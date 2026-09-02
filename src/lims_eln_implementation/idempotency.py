"""Exact-replay coordination for commands and external effects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar


T = TypeVar("T")


class IdempotencyError(ValueError):
    """Base class for idempotency decisions."""


class ContentCollision(IdempotencyError):
    """A stable key arrived with different semantic content."""


class IdempotencyInProgress(IdempotencyError):
    """A matching reservation already owns the right to execute."""


ReservationInProgress = IdempotencyInProgress


class ReservationState(StrEnum):
    ACQUIRED = "acquired"
    REPLAY = "replay"
    IN_PROGRESS = "in_progress"


@dataclass(frozen=True, slots=True)
class Reservation(Generic[T]):
    state: ReservationState
    outcome: T | None = None


@dataclass(slots=True)
class _Entry(Generic[T]):
    content_digest: str
    outcome: T | None = None
    committed: bool = False


class IdempotencyLedger(Generic[T]):
    """In-memory contract mirroring a durable unique-key ledger."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], _Entry[T]] = {}

    def reserve(self, tenant_id: str, key: str, content_digest: str) -> Reservation[T]:
        identity = (tenant_id, key)
        current = self._entries.get(identity)
        if current is None:
            self._entries[identity] = _Entry(content_digest=content_digest)
            return Reservation(ReservationState.ACQUIRED)
        if current.content_digest != content_digest:
            raise ContentCollision(
                f"idempotency key {key} already represents different content; "
                "use the original payload or allocate a new command identity"
            )
        if current.committed:
            return Reservation(ReservationState.REPLAY, current.outcome)
        return Reservation(ReservationState.IN_PROGRESS)

    def commit(self, tenant_id: str, key: str, outcome: T) -> None:
        entry = self._entries[(tenant_id, key)]
        entry.outcome = outcome
        entry.committed = True

    def recover(self, tenant_id: str, key: str) -> T | None:
        entry = self._entries.get((tenant_id, key))
        return entry.outcome if entry and entry.committed else None

    def transaction_snapshot(self) -> object:
        """Capture ledger state for the deterministic atomic conformance adapter."""

        return {
            identity: _Entry(
                content_digest=entry.content_digest,
                outcome=entry.outcome,
                committed=entry.committed,
            )
            for identity, entry in self._entries.items()
        }

    def transaction_restore(self, snapshot: object) -> None:
        """Restore a snapshot after a reference transaction fails."""

        if not isinstance(snapshot, dict):
            raise TypeError("idempotency transaction snapshot requires a dictionary")
        self._entries = dict(snapshot)
