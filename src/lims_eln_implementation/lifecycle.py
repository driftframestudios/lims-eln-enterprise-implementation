"""Specimen lifecycle application service."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID, uuid5

from .idempotency import (
    IdempotencyInProgress,
    IdempotencyLedger,
    ReservationState,
)
from .model import (
    Command,
    DomainEvent,
    SpecimenAggregate,
    SpecimenState,
    TransitionRejected,
    require_aware_utc,
)
from .store import AtomicExecutor, InMemoryAtomicExecutor, SpecimenRepository


_EVENT_NAMESPACE = UUID("85f45b64-16d2-4e80-a90b-37a181443dd2")

_TRANSITIONS: dict[tuple[SpecimenState, str], SpecimenState] = {
    (SpecimenState.REGISTERED, "accession"): SpecimenState.ACCESSIONED,
    (SpecimenState.ACCESSIONED, "start_processing"): SpecimenState.IN_PROCESS,
    (SpecimenState.IN_PROCESS, "submit_review"): SpecimenState.UNDER_REVIEW,
    (SpecimenState.UNDER_REVIEW, "release"): SpecimenState.RELEASED,
    (SpecimenState.RELEASED, "correct"): SpecimenState.CORRECTED,
    (SpecimenState.CORRECTED, "submit_review"): SpecimenState.UNDER_REVIEW,
}


class LifecycleService:
    def __init__(
        self,
        repository: SpecimenRepository,
        idempotency: IdempotencyLedger[SpecimenAggregate] | None = None,
        atomic: AtomicExecutor | None = None,
    ) -> None:
        self._repository = repository
        self._idempotency = idempotency or IdempotencyLedger()
        if atomic is None:
            if not all(
                hasattr(participant, "transaction_snapshot")
                and hasattr(participant, "transaction_restore")
                for participant in (repository, self._idempotency)
            ):
                raise ValueError(
                    "durable lifecycle adapters require one shared atomic executor"
                )
            atomic = InMemoryAtomicExecutor((repository, self._idempotency))  # type: ignore[arg-type]
        self._atomic = atomic

    def get(self, tenant_id: str, specimen_id: str) -> SpecimenAggregate | None:
        """Return the current tenant-scoped aggregate for a recovery decision."""

        return self._repository.get(tenant_id, specimen_id)

    def register(self, command: Command) -> SpecimenAggregate:
        return self._atomic.execute(lambda: self._register(command))

    def _register(self, command: Command) -> SpecimenAggregate:
        if command.action != "register":
            raise TransitionRejected("registration requires action=register")
        reservation = self._idempotency.reserve(
            command.tenant_id, command.command_id, command.content_digest
        )
        if reservation.state is ReservationState.REPLAY:
            assert reservation.outcome is not None
            return reservation.outcome
        if reservation.state is ReservationState.IN_PROGRESS:
            raise IdempotencyInProgress(
                f"command {command.command_id} is already in progress; "
                "reconcile its recorded outcome before another execution"
            )
        current = self._repository.get(command.tenant_id, command.specimen_id)
        if current is not None:
            raise TransitionRejected(
                f"specimen {command.specimen_id} already exists; load its current lifecycle"
            )
        if command.expected_version != 0:
            raise TransitionRejected("registration begins from expected_version=0")
        aggregate = SpecimenAggregate(
            tenant_id=command.tenant_id,
            specimen_id=command.specimen_id,
            state=SpecimenState.REGISTERED,
            version=1,
            attributes=dict(command.payload),
        )
        aggregate = self._append_event(aggregate, command, "specimen.registered")
        self._repository.save(aggregate, previous_version=None)
        self._idempotency.commit(command.tenant_id, command.command_id, aggregate)
        return aggregate

    def transition(self, command: Command) -> SpecimenAggregate:
        return self._atomic.execute(lambda: self._transition(command))

    def _transition(self, command: Command) -> SpecimenAggregate:
        reservation = self._idempotency.reserve(
            command.tenant_id, command.command_id, command.content_digest
        )
        if reservation.state is ReservationState.REPLAY:
            assert reservation.outcome is not None
            return reservation.outcome
        if reservation.state is ReservationState.IN_PROGRESS:
            raise IdempotencyInProgress(
                f"command {command.command_id} is already in progress; "
                "reconcile its recorded outcome before another execution"
            )
        current = self._repository.get(command.tenant_id, command.specimen_id)
        if current is None:
            raise TransitionRejected(
                f"specimen {command.specimen_id} requires registration before {command.action}"
            )
        current.assert_version(command.expected_version)
        target = self._target_state(current.state, command)
        next_aggregate = replace(
            current,
            state=target,
            version=current.version + 1,
            attributes={**current.attributes, **dict(command.payload)},
        )
        next_aggregate = self._append_event(
            next_aggregate, command, f"specimen.{command.action}"
        )
        self._repository.save(next_aggregate, previous_version=current.version)
        self._idempotency.commit(command.tenant_id, command.command_id, next_aggregate)
        return next_aggregate

    @staticmethod
    def _target_state(current: SpecimenState, command: Command) -> SpecimenState:
        if command.action == "void":
            if not command.reason_code:
                raise TransitionRejected(
                    "voiding requires a reason code; supply the accountable disposition"
                )
            return SpecimenState.VOIDED
        target = _TRANSITIONS.get((current, command.action))
        if target is None:
            raise TransitionRejected(
                f"{command.action} has no lifecycle meaning from {current}; "
                "reload the specimen and select its next supported action"
            )
        if command.action in {"release", "correct"} and not command.reason_code:
            raise TransitionRejected(
                f"{command.action} requires a reason code; supply the review disposition"
            )
        return target

    @staticmethod
    def _append_event(
        aggregate: SpecimenAggregate, command: Command, event_type: str
    ) -> SpecimenAggregate:
        event_id = str(uuid5(_EVENT_NAMESPACE, f"{command.tenant_id}:{command.command_id}"))
        event = DomainEvent(
            event_id=event_id,
            tenant_id=command.tenant_id,
            specimen_id=command.specimen_id,
            aggregate_version=aggregate.version,
            event_type=event_type,
            actor_id=command.actor_id,
            command_id=command.command_id,
            command_digest=command.content_digest,
            occurred_at=require_aware_utc(command.occurred_at),
            payload=dict(command.payload),
            reason_code=command.reason_code,
        )
        return replace(aggregate, events=aggregate.events + (event,))
