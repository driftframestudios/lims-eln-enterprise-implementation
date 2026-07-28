"""Tenant-scoped custody transfers with outbox evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .model import DomainError, canonical_digest, require_aware_utc
from .store import InMemoryOutbox, OutboxMessage


@dataclass(frozen=True, slots=True)
class CustodyPosition:
    tenant_id: str
    specimen_id: str
    location: str
    version: int
    custodian_id: str
    occurred_at: datetime


class CustodyService:
    def __init__(self, outbox: InMemoryOutbox) -> None:
        self._positions: dict[tuple[str, str], CustodyPosition] = {}
        self._outbox = outbox

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
        identity = (tenant_id, specimen_id)
        current = self._positions.get(identity)
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
        self._positions[identity] = next_position
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
        return self._positions.get((tenant_id, specimen_id))

