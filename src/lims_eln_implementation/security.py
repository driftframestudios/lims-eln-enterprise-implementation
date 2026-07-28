"""Tenant authorization and allowlisted evidence redaction."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, ClassVar, Mapping, Protocol


class AccessBoundaryError(PermissionError):
    """An access request requires a matching tenant and capability."""


class TenantSessionBindingError(RuntimeError):
    """A database transaction requires a verified tenant session setting."""


class TransactionCursor(Protocol):
    def execute(self, operation: str, parameters: tuple[str]) -> Any: ...

    def fetchone(self) -> tuple[Any, ...] | None: ...


@dataclass(frozen=True, slots=True)
class AccessContext:
    tenant_id: str
    actor_id: str
    capabilities: frozenset[str]

    def authorize(self, *, tenant_id: str, capability: str) -> None:
        if tenant_id != self.tenant_id:
            raise AccessBoundaryError(
                "tenant boundary requires the caller's own tenant; "
                "route the request through an authorized tenant context"
            )
        if capability not in self.capabilities:
            raise AccessBoundaryError(
                f"capability {capability} requires an assigned role; "
                "request access through the accountable owner"
            )


@dataclass(frozen=True, slots=True)
class PostgresTenantBinding:
    """Bind and verify one tenant identity for the current database transaction."""

    tenant_id: str
    STATEMENT: ClassVar[str] = (
        "select set_config('app.tenant_id', %s, true)"
    )

    def __post_init__(self) -> None:
        if not self.tenant_id or len(self.tenant_id) > 128:
            raise ValueError("tenant_id requires 1..128 characters")
        if any(ord(character) < 32 for character in self.tenant_id):
            raise ValueError("tenant_id requires printable characters")

    def bind(self, cursor: TransactionCursor) -> None:
        cursor.execute(self.STATEMENT, (self.tenant_id,))
        observed = cursor.fetchone()
        if observed != (self.tenant_id,):
            raise TenantSessionBindingError(
                "database transaction requires the requested tenant identity; "
                "return the connection to the pool and open a fresh transaction"
            )


class EvidenceRedactor:
    """Preserve diagnostic structure while replacing protected values."""

    _PROTECTED_NAME = re.compile(
        r"(patient|subject|name|email|phone|address|dob|birth|token|secret|password|key)",
        re.IGNORECASE,
    )

    def __init__(self, allowed_fields: set[str]) -> None:
        self._allowed = frozenset(allowed_fields)

    def redact(self, value: Any) -> Any:
        if isinstance(value, Mapping):
            output: dict[str, Any] = {}
            for key, item in value.items():
                normalized_key = str(key)
                if (
                    normalized_key not in self._allowed
                    or self._PROTECTED_NAME.search(normalized_key)
                ):
                    output[normalized_key] = "[REDACTED]"
                else:
                    output[normalized_key] = self.redact(item)
            return output
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.redact(item) for item in value)
        return value
