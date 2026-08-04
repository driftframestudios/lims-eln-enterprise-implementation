"""Canonical laboratory types with stable serialization and revision semantics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Mapping


class DomainError(ValueError):
    """Base class for explainable domain decisions."""


class RevisionConflict(DomainError):
    """The command planned from an earlier aggregate revision."""


class TransitionRejected(DomainError):
    """The requested transition has no meaning from the current state."""


class SpecimenState(StrEnum):
    REGISTERED = "registered"
    ACCESSIONED = "accessioned"
    IN_PROCESS = "in_process"
    UNDER_REVIEW = "under_review"
    RELEASED = "released"
    CORRECTED = "corrected"
    VOIDED = "voided"


def require_aware_utc(value: datetime) -> datetime:
    """Return a timezone-aware UTC timestamp or explain the required replacement."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainError("timestamp requires an explicit timezone; supply an aware UTC value")
    return value.astimezone(timezone.utc)


def canonical_json(value: Any) -> str:
    """Serialize a value into a stable comparison form."""
    def normalize(item: Any) -> Any:
        if isinstance(item, Mapping):
            if any(not isinstance(key, str) for key in item):
                raise TypeError("JSON object keys require strings")
            return {key: normalize(nested) for key, nested in item.items()}
        if isinstance(item, (list, tuple)):
            return [normalize(nested) for nested in item]
        return item

    try:
        return json.dumps(
            normalize(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise DomainError(
            "canonical content requires finite JSON values and string-keyed mappings"
        ) from error


def canonical_digest(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def immutable_json(value: Any) -> Any:
    """Return a recursively immutable snapshot of already-normalized JSON."""
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: immutable_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(immutable_json(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class Command:
    command_id: str
    tenant_id: str
    specimen_id: str
    actor_id: str
    action: str
    expected_version: int
    occurred_at: datetime
    payload: Mapping[str, Any] = field(default_factory=dict)
    reason_code: str | None = None
    _payload_json: str = field(init=False, repr=False)
    _content_digest: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("command_id", self.command_id),
            ("tenant_id", self.tenant_id),
            ("specimen_id", self.specimen_id),
            ("actor_id", self.actor_id),
            ("action", self.action),
        ):
            if not value.strip():
                raise DomainError(f"{name} requires a non-empty value")
        if self.expected_version < 0:
            raise DomainError("expected_version requires zero or a positive integer")
        occurred_at = require_aware_utc(self.occurred_at)
        if not isinstance(self.payload, Mapping):
            raise DomainError("payload requires a JSON object")
        payload_json = canonical_json(dict(self.payload))
        payload_snapshot = json.loads(payload_json)
        if not isinstance(payload_snapshot, dict):
            raise DomainError("payload requires a JSON object")
        object.__setattr__(self, "payload", immutable_json(payload_snapshot))
        object.__setattr__(self, "_payload_json", payload_json)
        object.__setattr__(
            self,
            "_content_digest",
            canonical_digest(
                {
                    "tenant_id": self.tenant_id,
                    "specimen_id": self.specimen_id,
                    "actor_id": self.actor_id,
                    "action": self.action,
                    "expected_version": self.expected_version,
                    "occurred_at": occurred_at.isoformat(),
                    "payload": payload_snapshot,
                    "reason_code": self.reason_code,
                }
            ),
        )

    @property
    def content_digest(self) -> str:
        return self._content_digest


@dataclass(frozen=True, slots=True)
class DomainEvent:
    event_id: str
    tenant_id: str
    specimen_id: str
    aggregate_version: int
    event_type: str
    actor_id: str
    command_id: str
    command_digest: str
    occurred_at: datetime
    payload: Mapping[str, Any]
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class SpecimenAggregate:
    tenant_id: str
    specimen_id: str
    state: SpecimenState
    version: int
    attributes: Mapping[str, Any] = field(default_factory=dict)
    events: tuple[DomainEvent, ...] = ()

    def assert_version(self, expected_version: int) -> None:
        if self.version != expected_version:
            raise RevisionConflict(
                f"specimen {self.specimen_id} is revision {self.version}; "
                f"reload it and plan from that revision"
            )
