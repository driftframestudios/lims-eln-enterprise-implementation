"""Tenant-scoped custody transfers with outbox evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .model import DomainError, require_aware_utc
from .store import (
    AtomicExecutor,
    InMemoryAtomicExecutor,
    InMemoryOutbox,
    OutboxMessage,
)


@dataclass(frozen=True, slots=True)
class CustodyPosition:
    tenant_id: str
    specimen_id: str
    location: str
    version: int
    custodian_id: str
    occurred_at: datetime
    last_transfer_id: str


@dataclass(frozen=True, slots=True)
class CustodyEvent:
    tenant_id: str
    specimen_id: str
    transfer_id: str
    expected_version: int
    resulting_version: int
    from_location: str | None
    to_location: str
    custodian_id: str
    occurred_at: datetime


class CustodyRepository(Protocol):
    def get(self, tenant_id: str, specimen_id: str) -> CustodyPosition | None: ...

    def get_transfer(self, tenant_id: str, transfer_id: str) -> CustodyEvent | None: ...

    def save(
        self,
        position: CustodyPosition,
        *,
        previous_version: int,
        event: CustodyEvent,
    ) -> None: ...

    def history(self, tenant_id: str, specimen_id: str) -> tuple[CustodyEvent, ...]: ...


class InMemoryCustodyRepository:
    """Tenant-scoped custody state for the atomic conformance adapter."""

    def __init__(self) -> None:
        self._positions: dict[tuple[str, str], CustodyPosition] = {}
        self._events: list[CustodyEvent] = []
        self._transfers: dict[tuple[str, str], CustodyEvent] = {}

    def get(self, tenant_id: str, specimen_id: str) -> CustodyPosition | None:
        return self._positions.get((tenant_id, specimen_id))

    def get_transfer(self, tenant_id: str, transfer_id: str) -> CustodyEvent | None:
        return self._transfers.get((tenant_id, transfer_id))

    def save(
        self,
        position: CustodyPosition,
        *,
        previous_version: int,
        event: CustodyEvent,
    ) -> None:
        identity = (position.tenant_id, position.specimen_id)
        current = self._positions.get(identity)
        actual_version = current.version if current else 0
        if actual_version != previous_version:
            raise DomainError(
                f"custody is revision {actual_version}; reload it and plan the transfer again"
            )
        transfer_identity = (event.tenant_id, event.transfer_id)
        if transfer_identity in self._transfers:
            raise DomainError(
                "custody transfer identity already has durable meaning; "
                "use its recorded outcome or allocate a new identity"
            )
        self._positions[(position.tenant_id, position.specimen_id)] = position
        self._events.append(event)
        self._transfers[transfer_identity] = event

    def history(self, tenant_id: str, specimen_id: str) -> tuple[CustodyEvent, ...]:
        return tuple(
            event
            for event in self._events
            if event.tenant_id == tenant_id and event.specimen_id == specimen_id
        )

    def transaction_snapshot(self) -> object:
        return (dict(self._positions), tuple(self._events), dict(self._transfers))

    def transaction_restore(self, snapshot: object) -> None:
        if not isinstance(snapshot, tuple) or len(snapshot) != 3:
            raise TypeError("custody transaction snapshot requires positions and history")
        positions, events, transfers = snapshot
        if (
            not isinstance(positions, dict)
            or not isinstance(events, tuple)
            or not isinstance(transfers, dict)
        ):
            raise TypeError("custody transaction snapshot requires typed state")
        self._positions = dict(positions)
        self._events = list(events)
        self._transfers = dict(transfers)


class CustodyService:
    def __init__(
        self,
        outbox: InMemoryOutbox,
        *,
        repository: CustodyRepository | None = None,
        atomic: AtomicExecutor | None = None,
    ) -> None:
        self._repository = repository or InMemoryCustodyRepository()
        self._outbox = outbox
        if atomic is None:
            if not all(
                hasattr(participant, "transaction_snapshot")
                and hasattr(participant, "transaction_restore")
                for participant in (self._repository, outbox)
            ):
                raise ValueError(
                    "durable custody adapters require one shared atomic executor"
                )
            atomic = InMemoryAtomicExecutor((self._repository, outbox))  # type: ignore[arg-type]
        self._atomic = atomic

    def place(
        self,
        *,
        tenant_id: str,
        specimen_id: str,
        location: str,
        custodian_id: str,
        expected_version: int,
        transfer_id: str,
        occurred_at: datetime,
    ) -> CustodyPosition:
        return self._atomic.execute(
            lambda: self._place(
                tenant_id=tenant_id,
                specimen_id=specimen_id,
                location=location,
                custodian_id=custodian_id,
                expected_version=expected_version,
                transfer_id=transfer_id,
                occurred_at=occurred_at,
            )
        )

    def _place(
        self,
        *,
        tenant_id: str,
        specimen_id: str,
        location: str,
        custodian_id: str,
        expected_version: int,
        transfer_id: str,
        occurred_at: datetime,
    ) -> CustodyPosition:
        for name, value in (
            ("tenant_id", tenant_id),
            ("specimen_id", specimen_id),
            ("location", location),
            ("custodian_id", custodian_id),
            ("transfer_id", transfer_id),
        ):
            if not value.strip():
                raise DomainError(f"{name} requires a non-empty value")
        if expected_version < 0:
            raise DomainError("expected_version requires zero or a positive integer")
        occurred_at = require_aware_utc(occurred_at)
        identity = (tenant_id, specimen_id)
        prior_transfer = self._repository.get_transfer(tenant_id, transfer_id)
        if prior_transfer is not None:
            requested = (
                specimen_id,
                expected_version,
                location,
                custodian_id,
                occurred_at,
            )
            recorded = (
                prior_transfer.specimen_id,
                prior_transfer.expected_version,
                prior_transfer.to_location,
                prior_transfer.custodian_id,
                prior_transfer.occurred_at,
            )
            if requested != recorded:
                raise DomainError(
                    "custody transfer identity already binds to different content; "
                    "allocate a new transfer identity after review"
                )
            replay = self._repository.get(tenant_id, specimen_id)
            if replay is None or replay.version < prior_transfer.resulting_version:
                raise DomainError(
                    "custody replay requires its durable resulting position; "
                    "route the aggregate to reconciliation"
                )
            return CustodyPosition(
                tenant_id=prior_transfer.tenant_id,
                specimen_id=prior_transfer.specimen_id,
                location=prior_transfer.to_location,
                version=prior_transfer.resulting_version,
                custodian_id=prior_transfer.custodian_id,
                occurred_at=prior_transfer.occurred_at,
                last_transfer_id=prior_transfer.transfer_id,
            )
        current = self._repository.get(*identity)
        current_version = current.version if current else 0
        if expected_version != current_version:
            raise DomainError(
                f"custody is revision {current_version}; reload it and plan the transfer again"
            )
        event = CustodyEvent(
            tenant_id=tenant_id,
            specimen_id=specimen_id,
            transfer_id=transfer_id,
            expected_version=expected_version,
            resulting_version=current_version + 1,
            from_location=current.location if current else None,
            to_location=location,
            custodian_id=custodian_id,
            occurred_at=occurred_at,
        )
        next_position = CustodyPosition(
            tenant_id=tenant_id,
            specimen_id=specimen_id,
            location=location,
            version=current_version + 1,
            custodian_id=custodian_id,
            occurred_at=occurred_at,
            last_transfer_id=transfer_id,
        )
        self._repository.save(
            next_position,
            previous_version=current_version,
            event=event,
        )
        payload = {
            "custodian_id": custodian_id,
            "from_location": event.from_location,
            "occurred_at_utc": occurred_at.isoformat(),
            "specimen_id": specimen_id,
            "to_location": location,
            "transfer_id": transfer_id,
            "version": next_position.version,
        }
        self._outbox.append(
            OutboxMessage(
                message_id=transfer_id,
                tenant_id=tenant_id,
                topic="custody.position.changed",
                aggregate_id=specimen_id,
                aggregate_version=next_position.version,
                payload=payload,
            )
        )
        return next_position

    def current(self, tenant_id: str, specimen_id: str) -> CustodyPosition | None:
        return self._repository.get(tenant_id, specimen_id)

    def history(self, tenant_id: str, specimen_id: str) -> tuple[CustodyEvent, ...]:
        return self._repository.history(tenant_id, specimen_id)
