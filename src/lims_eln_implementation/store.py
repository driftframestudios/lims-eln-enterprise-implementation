"""Persistence ports and a deterministic in-memory implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .model import RevisionConflict, SpecimenAggregate


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

