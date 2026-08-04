from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from itertools import count
import json
import unittest

from lims_eln_implementation.bounded_caller import (
    BoundedCaller,
    BudgetPolicy,
    CallDecision,
    CallDenied,
    CallReceipt,
    CallRequest,
    CallerGrant,
    EffectClass,
    InMemoryApprovalStore,
    InMemoryBudgetLedger,
    InMemoryCallerGrantStore,
    InMemoryCallReceiptStore,
    InMemoryInvocationLedger,
    InvocationState,
    OperationApproval,
    OperationDefinition,
    OperationRegistry,
    StoredCallOutcome,
)
from lims_eln_implementation.bounded_examples import (
    InMemorySpecimenOperationBackend,
    SpecimenRecord,
    register_specimen_operations,
    specimen_resource,
)
from lims_eln_implementation.ports import ExternalRecord, WriteCertainty
from lims_eln_implementation.production_adapters import (
    AdapterVersionError,
    DbApiCallReceiptStore,
    DbApiInvocationLedger,
    DurableInvocationError,
    ResourceReleaseError,
    VendorSdkWrite,
    VersionBand,
    VersionedVendorGatewayAdapter,
)
from lims_eln_implementation.security import SignedTenantContext

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
TENANT = "SYN-TENANT-A"
ACTOR = "SYN-ACTOR-01"
CALLER = "svc-ai-1"
SPECIMEN_1 = "SYN-SPECIMEN-0001"
SPECIMEN_2 = "SYN-SPECIMEN-0002"


def tenant_context(tenant_id: str) -> SignedTenantContext:
    issued_at = int(NOW.timestamp())
    return SignedTenantContext(
        tenant_id=tenant_id,
        subject_id="SYN-SERVICE-IDENTITY-01",
        key_id="synthetic-test-v1",
        issued_at_epoch=issued_at,
        expires_at_epoch=issued_at + 300,
        nonce="SYNTHETIC-NONCE-0001",
        signature_hex="a" * 64,
    )


class BoundedCallerHarness:
    def __init__(
        self,
        *,
        caller_limit: int = 20,
        tenant_limit: int = 30,
        resource_limit: int = 3,
        payload_limit: int = 2_048,
    ) -> None:
        self.now = NOW
        self.backend = InMemorySpecimenOperationBackend(
            (
                SpecimenRecord(TENANT, SPECIMEN_1, 4, "available", "clear"),
                SpecimenRecord(TENANT, SPECIMEN_2, 2, "available", "clear"),
            )
        )
        self.registry = OperationRegistry()
        register_specimen_operations(self.registry, self.backend)
        self.grant = CallerGrant(
            grant_id="GRANT-1",
            caller_id=CALLER,
            actor_ids=frozenset({ACTOR}),
            tenant_id=TENANT,
            capabilities=frozenset(
                {
                    "specimen.read",
                    "specimen.review_flag.write",
                    "specimen.quarantine.bulk",
                }
            ),
            resource_prefixes=("specimen:SYN-",),
            expires_at=NOW + timedelta(hours=1),
        )
        self.grants = InMemoryCallerGrantStore((self.grant,))
        self.approvals = InMemoryApprovalStore()
        self.budgets = InMemoryBudgetLedger(
            BudgetPolicy(
                window_id="WINDOW-1",
                caller_call_limits={CALLER: caller_limit},
                tenant_call_limits={TENANT: tenant_limit},
                max_resources_per_call=resource_limit,
                max_payload_bytes=payload_limit,
            )
        )
        self.receipts = InMemoryCallReceiptStore()
        self.invocations = InMemoryInvocationLedger()
        receipt_numbers = count(1)
        self.caller = BoundedCaller(
            registry=self.registry,
            grants=self.grants,
            approvals=self.approvals,
            budgets=self.budgets,
            receipts=self.receipts,
            invocations=self.invocations,
            clock=lambda: self.now,
            receipt_id_factory=lambda: f"RECEIPT-{next(receipt_numbers):04d}",
        )

    def request(
        self,
        *,
        call_id: str,
        operation: str,
        resources: tuple[str, ...],
        payload: dict[str, object],
        approval_id: str | None = None,
        caller_id: str = CALLER,
        actor_id: str = ACTOR,
        tenant_id: str = TENANT,
        requested_at=NOW,
    ) -> CallRequest:
        return CallRequest(
            call_id=call_id,
            caller_id=caller_id,
            actor_id=actor_id,
            tenant_id=tenant_id,
            operation_name=operation,
            resource_ids=resources,
            payload=payload,
            requested_at=requested_at,
            approval_id=approval_id,
        )

    def read_request(self, call_id: str = "CALL-READ-1") -> CallRequest:
        return self.request(
            call_id=call_id,
            operation="specimen.read",
            resources=(specimen_resource(SPECIMEN_1),),
            payload={"specimen_id": SPECIMEN_1},
        )

    def narrow_request(self, call_id: str = "CALL-WRITE-1") -> CallRequest:
        return self.request(
            call_id=call_id,
            operation="specimen.review_flag.set",
            resources=(specimen_resource(SPECIMEN_1),),
            payload={
                "specimen_id": SPECIMEN_1,
                "expected_version": 4,
                "review_flag": "scientific-review",
            },
        )

    def broad_request(
        self,
        call_id: str = "CALL-BROAD-1",
        *,
        approval_id: str | None = "APPROVAL-1",
    ) -> CallRequest:
        return self.request(
            call_id=call_id,
            operation="specimen.quarantine.bulk",
            resources=(
                specimen_resource(SPECIMEN_1),
                specimen_resource(SPECIMEN_2),
            ),
            payload={
                "specimen_ids": [SPECIMEN_1, SPECIMEN_2],
                "reason_code": "quality-hold",
            },
            approval_id=approval_id,
        )

    def approve(
        self,
        request: CallRequest,
        *,
        approval_id: str = "APPROVAL-1",
        approved_by: str = "SYN-QUALITY-APPROVER-01",
        approved_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(minutes=30),
    ) -> OperationApproval:
        operation = self.registry.get(request.operation_name)
        assert operation is not None
        approval = OperationApproval.for_request(
            approval_id=approval_id,
            request=request,
            operation_version=operation.version,
            operation_contract_digest=operation.contract_digest,
            effect_class=EffectClass.APPROVAL_GATED_BROAD_WRITE,
            approved_by=approved_by,
            approved_at=approved_at,
            expires_at=expires_at,
        )
        self.approvals.put(approval)
        return approval


class BoundedCallerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = BoundedCallerHarness()

    def test_read_succeeds_and_exact_replay_reuses_the_outcome(self) -> None:
        request = self.harness.read_request()
        first = self.harness.caller.invoke(request)
        second = self.harness.caller.invoke(request)

        self.assertEqual(first.output, second.output)
        self.assertEqual(first.receipt.decision, CallDecision.SUCCEEDED)
        self.assertEqual(second.receipt.decision, CallDecision.REPLAYED)
        self.assertEqual(
            self.harness.budgets.snapshot(),
            {"caller": {CALLER: 1}, "tenant": {TENANT: 1}},
        )
        self.assertEqual(
            [receipt.decision for receipt in self.harness.receipts.for_call(request.call_id)],
            [
                CallDecision.AUTHORIZED,
                CallDecision.SUCCEEDED,
                CallDecision.REPLAYED,
            ],
        )

    def test_call_identity_collision_is_denied_and_attributable(self) -> None:
        request = self.harness.read_request()
        self.harness.caller.invoke(request)
        changed = replace(
            request,
            payload={"specimen_id": SPECIMEN_2},
            resource_ids=(specimen_resource(SPECIMEN_2),),
        )

        with self.assertRaises(CallDenied) as captured:
            self.harness.caller.invoke(changed)

        self.assertEqual(captured.exception.reason_code, "idempotency_content_collision")
        self.assertEqual(
            self.harness.receipts.for_call(request.call_id)[-1].reason_code,
            "idempotency_content_collision",
        )

    def test_narrow_write_executes_once_and_replays_the_committed_version(self) -> None:
        request = self.harness.narrow_request()
        first = self.harness.caller.invoke(request)
        second = self.harness.caller.invoke(request)

        self.assertEqual(first.output["version"], 5)
        self.assertEqual(second.output, first.output)
        self.assertEqual(second.receipt.decision, CallDecision.REPLAYED)
        stored = self.harness.backend.read(tenant_id=TENANT, specimen_id=SPECIMEN_1)
        self.assertEqual((stored.version, stored.review_flag), (5, "scientific-review"))

    def test_broad_write_requires_an_exact_independent_approval(self) -> None:
        request_without_approval = self.harness.broad_request(approval_id=None)
        with self.assertRaises(CallDenied) as captured:
            self.harness.caller.invoke(request_without_approval)
        self.assertEqual(captured.exception.reason_code, "approval_required")

        request = self.harness.broad_request(call_id="CALL-BROAD-2")
        self.harness.approve(request)
        result = self.harness.caller.invoke(request)

        self.assertEqual(result.output["affected_count"], 2)
        self.assertEqual(
            {record["lifecycle_state"] for record in result.output["records"]},
            {"quarantined"},
        )
        self.assertEqual(result.receipt.approval_id, "APPROVAL-1")

    def test_broad_write_approval_is_bound_to_one_call_identity(self) -> None:
        request = self.harness.broad_request()
        self.harness.approve(request)
        reused = replace(request, call_id="CALL-BROAD-REUSED")

        with self.assertRaises(CallDenied) as captured:
            self.harness.caller.invoke(reused)

        self.assertEqual(captured.exception.reason_code, "approval_scope_mismatch")

    def test_approval_scope_and_time_are_bound_to_the_requested_effect(self) -> None:
        request = self.harness.broad_request()
        self.harness.approve(request)
        changed = replace(
            request,
            payload={
                "specimen_ids": [SPECIMEN_1, SPECIMEN_2],
                "reason_code": "different-hold",
            },
        )
        with self.assertRaises(CallDenied) as captured:
            self.harness.caller.invoke(changed)
        self.assertEqual(captured.exception.reason_code, "approval_scope_mismatch")

        future_request = replace(
            request,
            call_id="CALL-BROAD-FUTURE",
            approval_id="APPROVAL-2",
            requested_at=NOW + timedelta(minutes=45),
        )
        future_approval = OperationApproval.for_request(
            approval_id="APPROVAL-2",
            request=future_request,
            operation_version="1.0.0",
            operation_contract_digest=self.harness.registry.get(
                "specimen.quarantine.bulk"
            ).contract_digest,  # type: ignore[union-attr]
            effect_class=EffectClass.APPROVAL_GATED_BROAD_WRITE,
            approved_by="SYN-QUALITY-APPROVER-01",
            approved_at=NOW - timedelta(minutes=5),
            expires_at=NOW + timedelta(minutes=30),
        )
        self.harness.approvals.put(future_approval)
        self.harness.now = NOW + timedelta(minutes=45)
        with self.assertRaises(CallDenied) as captured:
            self.harness.caller.invoke(future_request)
        self.assertEqual(captured.exception.reason_code, "approval_outside_time_window")

    def test_independent_approver_is_required_at_construction(self) -> None:
        request = self.harness.broad_request()
        operation = self.harness.registry.get(request.operation_name)
        assert operation is not None
        with self.assertRaisesRegex(ValueError, "independent accountable identity"):
            OperationApproval.for_request(
                approval_id="APPROVAL-SELF",
                request=request,
                operation_version=operation.version,
                operation_contract_digest=operation.contract_digest,
                effect_class=EffectClass.APPROVAL_GATED_BROAD_WRITE,
                approved_by=ACTOR,
                approved_at=NOW - timedelta(minutes=1),
                expires_at=NOW + timedelta(minutes=10),
            )

    def test_service_clock_controls_request_and_grant_expiry(self) -> None:
        self.harness.now = NOW + timedelta(minutes=10)
        with self.assertRaises(CallDenied) as captured:
            self.harness.caller.invoke(self.harness.read_request("CALL-STALE"))
        self.assertEqual(captured.exception.reason_code, "request_time_stale")

        self.harness.now = NOW + timedelta(hours=2)
        current_request = replace(
            self.harness.read_request("CALL-GRANT-EXPIRED"),
            requested_at=self.harness.now,
        )
        with self.assertRaises(CallDenied) as captured:
            self.harness.caller.invoke(current_request)
        self.assertEqual(captured.exception.reason_code, "caller_grant_expired")

    def test_revoked_grants_and_approvals_stop_at_service_time(self) -> None:
        self.harness.grants.revoke(
            CALLER,
            revoked_at=NOW - timedelta(seconds=1),
        )
        with self.assertRaises(CallDenied) as captured:
            self.harness.caller.invoke(self.harness.read_request("CALL-REVOKED-GRANT"))
        self.assertEqual(captured.exception.reason_code, "caller_grant_revoked")

        approval_harness = BoundedCallerHarness()
        request = approval_harness.broad_request("CALL-REVOKED-APPROVAL")
        approval_harness.approve(request)
        approval_harness.approvals.revoke(
            "APPROVAL-1",
            revoked_at=NOW - timedelta(seconds=1),
        )
        with self.assertRaises(CallDenied) as captured:
            approval_harness.caller.invoke(request)
        self.assertEqual(captured.exception.reason_code, "approval_revoked")

    def test_actor_tenant_capability_and_resource_boundaries_fail_closed(self) -> None:
        scenarios = (
            (
                replace(self.harness.read_request("CALL-ACTOR"), actor_id="SYN-ACTOR-02"),
                "actor_outside_grant",
            ),
            (
                replace(self.harness.read_request("CALL-TENANT"), tenant_id="SYN-TENANT-B"),
                "tenant_outside_grant",
            ),
            (
                replace(
                    self.harness.read_request("CALL-RESOURCE"),
                    resource_ids=("specimen:OTHER-0001",),
                    payload={"specimen_id": "OTHER-0001"},
                ),
                "resource_outside_grant",
            ),
        )
        for request, expected in scenarios:
            with self.subTest(reason=expected):
                with self.assertRaises(CallDenied) as captured:
                    self.harness.caller.invoke(request)
                self.assertEqual(captured.exception.reason_code, expected)

        narrow_only = replace(
            self.harness.grant,
            capabilities=frozenset({"specimen.read"}),
        )
        self.harness.grants.put(narrow_only)
        with self.assertRaises(CallDenied) as captured:
            self.harness.caller.invoke(self.harness.narrow_request("CALL-CAPABILITY"))
        self.assertEqual(captured.exception.reason_code, "capability_outside_grant")

    def test_resource_payload_and_call_budgets_have_distinct_reason_codes(self) -> None:
        resource_harness = BoundedCallerHarness(resource_limit=1)
        request = resource_harness.broad_request()
        resource_harness.approve(request)
        with self.assertRaises(CallDenied) as captured:
            resource_harness.caller.invoke(request)
        self.assertEqual(captured.exception.reason_code, "resource_budget_exceeded")

        payload_harness = BoundedCallerHarness(payload_limit=20)
        with self.assertRaises(CallDenied) as captured:
            payload_harness.caller.invoke(payload_harness.read_request())
        self.assertEqual(captured.exception.reason_code, "payload_budget_exceeded")

        call_harness = BoundedCallerHarness(caller_limit=1)
        call_harness.caller.invoke(call_harness.read_request("CALL-BUDGET-1"))
        with self.assertRaises(CallDenied) as captured:
            call_harness.caller.invoke(call_harness.read_request("CALL-BUDGET-2"))
        self.assertEqual(captured.exception.reason_code, "caller_budget_exhausted")

    def test_resource_prefixes_require_explicit_namespace_boundaries(self) -> None:
        for prefix in ("", "specimen:SYN", "specimen:\n"):
            with self.subTest(prefix=prefix):
                with self.assertRaisesRegex(
                    ValueError,
                    "printable namespace boundaries",
                ):
                    replace(self.harness.grant, resource_prefixes=(prefix,))

        with self.assertRaisesRegex(ValueError, "namespace-qualified"):
            replace(
                self.harness.read_request("CALL-RESOURCE-GRAMMAR"),
                resource_ids=("SYN-SPECIMEN-0001",),
            )

    def test_payload_and_replayed_output_use_immutable_canonical_snapshots(self) -> None:
        payload: dict[str, object] = {
            "specimen_ids": [SPECIMEN_1, SPECIMEN_2],
            "reason_code": "quality-hold",
        }
        request = self.harness.request(
            call_id="CALL-SNAPSHOT",
            operation="specimen.quarantine.bulk",
            resources=(
                specimen_resource(SPECIMEN_1),
                specimen_resource(SPECIMEN_2),
            ),
            payload=payload,
            approval_id="APPROVAL-SNAPSHOT",
        )
        self.harness.approve(request, approval_id="APPROVAL-SNAPSHOT")
        specimen_ids = payload["specimen_ids"]
        assert isinstance(specimen_ids, list)
        specimen_ids[0] = "SYN-SPECIMEN-MUTATED"

        first = self.harness.caller.invoke(request)
        records = first.output["records"]
        assert isinstance(records, list)
        records[0]["lifecycle_state"] = "caller-mutated"
        replay = self.harness.caller.invoke(request)

        self.assertEqual(
            [record["specimen_id"] for record in replay.output["records"]],
            [SPECIMEN_1, SPECIMEN_2],
        )
        self.assertEqual(
            {record["lifecycle_state"] for record in replay.output["records"]},
            {"quarantined"},
        )

    def test_authority_containers_are_immutable_construction_snapshots(self) -> None:
        actors = {ACTOR}
        capabilities = {"specimen.read"}
        prefixes = ["specimen:SYN-"]
        caller_limits = {CALLER: 2}
        tenant_limits = {TENANT: 3}
        resources = [specimen_resource(SPECIMEN_1)]
        grant = CallerGrant(
            grant_id="GRANT-SNAPSHOT",
            caller_id=CALLER,
            actor_ids=actors,
            tenant_id=TENANT,
            capabilities=capabilities,
            resource_prefixes=prefixes,
            expires_at=NOW + timedelta(hours=1),
        )
        policy = BudgetPolicy(
            window_id="WINDOW-SNAPSHOT",
            caller_call_limits=caller_limits,
            tenant_call_limits=tenant_limits,
            max_resources_per_call=2,
            max_payload_bytes=1_024,
        )
        request = CallRequest(
            call_id="CALL-AUTHORITY-SNAPSHOT",
            caller_id=CALLER,
            actor_id=ACTOR,
            tenant_id=TENANT,
            operation_name="specimen.read",
            resource_ids=resources,
            payload={"specimen_id": SPECIMEN_1},
            requested_at=NOW,
        )

        actors.add("SYN-UNISSUED-ACTOR")
        capabilities.add("specimen.quarantine.bulk")
        prefixes.append("specimen:OTHER-")
        caller_limits[CALLER] = 200
        tenant_limits[TENANT] = 300
        resources[0] = specimen_resource(SPECIMEN_2)

        self.assertEqual(grant.actor_ids, frozenset({ACTOR}))
        self.assertEqual(grant.capabilities, frozenset({"specimen.read"}))
        self.assertEqual(grant.resource_prefixes, ("specimen:SYN-",))
        self.assertEqual(policy.caller_call_limits[CALLER], 2)
        self.assertEqual(policy.tenant_call_limits[TENANT], 3)
        self.assertEqual(
            request.resource_ids,
            (specimen_resource(SPECIMEN_1),),
        )
        with self.assertRaises(TypeError):
            policy.caller_call_limits[CALLER] = 4  # type: ignore[index]
        with self.assertRaises(TypeError):
            request.payload["specimen_id"] = SPECIMEN_2  # type: ignore[index]

    def test_operation_contract_change_cannot_relabel_a_stored_replay(self) -> None:
        request = self.harness.read_request("CALL-CONTRACT-CHANGE")
        self.harness.caller.invoke(request)
        original = self.harness.registry.get("specimen.read")
        assert original is not None
        upgraded_registry = OperationRegistry()
        upgraded_registry.register(
            replace(
                original,
                version="1.1.0",
                contract_digest="b" * 64,
            )
        )
        upgraded = BoundedCaller(
            registry=upgraded_registry,
            grants=self.harness.grants,
            approvals=self.harness.approvals,
            budgets=self.harness.budgets,
            receipts=self.harness.receipts,
            invocations=self.harness.invocations,
            clock=lambda: self.harness.now,
        )

        with self.assertRaises(CallDenied) as captured:
            upgraded.invoke(request)

        self.assertEqual(captured.exception.reason_code, "idempotency_content_collision")

    def test_unregistered_and_invalid_operations_emit_denial_receipts(self) -> None:
        unknown = self.harness.request(
            call_id="CALL-UNKNOWN",
            operation="specimen.execute_sql",
            resources=(specimen_resource(SPECIMEN_1),),
            payload={"statement": "select 1"},
        )
        with self.assertRaises(CallDenied) as captured:
            self.harness.caller.invoke(unknown)
        self.assertEqual(captured.exception.reason_code, "operation_unregistered")
        self.assertEqual(
            self.harness.receipts.for_call("CALL-UNKNOWN")[0].effect_class,
            EffectClass.UNCLASSIFIED,
        )

        invalid = replace(
            self.harness.read_request("CALL-INVALID"),
            payload={"specimen_id": SPECIMEN_1, "extra": "field"},
        )
        with self.assertRaises(CallDenied) as captured:
            self.harness.caller.invoke(invalid)
        self.assertEqual(captured.exception.reason_code, "operation_input_invalid")
        self.assertEqual(
            [receipt.decision for receipt in self.harness.receipts.all()[-2:]],
            [CallDecision.DENIED, CallDecision.DENIED],
        )

    def test_execution_failure_releases_invocation_for_a_bounded_retry(self) -> None:
        attempts = 0

        def execute(_context, value):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("synthetic transient")
            return {"specimen_id": value["specimen_id"], "attempt": attempts}

        registry = OperationRegistry()
        registry.register(
            OperationDefinition(
                name="specimen.transient.read",
                version="1.0.0",
                contract_digest="a" * 64,
                effect_class=EffectClass.READ,
                capability="specimen.read",
                decode=lambda payload: dict(payload),
                resources=lambda value: (specimen_resource(value["specimen_id"]),),
                execute=execute,
                encode=lambda output: output,
            )
        )
        caller = BoundedCaller(
            registry=registry,
            grants=self.harness.grants,
            approvals=self.harness.approvals,
            budgets=self.harness.budgets,
            receipts=self.harness.receipts,
            invocations=self.harness.invocations,
            clock=lambda: NOW,
            receipt_id_factory=(
                lambda numbers=count(1): f"RETRY-RECEIPT-{next(numbers):04d}"
            ),
        )
        request = self.harness.request(
            call_id="CALL-RETRY",
            operation="specimen.transient.read",
            resources=(specimen_resource(SPECIMEN_1),),
            payload={"specimen_id": SPECIMEN_1},
        )

        with self.assertRaisesRegex(RuntimeError, "synthetic transient"):
            caller.invoke(request)
        result = caller.invoke(request)

        self.assertEqual(result.output["attempt"], 2)
        self.assertEqual(
            [receipt.decision for receipt in self.harness.receipts.for_call("CALL-RETRY")],
            [
                CallDecision.AUTHORIZED,
                CallDecision.FAILED,
                CallDecision.AUTHORIZED,
                CallDecision.SUCCEEDED,
            ],
        )

    def test_write_failure_enters_recovery_and_blocks_automatic_reexecution(self) -> None:
        attempts = 0

        def execute(_context, value):
            nonlocal attempts
            attempts += 1
            raise TimeoutError(f"ambiguous write for {value['specimen_id']}")

        registry = OperationRegistry()
        registry.register(
            OperationDefinition(
                name="specimen.ambiguous.write",
                version="1.0.0",
                contract_digest="c" * 64,
                effect_class=EffectClass.IDEMPOTENT_NARROW_WRITE,
                capability="specimen.review_flag.write",
                decode=lambda payload: dict(payload),
                resources=lambda value: (specimen_resource(value["specimen_id"]),),
                execute=execute,
                encode=lambda output: output,
            )
        )
        caller = BoundedCaller(
            registry=registry,
            grants=self.harness.grants,
            approvals=self.harness.approvals,
            budgets=self.harness.budgets,
            receipts=self.harness.receipts,
            invocations=self.harness.invocations,
            clock=lambda: NOW,
        )
        request = self.harness.request(
            call_id="CALL-AMBIGUOUS-WRITE",
            operation="specimen.ambiguous.write",
            resources=(specimen_resource(SPECIMEN_1),),
            payload={"specimen_id": SPECIMEN_1},
        )

        with self.assertRaisesRegex(TimeoutError, "ambiguous write"):
            caller.invoke(request)
        with self.assertRaises(CallDenied) as captured:
            caller.invoke(request)

        self.assertEqual(attempts, 1)
        self.assertEqual(
            captured.exception.reason_code,
            "invocation_recovery_required",
        )

    def test_authorization_receipt_failure_releases_pre_effect_reservation(self) -> None:
        class FailFirstReceiptStore(InMemoryCallReceiptStore):
            def __init__(self) -> None:
                super().__init__()
                self.remaining_failures = 1

            def append(self, receipt: CallReceipt) -> None:
                if self.remaining_failures:
                    self.remaining_failures -= 1
                    raise RuntimeError("synthetic authorization receipt failure")
                super().append(receipt)

        receipts = FailFirstReceiptStore()
        caller = BoundedCaller(
            registry=self.harness.registry,
            grants=self.harness.grants,
            approvals=self.harness.approvals,
            budgets=self.harness.budgets,
            receipts=receipts,
            invocations=self.harness.invocations,
            clock=lambda: NOW,
        )
        request = self.harness.read_request("CALL-RECEIPT-RECOVERY")

        with self.assertRaisesRegex(RuntimeError, "authorization receipt failure"):
            caller.invoke(request)
        result = caller.invoke(request)

        self.assertEqual(result.receipt.decision, CallDecision.SUCCEEDED)
        self.assertEqual(
            self.harness.backend.read(
                tenant_id=TENANT,
                specimen_id=SPECIMEN_1,
            ).version,
            4,
        )


class FakeCursor:
    def __init__(
        self,
        *,
        fail_insert: bool = False,
        fail_close: bool = False,
        responses: tuple[tuple[object, ...] | None, ...] | None = None,
    ) -> None:
        self.fail_insert = fail_insert
        self.fail_close = fail_close
        self.responses = list(responses) if responses is not None else None
        self.executions: list[tuple[str, tuple[object, ...]]] = []
        self.closed = False

    def execute(self, operation: str, parameters: tuple[object, ...]) -> None:
        self.executions.append((operation, parameters))
        if self.fail_insert and "insert into bounded_call_receipt" in operation:
            raise RuntimeError("synthetic insert failure")

    def fetchone(self) -> tuple[object, ...] | None:
        if self.responses is not None:
            return self.responses.pop(0)
        return (TENANT,)

    def close(self) -> None:
        self.closed = True
        if self.fail_close:
            raise RuntimeError("synthetic cursor release failure")


class FakeConnection:
    def __init__(self, cursor: FakeCursor, *, fail_close: bool = False) -> None:
        self._cursor = cursor
        self.fail_close = fail_close
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self._cursor

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True
        if self.fail_close:
            raise RuntimeError("synthetic connection release failure")


def sample_receipt() -> CallReceipt:
    return CallReceipt(
        receipt_id="RECEIPT-DB-1",
        call_id="CALL-DB-1",
        caller_id=CALLER,
        actor_id=ACTOR,
        tenant_id=TENANT,
        operation_name="specimen.read",
        operation_version="1.0.0",
        operation_contract_digest="0" * 64,
        effect_class=EffectClass.READ,
        resource_ids=(specimen_resource(SPECIMEN_1),),
        payload_digest="1" * 64,
        invocation_digest="2" * 64,
        decision=CallDecision.SUCCEEDED,
        reason_code="operation_completed",
        grant_id="GRANT-1",
        budget_window_id="WINDOW-1",
        approval_id=None,
        result_digest="3" * 64,
        requested_at=NOW,
        recorded_at=NOW,
    )


class ProductionReceiptAdapterTests(unittest.TestCase):
    def store(self, connection: FakeConnection) -> DbApiCallReceiptStore:
        return DbApiCallReceiptStore(
            lambda: connection,
            driver_name="psycopg",
            driver_version="3.2.4",
            qualified_band=VersionBand("psycopg", "3.2.0", "3.3.0"),
            tenant_context_provider=tenant_context,
        )

    def test_receipt_insert_binds_tenant_commits_and_releases_resources(self) -> None:
        cursor = FakeCursor()
        connection = FakeConnection(cursor)
        self.store(connection).append(sample_receipt())

        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)
        self.assertEqual(json.loads(cursor.executions[0][1][0])["tenant_id"], TENANT)
        self.assertIn("insert into bounded_call_receipt", cursor.executions[1][0])
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)

    def test_receipt_insert_rolls_back_and_releases_resources_on_failure(self) -> None:
        cursor = FakeCursor(fail_insert=True)
        connection = FakeConnection(cursor)
        with self.assertRaisesRegex(RuntimeError, "synthetic insert failure"):
            self.store(connection).append(sample_receipt())

        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)

    def test_release_failure_is_explicit_after_a_successful_commit(self) -> None:
        cursor = FakeCursor(fail_close=True)
        connection = FakeConnection(cursor)
        with self.assertRaisesRegex(ResourceReleaseError, "successful"):
            self.store(connection).append(sample_receipt())
        self.assertEqual(connection.commits, 1)
        self.assertTrue(connection.closed)

    def test_database_driver_must_remain_inside_the_qualified_band(self) -> None:
        connection = FakeConnection(FakeCursor())
        with self.assertRaises(AdapterVersionError):
            DbApiCallReceiptStore(
                lambda: connection,
                driver_name="psycopg",
                driver_version="3.3.0",
                qualified_band=VersionBand("psycopg", "3.2.0", "3.3.0"),
                tenant_context_provider=tenant_context,
            )

    def test_version_band_requires_complete_released_coordinates(self) -> None:
        for observed in (
            "3.2",
            "3.2.4-rc1",
            "3.2.4+local",
            "3.2.4unqualified",
            "03.2.4",
            "3.02.4",
        ):
            with self.subTest(observed=observed):
                with self.assertRaisesRegex(
                    AdapterVersionError,
                    "complete released",
                ):
                    VersionBand("psycopg", "3.2.0", "3.3.0").require(observed)

    def test_receipt_contract_rejects_digest_and_provenance_drift(self) -> None:
        with self.assertRaisesRegex(ValueError, "lowercase SHA-256"):
            replace(sample_receipt(), invocation_digest="sha256:" + "2" * 64)
        with self.assertRaisesRegex(ValueError, "require operation, invocation"):
            replace(sample_receipt(), grant_id=None)
        with self.assertRaisesRegex(ValueError, "require a result digest"):
            replace(sample_receipt(), result_digest=None)


class DurableInvocationAdapterTests(unittest.TestCase):
    LEASE = "00000000-0000-4000-8000-000000000001"
    CONTENT = "a" * 64
    CONTRACT = "b" * 64

    def ledger(
        self,
        *connections: FakeConnection,
    ) -> DbApiInvocationLedger:
        remaining = iter(connections)
        return DbApiInvocationLedger(
            lambda: next(remaining),
            driver_name="psycopg",
            driver_version="3.2.4",
            qualified_band=VersionBand("psycopg", "3.2.0", "3.3.0"),
            tenant_context_provider=tenant_context,
            clock=lambda: NOW,
            lease_duration=timedelta(seconds=30),
            lease_token_factory=lambda: self.LEASE,
        )

    def reserve(self, ledger: DbApiInvocationLedger):
        return ledger.reserve(
            TENANT,
            "CALL-DURABLE-1",
            self.CONTENT,
            operation_name="specimen.read",
            operation_version="1.0.0",
            operation_contract_digest=self.CONTRACT,
            evaluated_at=NOW,
        )

    def test_acquire_complete_and_replay_bind_lease_and_fencing_tokens(self) -> None:
        acquire_cursor = FakeCursor(responses=((TENANT,), (self.LEASE, 1)))
        complete_cursor = FakeCursor(responses=((TENANT,), ("CALL-DURABLE-1",)))
        replay_cursor = FakeCursor(
            responses=(
                (TENANT,),
                None,
                (
                    self.CONTENT,
                    "specimen.read",
                    "1.0.0",
                    self.CONTRACT,
                    "completed",
                    self.LEASE,
                    1,
                    NOW + timedelta(seconds=30),
                    {"specimen_id": SPECIMEN_1},
                    "d" * 64,
                    None,
                ),
            )
        )
        connections = (
            FakeConnection(acquire_cursor),
            FakeConnection(complete_cursor),
            FakeConnection(replay_cursor),
        )
        ledger = self.ledger(*connections)

        acquired = self.reserve(ledger)
        self.assertEqual(acquired.state, InvocationState.ACQUIRED)
        self.assertEqual((acquired.lease_token, acquired.fencing_token), (self.LEASE, 1))
        ledger.commit(
            TENANT,
            "CALL-DURABLE-1",
            self.CONTENT,
            lease_token=self.LEASE,
            fencing_token=1,
            outcome=StoredCallOutcome(
                operation_version="1.0.0",
                operation_contract_digest=self.CONTRACT,
                output_json='{"specimen_id":"SYN-SPECIMEN-0001"}',
                result_digest="d" * 64,
            ),
        )
        replay = self.reserve(ledger)

        self.assertEqual(replay.state, InvocationState.REPLAY)
        assert replay.outcome is not None
        self.assertEqual(replay.outcome.decoded_output()["specimen_id"], SPECIMEN_1)
        complete_parameters = complete_cursor.executions[1][1]
        self.assertEqual(complete_parameters[-2:], (self.LEASE, 1))
        self.assertTrue(all(connection.commits == 1 for connection in connections))
        self.assertTrue(all(connection.closed for connection in connections))

    def test_expired_lease_moves_to_owned_recovery_state(self) -> None:
        cursor = FakeCursor(
            responses=(
                (TENANT,),
                None,
                (
                    self.CONTENT,
                    "specimen.read",
                    "1.0.0",
                    self.CONTRACT,
                    "in_progress",
                    self.LEASE,
                    7,
                    NOW - timedelta(seconds=1),
                    None,
                    None,
                    None,
                ),
                ("lease_expired_before_completion",),
            )
        )
        ledger = self.ledger(FakeConnection(cursor))

        reservation = self.reserve(ledger)

        self.assertEqual(reservation.state, InvocationState.RECOVERY_REQUIRED)
        self.assertEqual(reservation.fencing_token, 7)
        self.assertEqual(
            reservation.recovery_reason,
            "lease_expired_before_completion",
        )
        self.assertIn("fencing_token = %s", cursor.executions[-1][0])

    def test_completion_cas_fails_when_lease_ownership_changed(self) -> None:
        cursor = FakeCursor(responses=((TENANT,), None))
        connection = FakeConnection(cursor)
        ledger = self.ledger(connection)

        with self.assertRaisesRegex(DurableInvocationError, "lost its lease"):
            ledger.commit(
                TENANT,
                "CALL-DURABLE-1",
                self.CONTENT,
                lease_token=self.LEASE,
                fencing_token=9,
                outcome=StoredCallOutcome(
                    operation_version="1.0.0",
                    operation_contract_digest=self.CONTRACT,
                    output_json='{"status":"complete"}',
                    result_digest="d" * 64,
                ),
            )

        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)

    def test_existing_call_identity_rejects_changed_semantic_content(self) -> None:
        cursor = FakeCursor(
            responses=(
                (TENANT,),
                None,
                (
                    "f" * 64,
                    "specimen.read",
                    "1.0.0",
                    self.CONTRACT,
                    "in_progress",
                    self.LEASE,
                    1,
                    NOW + timedelta(seconds=30),
                    None,
                    None,
                    None,
                ),
            )
        )
        connection = FakeConnection(cursor)
        ledger = self.ledger(connection)

        with self.assertRaises(CallDenied) as captured:
            self.reserve(ledger)

        self.assertEqual(
            captured.exception.reason_code,
            "idempotency_content_collision",
        )
        self.assertEqual(connection.rollbacks, 1)


class FakeVendorClient:
    sdk_name = "synthetic-sdk"
    sdk_version = "2.4.1"
    api_version = "2026-04-01"

    def __init__(
        self,
        *,
        timeout: bool = False,
        record: ExternalRecord | None = None,
        fail_close: bool = False,
        write_identity: str = "VENDOR-SPECIMEN-1",
        write_revision: int = 7,
    ) -> None:
        self.timeout = timeout
        self.record = record
        self.fail_close = fail_close
        self.write_identity = write_identity
        self.write_revision = write_revision
        self.closed = False

    def write_record(self, **_kwargs: object) -> VendorSdkWrite:
        if self.timeout:
            raise TimeoutError("synthetic ambiguous outcome")
        return VendorSdkWrite(self.write_identity, self.write_revision, "TRACE-1")

    def read_record(self, **_kwargs: object) -> ExternalRecord | None:
        return self.record

    def close(self) -> None:
        self.closed = True
        if self.fail_close:
            raise RuntimeError("synthetic vendor release failure")


class ProductionVendorAdapterTests(unittest.TestCase):
    def adapter(self, client: FakeVendorClient) -> VersionedVendorGatewayAdapter:
        return VersionedVendorGatewayAdapter(
            vendor_name="synthetic-vendor",
            client_factory=lambda: client,
            sdk_name="synthetic-sdk",
            qualified_sdk_band=VersionBand("synthetic-sdk", "2.4.0", "2.5.0"),
            required_api_version="2026-04-01",
        )

    def test_confirmed_and_ambiguous_writes_preserve_certainty(self) -> None:
        confirmed_client = FakeVendorClient()
        confirmed = self.adapter(confirmed_client).write(
            tenant_id=TENANT,
            external_identity="VENDOR-SPECIMEN-1",
            expected_revision=6,
            payload={"result": "12.5"},
            request_id="REQUEST-1",
        )
        self.assertEqual(confirmed.certainty, WriteCertainty.CONFIRMED)
        self.assertEqual(confirmed.revision, 7)
        self.assertTrue(confirmed_client.closed)

        ambiguous_client = FakeVendorClient(timeout=True)
        ambiguous = self.adapter(ambiguous_client).write(
            tenant_id=TENANT,
            external_identity="VENDOR-SPECIMEN-1",
            expected_revision=6,
            payload={"result": "12.5"},
            request_id="REQUEST-2",
        )
        self.assertEqual(ambiguous.certainty, WriteCertainty.AMBIGUOUS)
        self.assertIsNone(ambiguous.revision)
        self.assertTrue(ambiguous_client.closed)

    def test_readback_requires_the_requested_tenant_and_identity(self) -> None:
        client = FakeVendorClient(
            record=ExternalRecord(
                tenant_id="SYN-TENANT-B",
                external_identity="VENDOR-SPECIMEN-1",
                revision=7,
                canonical_digest="sha256:" + "3" * 64,
                payload={"result": "12.5"},
            )
        )
        with self.assertRaisesRegex(RuntimeError, "requested tenant"):
            self.adapter(client).read(
                tenant_id=TENANT,
                external_identity="VENDOR-SPECIMEN-1",
            )
        self.assertTrue(client.closed)

    def test_mismatched_confirmation_and_post_write_release_are_ambiguous(self) -> None:
        scenarios = (
            FakeVendorClient(write_identity="VENDOR-OTHER-1"),
            FakeVendorClient(write_revision=6),
            FakeVendorClient(fail_close=True),
        )
        for index, client in enumerate(scenarios, start=1):
            with self.subTest(index=index):
                result = self.adapter(client).write(
                    tenant_id=TENANT,
                    external_identity="VENDOR-SPECIMEN-1",
                    expected_revision=6,
                    payload={"result": "12.5"},
                    request_id=f"REQUEST-AMBIGUOUS-{index}",
                )
                self.assertEqual(result.certainty, WriteCertainty.AMBIGUOUS)
                self.assertEqual(result.external_identity, "VENDOR-SPECIMEN-1")
                self.assertIsNone(result.revision)

    def test_sdk_and_api_versions_are_checked_before_vendor_work(self) -> None:
        client = FakeVendorClient()
        client.sdk_version = "3.0.0"
        with self.assertRaises(AdapterVersionError):
            self.adapter(client).read(
                tenant_id=TENANT,
                external_identity="VENDOR-SPECIMEN-1",
            )
        self.assertTrue(client.closed)

    def test_vendor_release_failure_is_explicit(self) -> None:
        client = FakeVendorClient(fail_close=True)
        with self.assertRaisesRegex(ResourceReleaseError, "successful release"):
            self.adapter(client).read(
                tenant_id=TENANT,
                external_identity="VENDOR-SPECIMEN-1",
            )


if __name__ == "__main__":
    unittest.main()
