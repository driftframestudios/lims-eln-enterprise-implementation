"""Persistence ports and a deterministic in-memory implementation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from hashlib import sha256
import json
from threading import RLock
from typing import Any, Generic, Mapping, Protocol, TypeVar

from .model import (
    DomainError,
    RevisionConflict,
    SpecimenAggregate,
    canonical_json,
    immutable_json,
)


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

    def list_for_tenant(self, tenant_id: str) -> tuple[SpecimenAggregate, ...]: ...

    def save(self, aggregate: SpecimenAggregate, previous_version: int | None) -> None: ...


class InMemorySpecimenRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], SpecimenAggregate] = {}

    def get(self, tenant_id: str, specimen_id: str) -> SpecimenAggregate | None:
        return self._items.get((tenant_id, specimen_id))

    def list_for_tenant(self, tenant_id: str) -> tuple[SpecimenAggregate, ...]:
        return tuple(
            aggregate
            for (item_tenant_id, _), aggregate in sorted(self._items.items())
            if item_tenant_id == tenant_id
        )

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
    payload: Mapping[str, Any] = field(repr=False)
    payload_json: str = field(init=False)
    payload_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("message_id", self.message_id),
            ("tenant_id", self.tenant_id),
            ("topic", self.topic),
            ("aggregate_id", self.aggregate_id),
        ):
            if not value.strip() or len(value) > 256 or not value.isprintable():
                raise DomainError(f"{name} requires 1..256 visible characters")
        if self.aggregate_version < 1:
            raise DomainError("aggregate_version requires a positive integer")
        if not isinstance(self.payload, Mapping):
            raise DomainError("outbox payload requires a JSON object")
        payload_json = canonical_json(dict(self.payload))
        payload_snapshot = json.loads(payload_json)
        if not isinstance(payload_snapshot, dict):
            raise DomainError("outbox payload requires a JSON object")
        object.__setattr__(self, "payload", immutable_json(payload_snapshot))
        object.__setattr__(self, "payload_json", payload_json)
        object.__setattr__(
            self,
            "payload_digest",
            sha256(payload_json.encode("utf-8")).hexdigest(),
        )


class OutboxContentCollision(DomainError):
    """One tenant-scoped message identity already names different content."""


class InMemoryOutbox:
    def __init__(self) -> None:
        self.messages: list[OutboxMessage] = []
        self._by_identity: dict[tuple[str, str], OutboxMessage] = {}

    def append(self, message: OutboxMessage) -> None:
        identity = (message.tenant_id, message.message_id)
        current = self._by_identity.get(identity)
        if current is not None and (
            current.topic,
            current.aggregate_id,
            current.aggregate_version,
            current.payload_json,
        ) == (
            message.topic,
            message.aggregate_id,
            message.aggregate_version,
            message.payload_json,
        ):
            return
        if current is not None:
            raise OutboxContentCollision(
                "outbox identity already binds to different content; "
                "allocate a new tenant-scoped message identity"
            )
        self.messages.append(message)
        self._by_identity[identity] = message

    def transaction_snapshot(self) -> object:
        return tuple(self.messages)

    def transaction_restore(self, snapshot: object) -> None:
        if not isinstance(snapshot, tuple):
            raise TypeError("outbox transaction snapshot requires a tuple")
        self.messages = list(snapshot)
        self._by_identity = {
            (message.tenant_id, message.message_id): message
            for message in self.messages
        }
