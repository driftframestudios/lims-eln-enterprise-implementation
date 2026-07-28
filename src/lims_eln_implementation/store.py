"""Persistence ports and a deterministic in-memory implementation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from typing import Generic, Protocol, TypeVar

from .model import RevisionConflict, SpecimenAggregate


T = TypeVar("T")


class TransactionParticipant(Protocol):
    """State that can participate in the deterministic transaction adapter."""

    def transaction_snapshot(self) -> object: ...

    def transaction_restore(self, snapshot: object) -> None: ...


class AtomicExecutor(Protocol):
    """One commit boundary shared by application state and its evidence."""

    def execute(self, operation: Callable[[], T]) -> T: ...


class InMemoryAtomicExecutor(Generic[T]):
    """Serial, rollback-capable conformance adapter for a database transaction.

    Deployment adapters implement ``AtomicExecutor`` with one database
    transaction and pass the same connection to every durable participant.
    """

    def __init__(self, participants: tuple[TransactionParticipant, ...]) -> None:
        if not participants:
            raise ValueError("an atomic executor requires at least one participant")
        self._participants = participants
        self._lock = RLock()

    def execute(self, operation: Callable[[], T]) -> T:
        with self._lock:
            snapshots = tuple(
                participant.transaction_snapshot()
                for participant in self._participants
            )
            try:
                return operation()
            except BaseException:
                for participant, snapshot in reversed(
                    tuple(zip(self._participants, snapshots))
                ):
                    participant.transaction_restore(snapshot)
                raise


class SpecimenRepository(Protocol):
    def get(self, tenant_id: str, specimen_id: str) -> SpecimenAggregate | None: ...

    def save(self, aggregate: SpecimenAggregate, previous_version: int | None) -> None: ...


class InMemorySpecimenRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], SpecimenAggregate] = {}

    def get(self, tenant_id: str, specimen_id: str) -> SpecimenAggregate | None:
        return self._items.get((tenant_id, specimen_id))

    def save(self, aggregate: SpecimenAggregate, previous_version: int | None) -> None:
        identity = (aggregate.tenant_id, aggregate.specimen_id)
        current = self._items.get(identity)
        actual_previous = current.version if current else None
        if actual_previous != previous_version:
            replacement = actual_previous if actual_previous is not None else "absent"
            raise RevisionConflict(
                f"persistence revision is {replacement}; reload and plan from the stored revision"
            )
        self._items[identity] = aggregate

    def transaction_snapshot(self) -> object:
        return dict(self._items)

    def transaction_restore(self, snapshot: object) -> None:
        if not isinstance(snapshot, dict):
            raise TypeError("specimen transaction snapshot requires a dictionary")
        self._items = dict(snapshot)


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    message_id: str
    tenant_id: str
    topic: str
    aggregate_id: str
    aggregate_version: int
    payload_digest: str


class InMemoryOutbox:
    def __init__(self) -> None:
        self.messages: list[OutboxMessage] = []

    def append(self, message: OutboxMessage) -> None:
        if any(item.message_id == message.message_id for item in self.messages):
            return
        self.messages.append(message)

    def transaction_snapshot(self) -> object:
        return tuple(self.messages)

    def transaction_restore(self, snapshot: object) -> None:
        if not isinstance(snapshot, tuple):
            raise TypeError("outbox transaction snapshot requires a tuple")
        self.messages = list(snapshot)
