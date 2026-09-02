"""One PostgreSQL-backed Golden Specimen vertical slice.

The adapter composes one named journey rather than introducing a general
persistence framework. Every accepted mutation shares one DB-API transaction,
and every returned document is rebuilt in a fresh tenant-bound transaction.
"""

# Stored row-shape violations are runtime integrity failures, not caller type errors.
# ruff: noqa: TRY004

from __future__ import annotations

import json
from base64 import b64encode
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from uuid import UUID, uuid4, uuid5

from ..application import (
    InstrumentReviewRequired,
    golden_specimen_operation_contract,
)
from ..bounded_caller import (
    BudgetPolicy,
    CallDenied,
    CallerGrant,
    CallRequest,
    InMemoryBudgetLedger,
)
from ..idempotency import ContentCollision, IdempotencyInProgress
from ..instrument import IngressDisposition, IngressResult, InstrumentEnvelope, InstrumentIngress
from ..lifecycle import LifecycleService
from ..model import (
    Command,
    DomainError,
    DomainEvent,
    SpecimenAggregate,
    SpecimenState,
    canonical_digest,
    require_aware_utc,
)
from ..security import (
    PostgresTenantBinding,
    TenantContextProvider,
    TenantSessionBindingError,
)
from ..store import InMemorySpecimenRepository
from ..vendors import FaultMode, InMemoryVendorGateway, ProjectionOutcome, VendorProjectionService
from .service import ObservationAbsent, SpecimenAbsent
from .shared_contracts import SharedContractUnavailable, build_observation, contract_available

_EXECUTE_OPERATION = golden_specimen_operation_contract("initial")[0]
_RECOVERY_OPERATION = golden_specimen_operation_contract("instrument_recovery")[0]
_RECEIPT_NAMESPACE = UUID("2802b71f-acde-48a5-b4f8-871359522ba1")


class Cursor(Protocol):
    def execute(self, operation: str, parameters: tuple[Any, ...] = ()) -> Any: ...

    def fetchone(self) -> Sequence[Any] | None: ...

    def fetchall(self) -> Sequence[Sequence[Any]]: ...

    def close(self) -> None: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...


ConnectionFactory = Callable[[], Connection]
FailureProbe = Callable[[str], None]


@contextmanager
def _transaction(connection_factory: ConnectionFactory) -> Iterator[Cursor]:
    """Own one transaction and release its cursor and connection explicitly."""

    connection = connection_factory()
    cursor: Cursor | None = None
    primary_error: BaseException | None = None
    try:
        cursor = connection.cursor()
        yield cursor
        connection.commit()
    except BaseException as error:
        primary_error = error
        try:
            connection.rollback()
        except Exception as rollback_error:  # noqa: BLE001
            primary_error.add_note(
                "PostgreSQL rollback also failed with "
                f"{type(rollback_error).__name__}; the primary error remains authoritative"
            )
        raise
    finally:
        release_error: Exception | None = None
        if cursor is not None:
            try:
                cursor.close()
            except Exception as error:  # noqa: BLE001
                release_error = error
        try:
            connection.close()
        except Exception as error:  # noqa: BLE001
            release_error = release_error or error
        if primary_error is None and release_error is not None:
            raise RuntimeError(
                "PostgreSQL workbench resources require complete release"
            ) from release_error


@dataclass(frozen=True, slots=True)
class _JourneyPlan:
    aggregate: SpecimenAggregate
    new_events: tuple[DomainEvent, ...]
    ingress: IngressResult
    message_id: str
    instrument_id: str
    captured_at: datetime
    projection: ProjectionOutcome | None
    receipt_id: str
    recovery_of_run_id: str | None = None


@dataclass(frozen=True, slots=True)
class _Reservation:
    state: str
    coordinate: Mapping[str, Any] | None = None
    lease_token: str | None = None
    fencing_token: int | None = None


@dataclass(frozen=True, slots=True)
class _NormalizedMeasurementFact:
    analyte: str
    decimal: str
    precision: int
    scale: int
    unit_code: str
    unit_system: str


class PostgresWorkbenchService:
    """Durable composition root for one synthetic Golden Specimen journey."""

    state_adapter = "postgresql"

    def __init__(
        self,
        connection_factory: ConnectionFactory,
        *,
        tenant_context_provider: TenantContextProvider,
        tenant_id: str = "SYN-TENANT-A",
        caller_id: str = "svc-golden-specimen-workbench",
        actor_ids: frozenset[str] | None = None,
        failure_probe: FailureProbe | None = None,
    ) -> None:
        self._connection_factory = connection_factory
        self._tenant_context_provider = tenant_context_provider
        self._tenant_id = tenant_id
        self._caller_id = caller_id
        self._permitted_actor_ids = actor_ids or frozenset(
            {"SYN-ACTOR-01", "SYN-SCIENTIST-01", "SYN-QUALITY-01"}
        )
        now = datetime.now(UTC)
        self._grant = CallerGrant(
            grant_id=f"reference:{caller_id}",
            caller_id=caller_id,
            actor_ids=self._permitted_actor_ids,
            tenant_id=tenant_id,
            capabilities=frozenset({_EXECUTE_OPERATION, _RECOVERY_OPERATION}),
            resource_prefixes=("specimen:SYN-", "specimen:SPM-SYN-"),
            expires_at=now + timedelta(hours=1),
        )
        self._budget = InMemoryBudgetLedger(
            BudgetPolicy(
                window_id="reference-hour",
                caller_call_limits={caller_id: 100},
                tenant_call_limits={tenant_id: 500},
                max_resources_per_call=1,
                max_payload_bytes=1_400_000,
            )
        )
        self._failure_probe = failure_probe or (lambda _: None)

    def run_golden_specimen(
        self,
        *,
        run_id: str,
        tenant_id: str,
        specimen_id: str,
        actor_id: str,
        scientist_id: str,
        quality_actor_id: str,
        occurred_at: datetime,
        raw_instrument_json: bytes,
        vendor_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self._execute(
            mode="initial",
            recovery_of_run_id=None,
            run_id=run_id,
            tenant_id=tenant_id,
            specimen_id=specimen_id,
            actor_id=actor_id,
            scientist_id=scientist_id,
            quality_actor_id=quality_actor_id,
            occurred_at=occurred_at,
            raw_instrument_json=raw_instrument_json,
            vendor_payload=vendor_payload,
        )

    def resume_instrument_review(
        self,
        *,
        recovery_of_run_id: str,
        run_id: str,
        tenant_id: str,
        specimen_id: str,
        actor_id: str,
        scientist_id: str,
        quality_actor_id: str,
        occurred_at: datetime,
        raw_instrument_json: bytes,
        vendor_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        if recovery_of_run_id == run_id:
            raise DomainError(
                "instrument recovery requires a new run identity linked to the original run"
            )
        return self._execute(
            mode="instrument_recovery",
            recovery_of_run_id=recovery_of_run_id,
            run_id=run_id,
            tenant_id=tenant_id,
            specimen_id=specimen_id,
            actor_id=actor_id,
            scientist_id=scientist_id,
            quality_actor_id=quality_actor_id,
            occurred_at=occurred_at,
            raw_instrument_json=raw_instrument_json,
            vendor_payload=vendor_payload,
        )

    def specimen(self, tenant_id: str, specimen_id: str) -> dict[str, Any]:
        self._authorize(tenant_id, frozenset())
        with self._bound_transaction(tenant_id) as cursor:
            return self._load_specimen(cursor, tenant_id, specimen_id)

    def observation(self, tenant_id: str, run_id: str) -> dict[str, Any]:
        self._authorize(tenant_id, frozenset())
        result = self._load_run(tenant_id, run_id)
        observation = result.get("observation")
        if not isinstance(observation, Mapping):
            raise ObservationAbsent(
                f"run {run_id} has no shared observation for tenant {tenant_id}; "
                "install the accepted contract package and reload the durable run"
            )
        return dict(observation)

    def summary(self, tenant_id: str) -> dict[str, Any]:
        self._authorize(tenant_id, frozenset())
        with self._bound_transaction(tenant_id) as cursor:
            cursor.execute(
                """
                select specimen_id, lifecycle_state, aggregate_version,
                       open_instrument_review_count, quarantine_history_count,
                       pending_outbox_count
                  from public.specimen_workbench_snapshot
                 where tenant_id = %s
                 order by specimen_id
                """,
                (tenant_id,),
            )
            rows = cursor.fetchall()
            cursor.execute(
                """
                select count(*)
                  from public.instrument_inbox
                 where tenant_id = %s
                """,
                (tenant_id,),
            )
            receipt_row = cursor.fetchone()
        lifecycle: dict[str, int] = {}
        for row in rows:
            lifecycle[str(row[1])] = lifecycle.get(str(row[1]), 0) + 1
        return {
            "tenant_id": tenant_id,
            "specimen_count": len(rows),
            "lifecycle_counts": dict(sorted(lifecycle.items())),
            "instrument_receipt_count": int(receipt_row[0]) if receipt_row else 0,
            "quarantine_count": sum(int(row[3]) for row in rows),
            "quarantine_history_count": sum(int(row[4]) for row in rows),
            "pending_outbox_count": sum(int(row[5]) for row in rows),
            "shared_contract": {
                "available": contract_available(),
                "contract_version": "1.0.0",
            },
            "specimens": [
                {
                    "specimen_id": str(row[0]),
                    "state": str(row[1]),
                    "version": int(row[2]),
                }
                for row in rows
            ],
        }

    @contextmanager
    def _bound_transaction(self, tenant_id: str) -> Iterator[Cursor]:
        context = self._tenant_context_provider(tenant_id)
        if context.subject_id != self._caller_id:
            raise TenantSessionBindingError(
                "tenant authority belongs to another workload identity; "
                "route the request through its matching composition root"
            )
        with _transaction(self._connection_factory) as cursor:
            cursor.execute("set transaction isolation level repeatable read")
            PostgresTenantBinding(context).bind(
                cursor,
                expected_tenant_id=tenant_id,
            )
            yield cursor

    def _authorize(self, tenant_id: str, actor_ids: frozenset[str]) -> None:
        if tenant_id != self._tenant_id:
            raise CallDenied(
                "tenant_outside_workbench_authority",
                "the requested tenant requires its matching workbench composition",
            )
        if not actor_ids.issubset(self._permitted_actor_ids):
            raise CallDenied(
                "actor_outside_workbench_authority",
                "every accountable actor requires an identity in the workbench grant",
            )

    def _execute(
        self,
        *,
        mode: str,
        recovery_of_run_id: str | None,
        run_id: str,
        tenant_id: str,
        specimen_id: str,
        actor_id: str,
        scientist_id: str,
        quality_actor_id: str,
        occurred_at: datetime,
        raw_instrument_json: bytes,
        vendor_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        for name, value in (
            ("run_id", run_id),
            ("tenant_id", tenant_id),
            ("specimen_id", specimen_id),
            ("actor_id", actor_id),
            ("scientist_id", scientist_id),
            ("quality_actor_id", quality_actor_id),
        ):
            if not value.strip():
                raise DomainError(f"{name} requires a non-empty value")
        self._authorize(
            tenant_id,
            frozenset({actor_id, scientist_id, quality_actor_id}),
        )
        occurred_at = require_aware_utc(occurred_at)
        request_received_at = datetime.now(UTC)
        operation_name, operation_version, operation_digest = _operation_contract(mode)
        payload: dict[str, Any] = {
            "specimen_id": specimen_id,
            "scientist_id": scientist_id,
            "quality_actor_id": quality_actor_id,
            "occurred_at": _timestamp(occurred_at),
            "raw_instrument_base64": b64encode(raw_instrument_json).decode("ascii"),
            "vendor_payload": dict(vendor_payload),
        }
        if recovery_of_run_id is not None:
            payload["recovery_of_call_id"] = recovery_of_run_id
        authority_request = CallRequest(
            call_id=run_id,
            caller_id=self._caller_id,
            actor_id=actor_id,
            tenant_id=tenant_id,
            operation_name=operation_name,
            resource_ids=(f"specimen:{specimen_id}",),
            payload=payload,
            requested_at=request_received_at,
        )
        run_digest = authority_request.invocation_digest(
            operation_version=operation_version,
            operation_contract_digest=operation_digest,
        )
        review_required: InstrumentReviewRequired | None = None
        with self._bound_transaction(tenant_id) as cursor:
            reservation = self._reserve_invocation(
                cursor,
                mode=mode,
                tenant_id=tenant_id,
                run_id=run_id,
                run_digest=run_digest,
            )
            if reservation.state == "completed":
                pass
            elif reservation.state == "recovery_required":
                review_required = InstrumentReviewRequired(
                    self._load_quarantine(cursor, tenant_id, run_id)
                )
            else:
                self._grant.authorize(
                    authority_request,
                    capability=operation_name,
                    evaluated_at=request_received_at,
                )
                self._budget.reserve(authority_request)
                if mode == "initial":
                    plan = self._plan_initial(
                        run_id=run_id,
                        tenant_id=tenant_id,
                        specimen_id=specimen_id,
                        actor_id=actor_id,
                        scientist_id=scientist_id,
                        quality_actor_id=quality_actor_id,
                        occurred_at=occurred_at,
                        raw_instrument_json=raw_instrument_json,
                        vendor_payload=vendor_payload,
                    )
                else:
                    assert recovery_of_run_id is not None
                    plan = self._plan_recovery(
                        cursor,
                        recovery_of_run_id=recovery_of_run_id,
                        run_id=run_id,
                        tenant_id=tenant_id,
                        specimen_id=specimen_id,
                        actor_id=actor_id,
                        scientist_id=scientist_id,
                        quality_actor_id=quality_actor_id,
                        occurred_at=occurred_at,
                        raw_instrument_json=raw_instrument_json,
                        vendor_payload=vendor_payload,
                    )
                    if plan.ingress.normalized_observation is None:
                        raise InstrumentReviewRequired(plan.ingress)
                self._failure_probe("after_plan")
                self._materialize(
                    cursor,
                    plan=plan,
                    mode=mode,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    specimen_id=specimen_id,
                    actor_id=actor_id,
                    scientist_id=scientist_id,
                    quality_actor_id=quality_actor_id,
                    occurred_at=occurred_at,
                    run_digest=run_digest,
                    authority_request=authority_request,
                    lease_token=reservation.lease_token,
                    fencing_token=reservation.fencing_token,
                )
                if plan.ingress.normalized_observation is None:
                    review_required = InstrumentReviewRequired(plan.ingress)
                self._failure_probe("before_commit")
        if review_required is not None:
            raise review_required
        return self._load_run(tenant_id, run_id)

    def _reserve_invocation(
        self,
        cursor: Cursor,
        *,
        mode: str,
        tenant_id: str,
        run_id: str,
        run_digest: str,
    ) -> _Reservation:
        operation, version, contract_digest = _operation_contract(mode)
        lease_token = str(uuid4())
        cursor.execute(
            """
            insert into public.bounded_call_invocation (
                tenant_id, call_id, invocation_sha256, operation_name,
                operation_version, operation_contract_sha256, state,
                lease_token, fencing_token, lease_expires_at_utc
            ) values (
                %s, %s, %s, %s, %s, %s, 'in_progress', %s::uuid, 1,
                transaction_timestamp() + interval '5 minutes'
            )
            on conflict (tenant_id, call_id) do nothing
            returning state, lease_token::text, fencing_token
            """,
            (
                tenant_id,
                run_id,
                run_digest,
                operation,
                version,
                contract_digest,
                lease_token,
            ),
        )
        inserted = cursor.fetchone()
        if inserted is not None:
            return _Reservation(
                "acquired",
                lease_token=str(inserted[1]),
                fencing_token=int(inserted[2]),
            )
        cursor.execute(
            """
            select invocation_sha256, operation_name, operation_version,
                   operation_contract_sha256, state, output_document
              from public.bounded_call_invocation
             where tenant_id = %s and call_id = %s
             for update
            """,
            (tenant_id, run_id),
        )
        current = cursor.fetchone()
        if current is None:
            raise RuntimeError("invocation conflict requires a readable durable row")
        if tuple(str(value) for value in current[:4]) != (
            run_digest,
            operation,
            version,
            contract_digest,
        ):
            raise ContentCollision(
                f"workbench run {run_id} already represents different content; "
                "reuse the original inputs or allocate a new run identity"
            )
        state = str(current[4])
        coordinate = current[5]
        if state == "completed":
            if not isinstance(coordinate, Mapping):
                raise RuntimeError("completed invocation requires a durable coordinate")
            return _Reservation(state, dict(coordinate))
        if state == "recovery_required":
            return _Reservation(state)
        if state == "in_progress":
            raise IdempotencyInProgress(
                f"workbench run {run_id} remains in progress; reconcile its durable state"
            )
        raise RuntimeError(f"invocation state {state!r} is outside the released model")

    def _plan_initial(
        self,
        *,
        run_id: str,
        tenant_id: str,
        specimen_id: str,
        actor_id: str,
        scientist_id: str,
        quality_actor_id: str,
        occurred_at: datetime,
        raw_instrument_json: bytes,
        vendor_payload: Mapping[str, Any],
    ) -> _JourneyPlan:
        repository = InMemorySpecimenRepository()
        lifecycle = LifecycleService(repository)
        aggregate = lifecycle.register(
            _command(
                run_id=run_id,
                tenant_id=tenant_id,
                specimen_id=specimen_id,
                actor_id=actor_id,
                suffix="register",
                action="register",
                expected_version=0,
                occurred_at=occurred_at,
                payload={"specimen_type": "synthetic_plasma"},
            )
        )
        aggregate = lifecycle.transition(
            _command(
                run_id=run_id,
                tenant_id=tenant_id,
                specimen_id=specimen_id,
                actor_id=actor_id,
                suffix="accession",
                action="accession",
                expected_version=aggregate.version,
                occurred_at=occurred_at,
            )
        )
        aggregate = lifecycle.transition(
            _command(
                run_id=run_id,
                tenant_id=tenant_id,
                specimen_id=specimen_id,
                actor_id=actor_id,
                suffix="start-processing",
                action="start_processing",
                expected_version=aggregate.version,
                occurred_at=occurred_at,
                payload={"assay_id": "SYN-ASSAY-01"},
            )
        )
        ingress = _ingest(
            run_id=run_id,
            tenant_id=tenant_id,
            specimen_id=specimen_id,
            occurred_at=occurred_at,
            raw_instrument_json=raw_instrument_json,
        )
        projection: ProjectionOutcome | None = None
        if ingress.normalized_observation is not None:
            projection = _project_vendor(
                run_id=run_id,
                tenant_id=tenant_id,
                specimen_id=specimen_id,
                instrument_digest=str(ingress.normalized_digest),
                vendor_payload=vendor_payload,
            )
            aggregate = _review_and_release(
                lifecycle,
                aggregate=aggregate,
                run_id=run_id,
                actor_id=scientist_id,
                quality_actor_id=quality_actor_id,
                occurred_at=occurred_at,
            )
        return _JourneyPlan(
            aggregate=aggregate,
            new_events=aggregate.events,
            ingress=ingress,
            message_id=f"{run_id}:instrument",
            instrument_id="SYN-INSTRUMENT-01",
            captured_at=occurred_at,
            projection=projection,
            receipt_id=_receipt_id(tenant_id, run_id),
        )

    def _assert_recovery_source(
        self,
        cursor: Cursor,
        *,
        tenant_id: str,
        run_id: str,
        specimen_id: str,
    ) -> None:
        initial_operation = _operation_contract("initial")
        cursor.execute(
            """
            select invocation_sha256, state, operation_name, operation_version,
                   operation_contract_sha256, recovery_reason, output_document,
                   result_sha256, completed_at_utc
              from public.bounded_call_invocation
             where tenant_id = %s and call_id = %s
             for update
            """,
            (tenant_id, run_id),
        )
        original = cursor.fetchone()
        if original is None or str(original[1]) != "recovery_required":
            raise DomainError(f"run {run_id} requires a durable instrument review")
        if tuple(str(value) for value in original[2:5]) != initial_operation:
            raise DomainError(f"run {run_id} is outside the Golden Specimen recovery source")
        recovery_reason = str(original[5]) if original[5] is not None else ""
        if not recovery_reason:
            raise RuntimeError("recovery-required invocation requires its reason")
        if any(value is not None for value in original[6:9]):
            raise RuntimeError("recovery-required invocation requires an uncompleted source state")

        receipt_id = _receipt_id(tenant_id, run_id)
        cursor.execute(
            """
            select receipt_id, caller_id, actor_id, operation_name,
                   operation_version, operation_contract_sha256, effect_class,
                   resource_ids, payload_sha256, invocation_sha256, decision,
                   reason_code, grant_id, budget_window_id, result_sha256
              from public.bounded_call_receipt
             where tenant_id = %s and call_id = %s and receipt_id = %s
            """,
            (tenant_id, run_id, receipt_id),
        )
        receipt = cursor.fetchone()
        if receipt is None:
            raise RuntimeError("instrument recovery requires its exact failed receipt")
        resource_ids = receipt[7]
        expected_resources = [f"specimen:{specimen_id}"]
        expected_invocation = canonical_digest(
            {
                "caller_id": str(receipt[1]),
                "actor_id": str(receipt[2]),
                "tenant_id": tenant_id,
                "operation_name": str(receipt[3]),
                "operation_version": str(receipt[4]),
                "operation_contract_digest": str(receipt[5]),
                "resource_ids": resource_ids,
                "payload_digest": str(receipt[8]),
            }
        )
        if (
            str(receipt[0]) != receipt_id
            or str(receipt[1]) != self._caller_id
            or str(receipt[2]) not in self._permitted_actor_ids
            or tuple(str(value) for value in receipt[3:6]) != initial_operation
            or str(receipt[6]) != "idempotent_narrow_write"
            or resource_ids != expected_resources
            or str(receipt[9]) != str(original[0])
            or expected_invocation != str(original[0])
            or str(receipt[10]) != "failed"
            or str(receipt[11]) != recovery_reason
            or str(receipt[12]) != self._grant.grant_id
            or str(receipt[13]) != self._budget.window_id
            or receipt[14] is not None
        ):
            raise RuntimeError(
                "instrument recovery requires exact failed invocation and receipt agreement"
            )

        cursor.execute(
            """
            select specimen_id, reason_code
              from public.instrument_inbox
             where tenant_id = %s and message_id = %s
               and disposition = 'quarantined'
            """,
            (tenant_id, f"{run_id}:instrument"),
        )
        source = cursor.fetchone()
        if source is None:
            raise DomainError(f"run {run_id} requires its quarantined instrument receipt")
        if str(source[1]) != recovery_reason:
            raise RuntimeError(
                "instrument recovery requires invocation and quarantine reason agreement"
            )
        if str(source[0]) != specimen_id:
            raise DomainError(
                f"run {run_id} carries instrument review for specimen "
                f"{source[0]}; resume that specimen"
            )

    def _plan_recovery(
        self,
        cursor: Cursor,
        *,
        recovery_of_run_id: str,
        run_id: str,
        tenant_id: str,
        specimen_id: str,
        actor_id: str,
        scientist_id: str,
        quality_actor_id: str,
        occurred_at: datetime,
        raw_instrument_json: bytes,
        vendor_payload: Mapping[str, Any],
    ) -> _JourneyPlan:
        self._assert_recovery_source(
            cursor,
            tenant_id=tenant_id,
            run_id=recovery_of_run_id,
            specimen_id=specimen_id,
        )
        aggregate = self._load_aggregate(cursor, tenant_id, specimen_id)
        if aggregate.state is not SpecimenState.IN_PROCESS:
            raise DomainError(
                f"specimen {specimen_id} is {aggregate.state.value}; "
                "instrument recovery continues from in_process"
            )
        repository = InMemorySpecimenRepository()
        repository.save(aggregate, previous_version=None)
        lifecycle = LifecycleService(repository)
        ingress = _ingest(
            run_id=run_id,
            tenant_id=tenant_id,
            specimen_id=specimen_id,
            occurred_at=occurred_at,
            raw_instrument_json=raw_instrument_json,
        )
        projection: ProjectionOutcome | None = None
        completed = aggregate
        if ingress.normalized_observation is not None:
            projection = _project_vendor(
                run_id=run_id,
                tenant_id=tenant_id,
                specimen_id=specimen_id,
                instrument_digest=str(ingress.normalized_digest),
                vendor_payload=vendor_payload,
            )
            completed = _review_and_release(
                lifecycle,
                aggregate=aggregate,
                run_id=run_id,
                actor_id=scientist_id,
                quality_actor_id=quality_actor_id,
                occurred_at=occurred_at,
            )
        return _JourneyPlan(
            aggregate=completed,
            new_events=completed.events[len(aggregate.events) :],
            ingress=ingress,
            message_id=f"{run_id}:instrument",
            instrument_id="SYN-INSTRUMENT-01",
            captured_at=occurred_at,
            projection=projection,
            receipt_id=_receipt_id(tenant_id, run_id),
            recovery_of_run_id=recovery_of_run_id,
        )

    def _materialize(
        self,
        cursor: Cursor,
        *,
        plan: _JourneyPlan,
        mode: str,
        tenant_id: str,
        run_id: str,
        specimen_id: str,
        actor_id: str,
        scientist_id: str,
        quality_actor_id: str,
        occurred_at: datetime,
        run_digest: str,
        authority_request: CallRequest,
        lease_token: str | None,
        fencing_token: int | None,
    ) -> None:
        if lease_token is None or fencing_token is None:
            raise RuntimeError("invocation materialization requires its lease and fence")
        if mode == "initial":
            self._insert_specimen(cursor, plan.aggregate)
            self._insert_events(cursor, plan.new_events)
            cursor.execute(
                """
                select custody_version
                  from public.record_custody_transfer(%s, %s, %s, 0, %s, %s)
                """,
                (
                    specimen_id,
                    "SYN-LAB-A/RECEIVING",
                    actor_id,
                    f"{run_id}:custody:receiving",
                    occurred_at,
                ),
            )
            if cursor.fetchone() is None:
                raise RuntimeError("custody materialization requires a resulting position")
        elif plan.ingress.normalized_observation is not None:
            previous_version = plan.aggregate.version - len(plan.new_events)
            self._update_specimen(cursor, plan.aggregate, previous_version)
            self._insert_events(cursor, plan.new_events)

        self._insert_instrument(cursor, plan)
        if plan.projection is not None:
            self._insert_vendor_projection(cursor, plan, tenant_id, specimen_id, run_id)
        if plan.recovery_of_run_id and plan.ingress.normalized_observation is not None:
            cursor.execute(
                """
                select disposition
                  from public.record_instrument_review_resolution(
                      %s, %s, 'accepted_replacement', %s, %s, %s, %s
                  )
                """,
                (
                    f"{plan.recovery_of_run_id}:instrument",
                    f"{run_id}:scientific-review",
                    plan.message_id,
                    scientist_id,
                    "replacement evidence passed scientific review",
                    occurred_at,
                ),
            )
            resolution = cursor.fetchone()
            if resolution is None or str(resolution[0]) != "accepted_replacement":
                raise RuntimeError("instrument recovery requires a durable resolution")

        successful = plan.ingress.normalized_observation is not None
        specimen_snapshot: dict[str, Any] | None = None
        outbox_topics: list[str] | None = None
        if successful:
            specimen_snapshot = self._load_specimen(cursor, tenant_id, specimen_id)
            cursor.execute(
                """
                select topic
                  from public.transactional_outbox
                 where tenant_id = %s and aggregate_id = %s
                 order by created_at_utc, message_id
                """,
                (tenant_id, specimen_id),
            )
            outbox_topics = [str(row[0]) for row in cursor.fetchall()]
        coordinate = {
            "coordinate_version": "2.0.0",
            "mode": mode,
            "run_id": run_id,
            "recovery_of_run_id": plan.recovery_of_run_id,
            "specimen_id": specimen_id,
            "actor_id": actor_id,
            "reviewer_id": scientist_id,
            "quality_actor_id": quality_actor_id,
            "instrument_message_id": plan.message_id,
            "raw_sha256": plan.ingress.raw_sha256,
            "normalized_sha256": plan.ingress.normalized_digest,
            "receipt_id": plan.receipt_id,
            "specimen_snapshot": specimen_snapshot,
            "outbox_topics": outbox_topics,
        }
        result_digest = canonical_digest(coordinate) if successful else None
        operation, version, contract_digest = _operation_contract(mode)
        if successful:
            cursor.execute(
                """
                update public.bounded_call_invocation
                   set state = 'completed', output_document = %s::jsonb,
                       result_sha256 = %s,
                       completed_at_utc = transaction_timestamp(),
                       recovery_reason = null
                 where tenant_id = %s and call_id = %s
                   and invocation_sha256 = %s and state = 'in_progress'
                   and lease_token = %s::uuid and fencing_token = %s
                   and lease_expires_at_utc > clock_timestamp()
                returning call_id
                """,
                (
                    _json(coordinate),
                    result_digest,
                    tenant_id,
                    run_id,
                    run_digest,
                    lease_token,
                    fencing_token,
                ),
            )
        else:
            cursor.execute(
                """
                update public.bounded_call_invocation
                   set state = 'recovery_required', recovery_reason = %s
                 where tenant_id = %s and call_id = %s
                   and invocation_sha256 = %s and state = 'in_progress'
                   and lease_token = %s::uuid and fencing_token = %s
                   and lease_expires_at_utc > clock_timestamp()
                returning call_id
                """,
                (
                    plan.ingress.reason_code,
                    tenant_id,
                    run_id,
                    run_digest,
                    lease_token,
                    fencing_token,
                ),
            )
        if cursor.fetchone() is None:
            raise RuntimeError("invocation completion lost its acquired state")
        cursor.execute(
            """
            insert into public.bounded_call_receipt (
                receipt_id, call_id, caller_id, actor_id, tenant_id,
                operation_name, operation_version, operation_contract_sha256,
                effect_class, resource_ids, payload_sha256, invocation_sha256,
                decision, reason_code, grant_id, budget_window_id, approval_id,
                result_sha256, requested_at_utc, recorded_at_utc
            ) values (
                %s, %s, %s, %s, %s, %s, %s, %s,
                'idempotent_narrow_write', %s::jsonb, %s, %s,
                %s, %s, %s, %s, null, %s, %s, transaction_timestamp()
            )
            """,
            (
                plan.receipt_id,
                run_id,
                self._caller_id,
                actor_id,
                tenant_id,
                operation,
                version,
                contract_digest,
                _json([f"specimen:{specimen_id}"]),
                authority_request.payload_digest,
                run_digest,
                "succeeded" if successful else "failed",
                "operation_completed" if successful else str(plan.ingress.reason_code),
                self._grant.grant_id,
                self._budget.window_id,
                result_digest,
                authority_request.requested_at,
            ),
        )
        self._failure_probe("after_materialization")

    def _insert_specimen(self, cursor: Cursor, aggregate: SpecimenAggregate) -> None:
        document = _aggregate_document(aggregate)
        cursor.execute(
            """
            insert into public.specimen (
                tenant_id, specimen_id, lifecycle_state, aggregate_version,
                canonical_document, canonical_sha256, updated_at_utc
            ) values (%s, %s, %s, %s, %s::jsonb, %s, %s)
            """,
            (
                aggregate.tenant_id,
                aggregate.specimen_id,
                aggregate.state.value,
                aggregate.version,
                _json(document),
                canonical_digest(document),
                aggregate.events[-1].occurred_at,
            ),
        )

    def _update_specimen(
        self,
        cursor: Cursor,
        aggregate: SpecimenAggregate,
        previous_version: int,
    ) -> None:
        document = _aggregate_document(aggregate)
        cursor.execute(
            """
            update public.specimen
               set lifecycle_state = %s, aggregate_version = %s,
                   canonical_document = %s::jsonb, canonical_sha256 = %s,
                   updated_at_utc = %s
             where tenant_id = %s and specimen_id = %s and aggregate_version = %s
            returning specimen_id
            """,
            (
                aggregate.state.value,
                aggregate.version,
                _json(document),
                canonical_digest(document),
                aggregate.events[-1].occurred_at,
                aggregate.tenant_id,
                aggregate.specimen_id,
                previous_version,
            ),
        )
        if cursor.fetchone() is None:
            raise DomainError(
                f"specimen {aggregate.specimen_id} changed before recovery; "
                "reload its durable revision"
            )

    def _insert_events(
        self,
        cursor: Cursor,
        events: tuple[DomainEvent, ...],
    ) -> None:
        for event in events:
            cursor.execute(
                """
                insert into public.specimen_event (
                    tenant_id, specimen_id, aggregate_version, event_id,
                    command_id, command_sha256, event_type, actor_id,
                    reason_code, payload, occurred_at_utc
                ) values (%s, %s, %s, %s::uuid, %s, %s, %s, %s, %s, %s::jsonb, %s)
                """,
                (
                    event.tenant_id,
                    event.specimen_id,
                    event.aggregate_version,
                    event.event_id,
                    event.command_id,
                    event.command_digest,
                    event.event_type,
                    event.actor_id,
                    event.reason_code,
                    _json(dict(event.payload)),
                    event.occurred_at,
                ),
            )
            outcome = {
                "specimen_id": event.specimen_id,
                "aggregate_version": event.aggregate_version,
                "event_id": event.event_id,
            }
            cursor.execute(
                """
                insert into public.idempotency_ledger (
                    tenant_id, idempotency_key, content_sha256, status,
                    outcome_document, committed_at_utc
                ) values (
                    %s, %s, %s, 'committed', %s::jsonb,
                    transaction_timestamp()
                )
                """,
                (
                    event.tenant_id,
                    event.command_id,
                    event.command_digest,
                    _json(outcome),
                ),
            )

    def _insert_instrument(self, cursor: Cursor, plan: _JourneyPlan) -> None:
        cursor.execute(
            """
            insert into public.instrument_inbox (
                tenant_id, message_id, instrument_id, specimen_id,
                raw_object_key, raw_sha256, captured_at_utc, disposition,
                reason_code, recovery_instruction
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                plan.aggregate.tenant_id,
                plan.message_id,
                plan.instrument_id,
                plan.aggregate.specimen_id,
                f"synthetic/workbench/{plan.ingress.raw_sha256[:24]}.json",
                plan.ingress.raw_sha256,
                plan.captured_at,
                plan.ingress.disposition.value,
                plan.ingress.reason_code,
                plan.ingress.recovery,
            ),
        )
        observation = plan.ingress.normalized_observation
        if observation is None:
            return
        measurement = _measurement_from_ingress(plan.ingress)
        cursor.execute(
            """
            insert into public.instrument_measurement (
                tenant_id, measurement_id, message_id, specimen_id,
                analyte_code, quantity, source_precision, source_scale,
                unit_code, unit_system, captured_at_utc, raw_sha256,
                normalized_sha256, source_disposition
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                plan.aggregate.tenant_id,
                f"{plan.message_id}:measurement",
                plan.message_id,
                plan.aggregate.specimen_id,
                measurement.analyte,
                measurement.decimal,
                measurement.precision,
                measurement.scale,
                measurement.unit_code,
                measurement.unit_system,
                plan.captured_at,
                plan.ingress.raw_sha256,
                plan.ingress.normalized_digest,
                plan.ingress.disposition.value,
            ),
        )

    def _insert_vendor_projection(
        self,
        cursor: Cursor,
        plan: _JourneyPlan,
        tenant_id: str,
        specimen_id: str,
        run_id: str,
    ) -> None:
        assert plan.projection is not None
        cursor.execute(
            """
            insert into public.vendor_projection (
                tenant_id, vendor_name, external_identity, external_revision,
                canonical_sha256, request_id, trace_id,
                reconciliation_state, observed_at_utc
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                tenant_id,
                plan.projection.vendor_name,
                specimen_id,
                plan.projection.revision,
                plan.projection.canonical_digest,
                f"{run_id}:vendor-projection",
                plan.projection.trace_id,
                "readback_confirmed" if plan.projection.reconciled else "confirmed",
                plan.captured_at,
            ),
        )

    def _load_quarantine(
        self,
        cursor: Cursor,
        tenant_id: str,
        run_id: str,
    ) -> IngressResult:
        cursor.execute(
            """
            select raw_sha256, reason_code, recovery_instruction
              from public.instrument_inbox
             where tenant_id = %s and message_id = %s and disposition = 'quarantined'
            """,
            (tenant_id, f"{run_id}:instrument"),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("recovery-required run requires its quarantine receipt")
        return IngressResult(
            disposition=IngressDisposition.QUARANTINED,
            raw_sha256=str(row[0]),
            normalized_digest=None,
            normalized_document_json=None,
            normalized_observation=None,
            reason_code=str(row[1]),
            recovery=str(row[2]),
        )

    def _load_aggregate(
        self,
        cursor: Cursor,
        tenant_id: str,
        specimen_id: str,
    ) -> SpecimenAggregate:
        specimen = self._load_specimen(cursor, tenant_id, specimen_id)
        events = tuple(
            DomainEvent(
                event_id=str(event["event_id"]),
                tenant_id=tenant_id,
                specimen_id=specimen_id,
                aggregate_version=int(event["aggregate_version"]),
                event_type=str(event["event_type"]),
                actor_id=str(event["actor_id"]),
                command_id=str(event["command_id"]),
                command_digest=str(event["command_digest"]),
                occurred_at=require_aware_utc(datetime.fromisoformat(str(event["occurred_at"]))),
                payload=dict(event["payload"]),
                reason_code=(
                    str(event["reason_code"]) if event["reason_code"] is not None else None
                ),
            )
            for event in specimen["events"]
        )
        version = int(specimen["version"])
        if tuple(event.aggregate_version for event in events) != tuple(range(1, version + 1)):
            raise RuntimeError(
                "durable specimen recovery requires complete event-version continuity"
            )
        return SpecimenAggregate(
            tenant_id=tenant_id,
            specimen_id=specimen_id,
            state=SpecimenState(str(specimen["state"])),
            version=version,
            attributes=dict(specimen["attributes"]),
            events=events,
        )

    def _load_specimen(
        self,
        cursor: Cursor,
        tenant_id: str,
        specimen_id: str,
    ) -> dict[str, Any]:
        cursor.execute(
            """
            select snapshot.lifecycle_state, snapshot.aggregate_version,
                   snapshot.canonical_document, snapshot.location_code,
                   snapshot.custodian_id, snapshot.custody_version,
                   snapshot.latest_measurement_id,
                   snapshot.latest_instrument_message_id,
                   snapshot.latest_instrument_id, snapshot.latest_analyte_code,
                   snapshot.latest_observed_value_text, snapshot.latest_unit_code,
                   snapshot.latest_observation_sha256, snapshot.latest_raw_sha256,
                   snapshot.vendor_name, snapshot.external_revision,
                   snapshot.reconciliation_state,
                   snapshot.open_instrument_review_count,
                   snapshot.quarantine_history_count,
                   snapshot.pending_outbox_count,
                   source.canonical_sha256
              from public.specimen_workbench_snapshot as snapshot
              join public.specimen as source
                on source.tenant_id = snapshot.tenant_id
               and source.specimen_id = snapshot.specimen_id
             where snapshot.tenant_id = %s and snapshot.specimen_id = %s
            """,
            (tenant_id, specimen_id),
        )
        snapshot = cursor.fetchone()
        if snapshot is None:
            raise SpecimenAbsent(
                f"specimen {specimen_id} is absent from tenant {tenant_id}; "
                "register it or select an existing specimen"
            )
        canonical = snapshot[2]
        if not isinstance(canonical, Mapping):
            raise RuntimeError("workbench snapshot requires a canonical specimen document")
        attributes = canonical.get("attributes")
        if not isinstance(attributes, Mapping):
            raise RuntimeError("canonical specimen attributes require one object")
        expected_canonical = {
            "tenant_id": tenant_id,
            "specimen_id": specimen_id,
            "state": str(snapshot[0]),
            "version": int(snapshot[1]),
            "attributes": dict(attributes),
        }
        if dict(canonical) != expected_canonical:
            raise RuntimeError("canonical specimen document requires exact row-state agreement")
        if canonical_digest(canonical) != str(snapshot[20]):
            raise RuntimeError("canonical specimen document requires its stored digest")
        cursor.execute(
            """
            select event_id::text, event_type, aggregate_version, actor_id,
                   command_id, command_sha256, occurred_at_utc, payload, reason_code
              from public.specimen_event
             where tenant_id = %s and specimen_id = %s
             order by aggregate_version
            """,
            (tenant_id, specimen_id),
        )
        event_rows = cursor.fetchall()
        events = [
            {
                "event_id": str(row[0]),
                "event_type": str(row[1]),
                "aggregate_version": int(row[2]),
                "actor_id": str(row[3]),
                "command_id": str(row[4]),
                "command_digest": str(row[5]),
                "occurred_at": _timestamp(row[6]),
                "payload": dict(row[7]),
                "reason_code": str(row[8]) if row[8] is not None else None,
            }
            for row in event_rows
        ]
        cursor.execute(
            """
            select inbox.message_id, inbox.instrument_id, inbox.disposition,
                   inbox.raw_sha256, inbox.reason_code, inbox.recovery_instruction,
                   inbox.captured_at_utc, observation.analyte_code,
                   observation.observed_value_text, observation.unit_code,
                   observation.normalized_sha256, observation.source_precision,
                   observation.source_scale, observation.unit_system
              from public.instrument_inbox as inbox
              left join public.normalized_observation as observation
                on observation.tenant_id = inbox.tenant_id
               and observation.message_id = inbox.message_id
             where inbox.tenant_id = %s and inbox.specimen_id = %s
             order by inbox.recorded_at_utc, inbox.message_id
            """,
            (tenant_id, specimen_id),
        )
        receipts = [
            _instrument_receipt_document(tenant_id, specimen_id, row) for row in cursor.fetchall()
        ]
        cursor.execute(
            """
            select vendor_name, external_identity, external_revision,
                   canonical_sha256, reconciliation_state, trace_id
              from public.vendor_projection
             where tenant_id = %s and external_identity = %s
             order by observed_at_utc desc, vendor_name
             limit 1
            """,
            (tenant_id, specimen_id),
        )
        vendor = cursor.fetchone()
        return {
            "tenant_id": tenant_id,
            "specimen_id": specimen_id,
            "state": str(snapshot[0]),
            "version": int(snapshot[1]),
            "attributes": dict(attributes),
            "events": events,
            "custody": (
                {
                    "location": str(snapshot[3]),
                    "version": int(snapshot[5]),
                    "custodian_id": str(snapshot[4]),
                }
                if snapshot[3] is not None
                else None
            ),
            "instrument_receipts": receipts,
            "projection": (
                {
                    "vendor_name": str(vendor[0]),
                    "external_identity": str(vendor[1]),
                    "revision": int(vendor[2]),
                    "canonical_digest": str(vendor[3]),
                    "reconciled": str(vendor[4]) == "readback_confirmed",
                    "trace_id": str(vendor[5]),
                }
                if vendor is not None
                else None
            ),
        }

    def _load_run(self, tenant_id: str, run_id: str) -> dict[str, Any]:
        with self._bound_transaction(tenant_id) as cursor:
            cursor.execute(
                """
                select invocation.output_document, invocation.invocation_sha256,
                       invocation.operation_name, invocation.operation_version,
                       invocation.operation_contract_sha256,
                       invocation.result_sha256
                  from public.bounded_call_invocation as invocation
                 where invocation.tenant_id = %s and invocation.call_id = %s
                   and invocation.state = 'completed'
                """,
                (tenant_id, run_id),
            )
            run_row = cursor.fetchone()
            if run_row is None or not isinstance(run_row[0], Mapping):
                raise ObservationAbsent(
                    f"run {run_id} has no completed durable result for tenant {tenant_id}"
                )
            coordinate = dict(run_row[0])
            required_coordinate_fields = {
                "coordinate_version",
                "mode",
                "run_id",
                "recovery_of_run_id",
                "specimen_id",
                "actor_id",
                "reviewer_id",
                "quality_actor_id",
                "instrument_message_id",
                "raw_sha256",
                "normalized_sha256",
                "receipt_id",
                "specimen_snapshot",
                "outbox_topics",
            }
            if set(coordinate) != required_coordinate_fields:
                raise RuntimeError("durable run coordinate requires its released fields")
            if coordinate["coordinate_version"] != "2.0.0":
                raise RuntimeError("durable run coordinate requires released version 2.0.0")
            if coordinate["run_id"] != run_id:
                raise RuntimeError("durable run coordinate requires the requested run identity")
            if canonical_digest(coordinate) != str(run_row[5]):
                raise RuntimeError("durable run coordinate requires its stored result digest")
            operation = _operation_contract(str(coordinate["mode"]))
            if tuple(str(value) for value in run_row[2:5]) != operation:
                raise RuntimeError("durable run requires its released operation coordinate")
            receipt_id = str(coordinate["receipt_id"])
            if receipt_id != _receipt_id(tenant_id, run_id):
                raise RuntimeError("durable run requires its deterministic receipt identity")
            cursor.execute(
                """
                select receipt_id, caller_id, actor_id, operation_name,
                       operation_version, operation_contract_sha256,
                       effect_class, resource_ids, payload_sha256,
                       invocation_sha256, decision, reason_code, grant_id,
                       budget_window_id, result_sha256
                  from public.bounded_call_receipt
                 where tenant_id = %s and call_id = %s and receipt_id = %s
                """,
                (tenant_id, run_id, receipt_id),
            )
            receipt_row = cursor.fetchone()
            if receipt_row is None:
                raise RuntimeError("completed durable run requires its exact receipt")
            resource_ids = receipt_row[7]
            expected_resources = [f"specimen:{coordinate['specimen_id']}"]
            expected_invocation = canonical_digest(
                {
                    "caller_id": str(receipt_row[1]),
                    "actor_id": str(receipt_row[2]),
                    "tenant_id": tenant_id,
                    "operation_name": str(receipt_row[3]),
                    "operation_version": str(receipt_row[4]),
                    "operation_contract_digest": str(receipt_row[5]),
                    "resource_ids": resource_ids,
                    "payload_digest": str(receipt_row[8]),
                }
            )
            if (
                str(receipt_row[0]) != receipt_id
                or str(receipt_row[1]) != self._caller_id
                or str(receipt_row[2]) != str(coordinate["actor_id"])
                or tuple(str(value) for value in receipt_row[3:6]) != operation
                or str(receipt_row[6]) != "idempotent_narrow_write"
                or resource_ids != expected_resources
                or expected_invocation != str(run_row[1])
                or str(receipt_row[9]) != str(run_row[1])
                or str(receipt_row[10]) != "succeeded"
                or str(receipt_row[11]) != "operation_completed"
                or str(receipt_row[12]) != self._grant.grant_id
                or str(receipt_row[13]) != self._budget.window_id
                or str(receipt_row[14]) != str(run_row[5])
            ):
                raise RuntimeError(
                    "completed durable run requires exact invocation and receipt agreement"
                )
            specimen_id = str(coordinate.get("specimen_id", ""))
            if not specimen_id:
                raise RuntimeError("durable run coordinate requires a specimen identity")
            snapshot_value = coordinate["specimen_snapshot"]
            if not isinstance(snapshot_value, Mapping):
                raise RuntimeError("durable run requires its immutable specimen snapshot")
            specimen = dict(snapshot_value)
            required_specimen_fields = {
                "tenant_id",
                "specimen_id",
                "state",
                "version",
                "attributes",
                "events",
                "custody",
                "instrument_receipts",
                "projection",
            }
            if set(specimen) != required_specimen_fields:
                raise RuntimeError("durable run specimen snapshot requires its released fields")
            if (
                specimen["tenant_id"] != tenant_id
                or specimen["specimen_id"] != specimen_id
                or specimen["state"] != "released"
                or type(specimen["version"]) is not int
                or not isinstance(specimen["events"], list)
                or not isinstance(specimen["instrument_receipts"], list)
            ):
                raise RuntimeError(
                    "durable run specimen snapshot requires its released identity and state"
                )
            outbox_value = coordinate["outbox_topics"]
            if not isinstance(outbox_value, list) or any(
                not isinstance(value, str) or not value for value in outbox_value
            ):
                raise RuntimeError("durable run requires its immutable outbox topics")
            outbox_topics = list(outbox_value)
        message_id = str(coordinate.get("instrument_message_id", ""))
        instrument_receipt = next(
            (item for item in specimen["instrument_receipts"] if item["message_id"] == message_id),
            None,
        )
        if instrument_receipt is None:
            raise RuntimeError("durable run requires its instrument receipt")
        observation_value = instrument_receipt.get("normalized_observation")
        if not isinstance(observation_value, Mapping):
            raise RuntimeError("completed durable run requires a normalized observation")
        review_event = _run_event(specimen["events"], run_id, "specimen.submit_review")
        release_event = _run_event(specimen["events"], run_id, "specimen.release")
        if coordinate["mode"] == "initial":
            register_event = _run_event(specimen["events"], run_id, "specimen.registered")
            if register_event["actor_id"] != coordinate["actor_id"]:
                raise RuntimeError("initial durable run requires its accountable actor event")
        if (
            review_event["actor_id"] != coordinate["reviewer_id"]
            or release_event["actor_id"] != coordinate["quality_actor_id"]
        ):
            raise RuntimeError("durable review and release require their accountable actors")
        if (
            instrument_receipt["raw_sha256"] != coordinate["raw_sha256"]
            or instrument_receipt["normalized_digest"] != coordinate["normalized_sha256"]
        ):
            raise RuntimeError("durable run coordinate requires its exact instrument evidence")
        review_payload = review_event["payload"]
        release_payload = release_event["payload"]
        if not isinstance(review_payload, Mapping) or not isinstance(release_payload, Mapping):
            raise RuntimeError("review and release events require object payloads")
        for field in ("review_id", "decision", "quality_flag"):
            if not review_payload.get(field):
                raise RuntimeError(f"durable review event requires {field}")
        if not release_payload.get("approval_receipt_id"):
            raise RuntimeError("durable release event requires approval_receipt_id")
        custody = specimen.get("custody")
        if not isinstance(custody, Mapping):
            raise RuntimeError("completed durable run requires current custody")
        expected_projection = {
            "projection_id": "urn:driftframe:lims-eln:golden-specimen-result",
            "projection_version": "1.0.0",
            "comparison_compatibility": "exact-version",
            "tenant_id": tenant_id,
            "specimen_id": specimen_id,
            "lifecycle": {
                "state": specimen["state"],
                "aggregate_version": specimen["version"],
            },
            "custody": {"current_location": custody["location"]},
            "measurement": {
                "analyte": observation_value["analyte"],
                "value": float(Decimal(str(observation_value["value"]))),
                "unit": observation_value["unit"],
                "quality_flag": review_payload["quality_flag"],
            },
            "review_resolution": {
                "review_id": review_payload["review_id"],
                "decision": review_payload["decision"],
                "resolved_at": _contract_timestamp(str(review_event["occurred_at"])),
            },
            "release": {
                "approval_receipt_id": release_payload["approval_receipt_id"],
                "released_at": _contract_timestamp(str(release_event["occurred_at"])),
            },
        }
        vendor = specimen.get("projection")
        try:
            observation = build_observation(
                run_id=run_id,
                actor_id=str(coordinate["actor_id"]),
                reviewer_id=str(coordinate["reviewer_id"]),
                raw_sha256=str(coordinate["raw_sha256"]),
                result=specimen,
                state_adapter="postgresql",
                governed_locator=f"postgresql://workbench/{tenant_id}/{run_id}",
                configuration_detail={"migration_head": "005"},
                producer_detail={
                    "outbox_topics": outbox_topics,
                    "durable_run_coordinate": {
                        "mode": coordinate["mode"],
                        "receipt_id": coordinate["receipt_id"],
                    },
                },
            )
        except SharedContractUnavailable:
            observation = None
        if observation is not None and observation["result"]["projection"] != expected_projection:
            raise RuntimeError(
                "typed Golden Specimen projection requires exact stored-state agreement"
            )
        return {
            "run_id": run_id,
            "outcome": {
                "lifecycle_state": specimen["state"],
                "lifecycle_version": specimen["version"],
                "instrument_digest": instrument_receipt["normalized_digest"],
                "custody_location": custody["location"],
                "call_receipt_id": coordinate["receipt_id"],
                "call_decision": str(receipt_row[10]),
                "projection": vendor,
            },
            "specimen": specimen,
            "observation": observation,
        }


def _operation_contract(mode: str) -> tuple[str, str, str]:
    return golden_specimen_operation_contract(mode)


def _command(
    *,
    run_id: str,
    tenant_id: str,
    specimen_id: str,
    actor_id: str,
    suffix: str,
    action: str,
    expected_version: int,
    occurred_at: datetime,
    payload: Mapping[str, Any] | None = None,
    reason_code: str | None = None,
) -> Command:
    return Command(
        command_id=f"{run_id}:{suffix}",
        tenant_id=tenant_id,
        specimen_id=specimen_id,
        actor_id=actor_id,
        action=action,
        expected_version=expected_version,
        occurred_at=occurred_at,
        payload=dict(payload or {}),
        reason_code=reason_code,
    )


def _review_and_release(
    lifecycle: LifecycleService,
    *,
    aggregate: SpecimenAggregate,
    run_id: str,
    actor_id: str,
    quality_actor_id: str,
    occurred_at: datetime,
) -> SpecimenAggregate:
    aggregate = lifecycle.transition(
        _command(
            run_id=run_id,
            tenant_id=aggregate.tenant_id,
            specimen_id=aggregate.specimen_id,
            actor_id=actor_id,
            suffix="submit-review",
            action="submit_review",
            expected_version=aggregate.version,
            occurred_at=occurred_at,
            payload={
                "review_id": f"{run_id}:scientific-review",
                "decision": "accepted",
                "quality_flag": "pass",
            },
        )
    )
    return lifecycle.transition(
        _command(
            run_id=run_id,
            tenant_id=aggregate.tenant_id,
            specimen_id=aggregate.specimen_id,
            actor_id=quality_actor_id,
            suffix="release",
            action="release",
            expected_version=aggregate.version,
            occurred_at=occurred_at,
            payload={"approval_receipt_id": f"{run_id}:quality-approval"},
            reason_code="scientific_review_complete",
        )
    )


def _ingest(
    *,
    run_id: str,
    tenant_id: str,
    specimen_id: str,
    occurred_at: datetime,
    raw_instrument_json: bytes,
) -> IngressResult:
    return InstrumentIngress().ingest(
        InstrumentEnvelope(
            tenant_id=tenant_id,
            message_id=f"{run_id}:instrument",
            instrument_id="SYN-INSTRUMENT-01",
            specimen_id=specimen_id,
            captured_at=occurred_at,
            media_type="application/json",
            raw_bytes=raw_instrument_json,
        )
    )


def _project_vendor(
    *,
    run_id: str,
    tenant_id: str,
    specimen_id: str,
    instrument_digest: str,
    vendor_payload: Mapping[str, Any],
) -> ProjectionOutcome:
    gateway = InMemoryVendorGateway("synthetic-benchling")
    gateway.fault_mode = FaultMode.TIMEOUT_AFTER_COMMIT
    return VendorProjectionService(gateway).project(
        tenant_id=tenant_id,
        request_id=f"{run_id}:vendor-projection",
        external_identity=specimen_id,
        expected_revision=0,
        payload={**dict(vendor_payload), "instrument_digest": instrument_digest},
    )


def _receipt_id(tenant_id: str, run_id: str) -> str:
    coordinate_digest = canonical_digest({"tenant_id": tenant_id, "run_id": run_id})
    return str(uuid5(_RECEIPT_NAMESPACE, coordinate_digest))


def _aggregate_document(aggregate: SpecimenAggregate) -> dict[str, Any]:
    return {
        "tenant_id": aggregate.tenant_id,
        "specimen_id": aggregate.specimen_id,
        "state": aggregate.state.value,
        "version": aggregate.version,
        "attributes": dict(aggregate.attributes),
    }


def _json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _measurement_from_ingress(result: IngressResult) -> _NormalizedMeasurementFact:
    observation = result.normalized_observation
    document_json = result.normalized_document_json
    normalized_digest = result.normalized_digest
    if observation is None or document_json is None or normalized_digest is None:
        raise RuntimeError("accepted instrument ingress requires its normalized evidence")
    try:
        document = json.loads(document_json)
    except (json.JSONDecodeError, TypeError) as error:
        raise RuntimeError("normalized instrument evidence requires canonical JSON") from error
    if not isinstance(document, Mapping):
        raise RuntimeError("normalized instrument evidence requires one object")
    quantity = document.get("quantity")
    if not isinstance(quantity, Mapping):
        raise RuntimeError("normalized instrument evidence requires a quantity object")
    decimal_value = quantity.get("decimal")
    precision_value = quantity.get("precision")
    scale_value = quantity.get("scale")
    unit_code = quantity.get("unit_code")
    unit_system = quantity.get("unit_system")
    if not isinstance(decimal_value, str):
        raise RuntimeError("normalized quantity requires its decimal text")
    if type(precision_value) is not int or not 1 <= precision_value <= 38:
        raise RuntimeError("normalized quantity requires released source precision")
    if type(scale_value) is not int or not 0 <= scale_value <= 18:
        raise RuntimeError("normalized quantity requires released source scale")
    if not isinstance(unit_code, str) or not isinstance(unit_system, str):
        raise RuntimeError("normalized quantity requires released unit coordinates")
    try:
        decimal = Decimal(decimal_value)
    except (InvalidOperation, ValueError) as error:
        raise RuntimeError("normalized quantity requires finite decimal text") from error
    if not decimal.is_finite() or max(-decimal.as_tuple().exponent, 0) != scale_value:
        raise RuntimeError("normalized quantity scale requires exact decimal agreement")
    expected_fields = {
        "tenant_id": observation.tenant_id,
        "specimen_id": observation.specimen_id,
        "instrument_id": observation.instrument_id,
        "captured_at": require_aware_utc(observation.captured_at).isoformat(),
        "analyte": observation.analyte,
        "raw_sha256": observation.raw_sha256,
    }
    for field, expected in expected_fields.items():
        if document.get(field) != expected:
            raise RuntimeError(f"normalized instrument evidence requires exact {field} agreement")
    if decimal_value != observation.value or unit_code != observation.unit:
        raise RuntimeError("normalized instrument projection requires quantity agreement")
    if observation.raw_sha256 != result.raw_sha256:
        raise RuntimeError("normalized instrument evidence requires raw digest agreement")
    if canonical_digest(document) != normalized_digest:
        raise RuntimeError("normalized instrument evidence requires its canonical digest")
    return _NormalizedMeasurementFact(
        analyte=observation.analyte,
        decimal=decimal_value,
        precision=precision_value,
        scale=scale_value,
        unit_code=unit_code,
        unit_system=unit_system,
    )


def _timestamp(value: datetime) -> str:
    return require_aware_utc(value).isoformat()


def _contract_timestamp(value: str) -> str:
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise RuntimeError("durable event timestamp requires an explicit UTC offset")
    return instant.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _instrument_receipt_document(
    tenant_id: str,
    specimen_id: str,
    row: Sequence[Any],
) -> dict[str, Any]:
    normalized: dict[str, Any] | None = None
    if row[7] is not None:
        if any(row[index] is None for index in range(8, 14)):
            raise RuntimeError(
                "durable normalized observation requires complete scientific coordinates"
            )
        normalized_document = {
            "tenant_id": tenant_id,
            "specimen_id": specimen_id,
            "instrument_id": str(row[1]),
            "captured_at": _timestamp(row[6]),
            "analyte": str(row[7]),
            "quantity": {
                "decimal": str(row[8]),
                "precision": int(row[11]),
                "scale": int(row[12]),
                "unit_code": str(row[9]),
                "unit_system": str(row[13]),
            },
            "raw_sha256": str(row[3]),
        }
        if canonical_digest(normalized_document) != str(row[10]):
            raise RuntimeError(
                "durable normalized observation requires its stored canonical digest"
            )
        normalized = {
            "tenant_id": tenant_id,
            "specimen_id": specimen_id,
            "instrument_id": str(row[1]),
            "captured_at": _timestamp(row[6]),
            "analyte": str(row[7]),
            "value": str(row[8]),
            "unit": str(row[9]),
            "raw_sha256": str(row[3]),
        }
    elif any(row[index] is not None for index in range(8, 14)):
        raise RuntimeError(
            "instrument receipt without a measurement requires absent normalized fields"
        )
    return {
        "tenant_id": tenant_id,
        "specimen_id": specimen_id,
        "message_id": str(row[0]),
        "instrument_id": str(row[1]),
        "disposition": str(row[2]),
        "raw_sha256": str(row[3]),
        "normalized_observation": normalized,
        "normalized_digest": str(row[10]) if row[10] is not None else None,
        "reason_code": str(row[4]) if row[4] is not None else None,
        "recovery": str(row[5]),
        "captured_at": _timestamp(row[6]),
    }


def _run_event(
    events: Sequence[Mapping[str, Any]],
    run_id: str,
    event_type: str,
) -> Mapping[str, Any]:
    matches = [
        event
        for event in events
        if event.get("event_type") == event_type
        and str(event.get("command_id", "")).startswith(f"{run_id}:")
    ]
    if len(matches) != 1:
        raise RuntimeError(f"durable run requires one {event_type} event")
    return matches[0]
