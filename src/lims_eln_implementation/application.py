"""Bounded application entry point for the inspectable specimen journey."""

from __future__ import annotations

from base64 import b64decode, b64encode
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping

from .bounded_caller import (
    BoundedCaller,
    BudgetPolicy,
    CallRequest,
    CallerGrant,
    EffectClass,
    InMemoryApprovalStore,
    InMemoryBudgetLedger,
    InMemoryCallerGrantStore,
    InMemoryCallReceiptStore,
    InMemoryInvocationLedger,
    OperationContext,
    OperationDefinition,
    OperationInputError,
    OperationRegistry,
)
from .bounded_examples import specimen_resource
from .custody import CustodyService
from .instrument import IngressResult, InstrumentEnvelope, InstrumentIngress
from .lifecycle import LifecycleService
from .model import (
    Command,
    DomainError,
    DomainEvent,
    SpecimenAggregate,
    SpecimenState,
    canonical_digest,
    require_aware_utc,
)
from .vendors import ProjectionOutcome, VendorProjectionService


_OPERATION_NAME = "specimen.golden_journey.execute"
_OPERATION_VERSION = "2.0.0"
_CAPABILITY = "specimen.golden_journey.execute"
_RECOVERY_OPERATION_NAME = "specimen.golden_journey.recover_instrument"
_RECOVERY_OPERATION_VERSION = "1.0.0"
_RECOVERY_CAPABILITY = "specimen.golden_journey.recover_instrument"


@dataclass(frozen=True, slots=True)
class GoldenSpecimenOutcome:
    aggregate: SpecimenAggregate
    instrument_digest: str
    projection: ProjectionOutcome
    custody_location: str
    call_receipt_id: str
    call_decision: str


class InstrumentReviewRequired(DomainError):
    """The raw instrument message has a named recovery route before release."""

    def __init__(self, result: IngressResult) -> None:
        self.result = result
        super().__init__(
            f"instrument review required ({result.reason_code}); {result.recovery}"
        )


@dataclass(frozen=True, slots=True)
class _GoldenSpecimenInput:
    specimen_id: str
    scientist_id: str
    quality_actor_id: str
    raw_instrument_json: bytes
    vendor_payload: Mapping[str, Any]

    @classmethod
    def decode(cls, payload: Mapping[str, Any]) -> _GoldenSpecimenInput:
        expected = {
            "specimen_id",
            "scientist_id",
            "quality_actor_id",
            "raw_instrument_base64",
            "vendor_payload",
        }
        if set(payload) != expected:
            raise OperationInputError(
                "golden specimen input requires specimen identity, instrument bytes, "
                "and vendor payload"
            )
        specimen_id = payload["specimen_id"]
        scientist_id = payload["scientist_id"]
        quality_actor_id = payload["quality_actor_id"]
        encoded = payload["raw_instrument_base64"]
        vendor_payload = payload["vendor_payload"]
        if not isinstance(specimen_id, str) or not specimen_id.strip():
            raise OperationInputError("specimen_id requires a populated identity")
        for name, value in (
            ("scientist_id", scientist_id),
            ("quality_actor_id", quality_actor_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise OperationInputError(f"{name} requires a populated identity")
        if not isinstance(encoded, str) or not encoded:
            raise OperationInputError("raw instrument content requires base64 text")
        if not isinstance(vendor_payload, Mapping):
            raise OperationInputError("vendor_payload requires an object")
        try:
            raw = b64decode(encoded, validate=True)
        except ValueError as error:
            raise OperationInputError(
                "raw instrument content requires canonical base64"
            ) from error
        if not raw or len(raw) > 1_048_576:
            raise OperationInputError(
                "raw instrument content requires 1..1048576 bytes"
            )
        return cls(
            specimen_id,
            scientist_id,
            quality_actor_id,
            raw,
            dict(vendor_payload),
        )


@dataclass(frozen=True, slots=True)
class _GoldenSpecimenRecoveryInput(_GoldenSpecimenInput):
    recovery_of_call_id: str

    @classmethod
    def decode(cls, payload: Mapping[str, Any]) -> _GoldenSpecimenRecoveryInput:
        expected = {
            "recovery_of_call_id",
            "specimen_id",
            "scientist_id",
            "quality_actor_id",
            "raw_instrument_base64",
            "vendor_payload",
        }
        if set(payload) != expected:
            raise OperationInputError(
                "instrument recovery input requires original call linkage, specimen "
                "identity, instrument bytes, role identities, and vendor payload"
            )
        recovery_of_call_id = payload["recovery_of_call_id"]
        if not isinstance(recovery_of_call_id, str) or not recovery_of_call_id.strip():
            raise OperationInputError(
                "recovery_of_call_id requires a populated identity"
            )
        initial = _GoldenSpecimenInput.decode(
            {
                key: value
                for key, value in payload.items()
                if key != "recovery_of_call_id"
            }
        )
        return cls(
            initial.specimen_id,
            initial.scientist_id,
            initial.quality_actor_id,
            initial.raw_instrument_json,
            initial.vendor_payload,
            recovery_of_call_id,
        )


def _require_permitted_role_actors(
    value: _GoldenSpecimenInput,
    permitted_actor_ids: frozenset[str],
) -> None:
    outside = {
        value.scientist_id,
        value.quality_actor_id,
    }.difference(permitted_actor_ids)
    if outside:
        raise OperationInputError(
            "scientific and quality actors require identities in the issued grant"
        )


def _decode_authorized_initial_input(
    payload: Mapping[str, Any],
    permitted_actor_ids: frozenset[str],
) -> _GoldenSpecimenInput:
    value = _GoldenSpecimenInput.decode(payload)
    _require_permitted_role_actors(value, permitted_actor_ids)
    return value


def _decode_authorized_recovery_input(
    payload: Mapping[str, Any],
    permitted_actor_ids: frozenset[str],
) -> _GoldenSpecimenRecoveryInput:
    value = _GoldenSpecimenRecoveryInput.decode(payload)
    _require_permitted_role_actors(value, permitted_actor_ids)
    return value


class _GoldenSpecimenWorkflow:
    """Internal operation implementation reachable through ``BoundedCaller``."""

    def __init__(
        self,
        *,
        lifecycle: LifecycleService,
        custody: CustodyService,
        ingress: InstrumentIngress,
        projection: VendorProjectionService,
        permitted_actor_ids: frozenset[str],
    ) -> None:
        self._lifecycle = lifecycle
        self._custody = custody
        self._ingress = ingress
        self._projection = projection
        self._permitted_actor_ids = frozenset(permitted_actor_ids)

    def execute(
        self,
        context: OperationContext,
        value: _GoldenSpecimenInput,
    ) -> GoldenSpecimenOutcome:
        self._authorize_role_actors(value)
        aggregate = self._lifecycle.register(
            _command(
                context=context,
                specimen_id=value.specimen_id,
                suffix="register",
                action="register",
                expected_version=0,
                payload={"specimen_type": "synthetic_plasma"},
            )
        )
        aggregate = self._lifecycle.transition(
            _command(
                context=context,
                specimen_id=value.specimen_id,
                suffix="accession",
                action="accession",
                expected_version=aggregate.version,
            )
        )
        position = self._custody.place(
            tenant_id=context.tenant_id,
            specimen_id=value.specimen_id,
            location="SYN-LAB-A/RECEIVING",
            custodian_id=context.actor_id,
            expected_version=0,
            transfer_id=f"{context.call_id}:custody:receiving",
            occurred_at=context.requested_at,
        )
        aggregate = self._lifecycle.transition(
            _command(
                context=context,
                specimen_id=value.specimen_id,
                suffix="start-processing",
                action="start_processing",
                expected_version=aggregate.version,
                payload={"assay_id": "SYN-ASSAY-01"},
            )
        )
        return self._complete_processing(
            context=context,
            value=value,
            aggregate=aggregate,
            custody_location=position.location,
        )

    def recover(
        self,
        context: OperationContext,
        value: _GoldenSpecimenInput,
    ) -> GoldenSpecimenOutcome:
        self._authorize_role_actors(value)
        if not isinstance(value, _GoldenSpecimenRecoveryInput):
            raise OperationInputError("instrument recovery requires recovery linkage")
        if value.recovery_of_call_id == context.call_id:
            raise OperationInputError(
                "instrument recovery requires a new call identity linked to the original call"
            )
        original = next(
            (
                (envelope, result)
                for envelope, result in self._ingress.quarantine
                if envelope.tenant_id == context.tenant_id
                and envelope.message_id == f"{value.recovery_of_call_id}:instrument"
            ),
            None,
        )
        if original is None:
            raise DomainError(
                f"call {value.recovery_of_call_id} requires a quarantined "
                "instrument receipt"
            )
        original_envelope, _ = original
        if original_envelope.specimen_id != value.specimen_id:
            raise DomainError(
                f"call {value.recovery_of_call_id} carries instrument review for specimen "
                f"{original_envelope.specimen_id}; resume that specimen"
            )
        aggregate = self._lifecycle.get(context.tenant_id, value.specimen_id)
        if aggregate is None:
            raise DomainError(
                f"specimen {value.specimen_id} requires an in-process journey before recovery"
            )
        if aggregate.state is not SpecimenState.IN_PROCESS:
            raise DomainError(
                f"specimen {value.specimen_id} is {aggregate.state.value}; "
                "instrument recovery continues from in_process"
            )
        position = self._custody.current(context.tenant_id, value.specimen_id)
        if position is None:
            raise DomainError(
                f"specimen {value.specimen_id} requires a custody position before recovery"
            )
        return self._complete_processing(
            context=context,
            value=value,
            aggregate=aggregate,
            custody_location=position.location,
        )

    def _complete_processing(
        self,
        *,
        context: OperationContext,
        value: _GoldenSpecimenInput,
        aggregate: SpecimenAggregate,
        custody_location: str,
    ) -> GoldenSpecimenOutcome:
        ingress = self._ingress.ingest(
            InstrumentEnvelope(
                tenant_id=context.tenant_id,
                message_id=f"{context.call_id}:instrument",
                instrument_id="SYN-INSTRUMENT-01",
                specimen_id=value.specimen_id,
                captured_at=context.requested_at,
                media_type="application/json",
                raw_bytes=value.raw_instrument_json,
            )
        )
        if ingress.normalized_digest is None:
            raise InstrumentReviewRequired(ingress)
        projection = self._projection.project(
            tenant_id=context.tenant_id,
            request_id=f"{context.call_id}:vendor-projection",
            external_identity=value.specimen_id,
            expected_revision=0,
            payload={
                **dict(value.vendor_payload),
                "instrument_digest": ingress.normalized_digest,
            },
        )
        aggregate = self._lifecycle.transition(
            _command(
                context=context,
                specimen_id=value.specimen_id,
                suffix="submit-review",
                action="submit_review",
                expected_version=aggregate.version,
                actor_id=value.scientist_id,
                payload={"review_id": f"{context.call_id}:scientific-review"},
            )
        )
        aggregate = self._lifecycle.transition(
            _command(
                context=context,
                specimen_id=value.specimen_id,
                suffix="release",
                action="release",
                expected_version=aggregate.version,
                actor_id=value.quality_actor_id,
                payload={"approval_receipt_id": f"{context.call_id}:quality-approval"},
                reason_code="scientific_review_complete",
            )
        )
        return GoldenSpecimenOutcome(
            aggregate=aggregate,
            instrument_digest=ingress.normalized_digest,
            projection=projection,
            custody_location=custody_location,
            call_receipt_id="pending",
            call_decision="pending",
        )

    def _authorize_role_actors(self, value: _GoldenSpecimenInput) -> None:
        _require_permitted_role_actors(value, self._permitted_actor_ids)


class GoldenSpecimenApplication:
    """Public boundary that can execute the journey only through bounded authority."""

    def __init__(self, *, caller: BoundedCaller, caller_id: str) -> None:
        if not caller_id.strip():
            raise ValueError("caller_id requires a workload identity")
        self._caller = caller
        self._caller_id = caller_id

    def process(
        self,
        *,
        call_id: str,
        tenant_id: str,
        specimen_id: str,
        actor_id: str,
        occurred_at: datetime,
        raw_instrument_json: bytes,
        vendor_payload: Mapping[str, Any],
        scientist_id: str | None = None,
        quality_actor_id: str | None = None,
    ) -> GoldenSpecimenOutcome:
        scientist = scientist_id or actor_id
        quality_actor = quality_actor_id or scientist
        result = self._caller.invoke(
            CallRequest(
                call_id=call_id,
                caller_id=self._caller_id,
                actor_id=actor_id,
                tenant_id=tenant_id,
                operation_name=_OPERATION_NAME,
                resource_ids=(specimen_resource(specimen_id),),
                payload={
                    "specimen_id": specimen_id,
                    "scientist_id": scientist,
                    "quality_actor_id": quality_actor,
                    "raw_instrument_base64": b64encode(raw_instrument_json).decode(
                        "ascii"
                    ),
                    "vendor_payload": dict(vendor_payload),
                },
                requested_at=require_aware_utc(occurred_at),
            )
        )
        return _outcome_with_receipt(
            result.output,
            receipt_id=result.receipt.receipt_id,
            decision=result.receipt.decision.value,
        )

    def resume_after_instrument_review(
        self,
        *,
        recovery_of_call_id: str,
        call_id: str,
        tenant_id: str,
        specimen_id: str,
        actor_id: str,
        scientist_id: str,
        quality_actor_id: str,
        occurred_at: datetime,
        raw_instrument_json: bytes,
        vendor_payload: Mapping[str, Any],
    ) -> GoldenSpecimenOutcome:
        """Continue a quarantined journey through a distinct bounded call."""
        if recovery_of_call_id == call_id:
            raise OperationInputError(
                "instrument recovery requires a new call identity linked to the original call"
            )
        result = self._caller.invoke(
            CallRequest(
                call_id=call_id,
                caller_id=self._caller_id,
                actor_id=actor_id,
                tenant_id=tenant_id,
                operation_name=_RECOVERY_OPERATION_NAME,
                resource_ids=(specimen_resource(specimen_id),),
                payload={
                    "recovery_of_call_id": recovery_of_call_id,
                    "specimen_id": specimen_id,
                    "scientist_id": scientist_id,
                    "quality_actor_id": quality_actor_id,
                    "raw_instrument_base64": b64encode(raw_instrument_json).decode(
                        "ascii"
                    ),
                    "vendor_payload": dict(vendor_payload),
                },
                requested_at=require_aware_utc(occurred_at),
            )
        )
        return _outcome_with_receipt(
            result.output,
            receipt_id=result.receipt.receipt_id,
            decision=result.receipt.decision.value,
        )


def register_golden_specimen_operation(
    registry: OperationRegistry,
    *,
    lifecycle: LifecycleService,
    custody: CustodyService,
    ingress: InstrumentIngress,
    projection: VendorProjectionService,
    permitted_actor_ids: frozenset[str],
) -> None:
    """Register initial and recovery paths for the composed specimen workflow."""

    workflow = _GoldenSpecimenWorkflow(
        lifecycle=lifecycle,
        custody=custody,
        ingress=ingress,
        projection=projection,
        permitted_actor_ids=permitted_actor_ids,
    )
    contract_digest = canonical_digest(
        {
            "name": _OPERATION_NAME,
            "version": _OPERATION_VERSION,
            "effect_class": EffectClass.IDEMPOTENT_NARROW_WRITE.value,
            "capability": _CAPABILITY,
            "fields": [
                "raw_instrument_base64",
                "specimen_id",
                "scientist_id",
                "quality_actor_id",
                "vendor_payload",
            ],
        }
    )
    registry.register(
        OperationDefinition[
            _GoldenSpecimenInput,
            GoldenSpecimenOutcome,
        ](
            name=_OPERATION_NAME,
            version=_OPERATION_VERSION,
            contract_digest=contract_digest,
            effect_class=EffectClass.IDEMPOTENT_NARROW_WRITE,
            capability=_CAPABILITY,
            decode=lambda payload: _decode_authorized_initial_input(
                payload,
                permitted_actor_ids,
            ),
            resources=lambda value: (specimen_resource(value.specimen_id),),
            execute=workflow.execute,
            encode=_encode_outcome,
        )
    )
    recovery_contract_digest = canonical_digest(
        {
            "name": _RECOVERY_OPERATION_NAME,
            "version": _RECOVERY_OPERATION_VERSION,
            "effect_class": EffectClass.IDEMPOTENT_NARROW_WRITE.value,
            "capability": _RECOVERY_CAPABILITY,
            "fields": [
                "quality_actor_id",
                "raw_instrument_base64",
                "recovery_of_call_id",
                "scientist_id",
                "specimen_id",
                "vendor_payload",
            ],
        }
    )
    registry.register(
        OperationDefinition[
            _GoldenSpecimenRecoveryInput,
            GoldenSpecimenOutcome,
        ](
            name=_RECOVERY_OPERATION_NAME,
            version=_RECOVERY_OPERATION_VERSION,
            contract_digest=recovery_contract_digest,
            effect_class=EffectClass.IDEMPOTENT_NARROW_WRITE,
            capability=_RECOVERY_CAPABILITY,
            decode=lambda payload: _decode_authorized_recovery_input(
                payload,
                permitted_actor_ids,
            ),
            resources=lambda value: (specimen_resource(value.specimen_id),),
            execute=workflow.recover,
            encode=_encode_outcome,
        )
    )


def build_reference_golden_specimen_application(
    *,
    lifecycle: LifecycleService,
    custody: CustodyService,
    ingress: InstrumentIngress,
    projection: VendorProjectionService,
    tenant_id: str,
    caller_id: str,
    actor_ids: frozenset[str],
    clock: Callable[[], datetime],
) -> GoldenSpecimenApplication:
    """Compose a complete local proof with explicit, bounded authority stores.

    Production composition supplies durable grant, budget, invocation, and
    receipt stores to ``BoundedCaller`` while preserving this public boundary.
    """

    registry = OperationRegistry()
    register_golden_specimen_operation(
        registry,
        lifecycle=lifecycle,
        custody=custody,
        ingress=ingress,
        projection=projection,
        permitted_actor_ids=actor_ids,
    )
    now = require_aware_utc(clock())
    caller = BoundedCaller(
        registry=registry,
        grants=InMemoryCallerGrantStore(
            (
                CallerGrant(
                    grant_id=f"reference:{caller_id}",
                    caller_id=caller_id,
                    actor_ids=actor_ids,
                    tenant_id=tenant_id,
                    capabilities=frozenset({_CAPABILITY, _RECOVERY_CAPABILITY}),
                    resource_prefixes=("specimen:SYN-", "specimen:SPM-SYN-"),
                    expires_at=now + timedelta(hours=1),
                ),
            )
        ),
        approvals=InMemoryApprovalStore(),
        budgets=InMemoryBudgetLedger(
            BudgetPolicy(
                window_id="reference-hour",
                caller_call_limits={caller_id: 100},
                tenant_call_limits={tenant_id: 500},
                max_resources_per_call=1,
                max_payload_bytes=1_400_000,
            )
        ),
        receipts=InMemoryCallReceiptStore(),
        invocations=InMemoryInvocationLedger(),
        clock=clock,
    )
    return GoldenSpecimenApplication(caller=caller, caller_id=caller_id)


def _command(
    *,
    context: OperationContext,
    specimen_id: str,
    suffix: str,
    action: str,
    expected_version: int,
    payload: Mapping[str, Any] | None = None,
    actor_id: str | None = None,
    reason_code: str | None = None,
) -> Command:
    return Command(
        command_id=f"{context.call_id}:{suffix}",
        tenant_id=context.tenant_id,
        specimen_id=specimen_id,
        actor_id=actor_id or context.actor_id,
        action=action,
        expected_version=expected_version,
        occurred_at=context.requested_at,
        payload=dict(payload or {}),
        reason_code=reason_code,
    )


def _encode_event(event: DomainEvent) -> Mapping[str, Any]:
    return {
        "event_id": event.event_id,
        "tenant_id": event.tenant_id,
        "specimen_id": event.specimen_id,
        "aggregate_version": event.aggregate_version,
        "event_type": event.event_type,
        "actor_id": event.actor_id,
        "command_id": event.command_id,
        "command_digest": event.command_digest,
        "occurred_at": event.occurred_at.isoformat(),
        "payload": dict(event.payload),
        "reason_code": event.reason_code,
    }


def _encode_outcome(outcome: GoldenSpecimenOutcome) -> Mapping[str, Any]:
    return {
        "aggregate": {
            "tenant_id": outcome.aggregate.tenant_id,
            "specimen_id": outcome.aggregate.specimen_id,
            "state": outcome.aggregate.state.value,
            "version": outcome.aggregate.version,
            "attributes": dict(outcome.aggregate.attributes),
            "events": [_encode_event(event) for event in outcome.aggregate.events],
        },
        "instrument_digest": outcome.instrument_digest,
        "projection": {
            "vendor_name": outcome.projection.vendor_name,
            "external_identity": outcome.projection.external_identity,
            "revision": outcome.projection.revision,
            "canonical_digest": outcome.projection.canonical_digest,
            "reconciled": outcome.projection.reconciled,
            "trace_id": outcome.projection.trace_id,
        },
        "custody_location": outcome.custody_location,
    }


def _decode_outcome(value: Mapping[str, Any]) -> GoldenSpecimenOutcome:
    aggregate_value = value["aggregate"]
    projection_value = value["projection"]
    assert isinstance(aggregate_value, Mapping)
    assert isinstance(projection_value, Mapping)
    events = tuple(
        DomainEvent(
            event_id=str(event["event_id"]),
            tenant_id=str(event["tenant_id"]),
            specimen_id=str(event["specimen_id"]),
            aggregate_version=int(event["aggregate_version"]),
            event_type=str(event["event_type"]),
            actor_id=str(event["actor_id"]),
            command_id=str(event["command_id"]),
            command_digest=str(event["command_digest"]),
            occurred_at=datetime.fromisoformat(str(event["occurred_at"])),
            payload=dict(event["payload"]),
            reason_code=(
                None if event["reason_code"] is None else str(event["reason_code"])
            ),
        )
        for event in aggregate_value["events"]
    )
    aggregate = SpecimenAggregate(
        tenant_id=str(aggregate_value["tenant_id"]),
        specimen_id=str(aggregate_value["specimen_id"]),
        state=SpecimenState(str(aggregate_value["state"])),
        version=int(aggregate_value["version"]),
        attributes=dict(aggregate_value["attributes"]),
        events=events,
    )
    projection = ProjectionOutcome(
        vendor_name=str(projection_value["vendor_name"]),
        external_identity=str(projection_value["external_identity"]),
        revision=int(projection_value["revision"]),
        canonical_digest=str(projection_value["canonical_digest"]),
        reconciled=bool(projection_value["reconciled"]),
        trace_id=str(projection_value["trace_id"]),
    )
    return GoldenSpecimenOutcome(
        aggregate=aggregate,
        instrument_digest=str(value["instrument_digest"]),
        projection=projection,
        custody_location=str(value["custody_location"]),
        call_receipt_id="decoded-before-receipt",
        call_decision="decoded-before-receipt",
    )


def _outcome_with_receipt(
    value: Mapping[str, Any],
    *,
    receipt_id: str,
    decision: str,
) -> GoldenSpecimenOutcome:
    outcome = _decode_outcome(value)
    return GoldenSpecimenOutcome(
        aggregate=outcome.aggregate,
        instrument_digest=outcome.instrument_digest,
        projection=outcome.projection,
        custody_location=outcome.custody_location,
        call_receipt_id=receipt_id,
        call_decision=decision,
    )
