"""Tenant-scoped custody transfers with outbox evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .model import DomainError, canonical_digest, require_aware_utc
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


class CustodyRepository(Protocol):
    def get(self, tenant_id: str, specimen_id: str) -> CustodyPosition | None: ...

    def save(self, position: CustodyPosition) -> None: ...


class InMemoryCustodyRepository:
    """Tenant-scoped custody state for the atomic conformance adapter."""

    def __init__(self) -> None:
        self._positions: dict[tuple[str, str], CustodyPosition] = {}

    def get(self, tenant_id: str, specimen_id: str) -> CustodyPosition | None:
        return self._positions.get((tenant_id, specimen_id))

    def save(self, position: CustodyPosition) -> None:
        self._positions[(position.tenant_id, position.specimen_id)] = position

    def transaction_snapshot(self) -> object:
        return dict(self._positions)

    def transaction_restore(self, snapshot: object) -> None:
        if not isinstance(snapshot, dict):
            raise TypeError("custody transaction snapshot requires a dictionary")
        self._positions = dict(snapshot)


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
        identity = (tenant_id, specimen_id)
        current = self._repository.get(*identity)
        current_version = current.version if current else 0
        if expected_version != current_version:
            raise DomainError(
                f"custody is revision {current_version}; reload it and plan the transfer again"
            )
        if not location.strip():
            raise DomainError("custody location requires a named destination")
        next_position = CustodyPosition(
            tenant_id=tenant_id,
            specimen_id=specimen_id,
            location=location,
            version=current_version + 1,
            custodian_id=custodian_id,
            occurred_at=require_aware_utc(occurred_at),
        )
        self._repository.save(next_position)
        self._outbox.append(
            OutboxMessage(
                message_id=transfer_id,
                tenant_id=tenant_id,
                topic="custody.position.changed",
                aggregate_id=specimen_id,
                aggregate_version=next_position.version,
                payload_digest=canonical_digest(
                    {
                        "location": location,
                        "custodian_id": custodian_id,
                        "version": next_position.version,
                    }
                ),
            )
        )
        return next_position

    def current(self, tenant_id: str, specimen_id: str) -> CustodyPosition | None:
        return self._repository.get(tenant_id, specimen_id)
