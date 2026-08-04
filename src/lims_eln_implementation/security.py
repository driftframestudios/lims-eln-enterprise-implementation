"""Small security utilities at real application boundaries."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol


class TenantSessionBindingError(RuntimeError):
    """A transaction failed to retain its selected tenant scope."""


class TransactionCursor(Protocol):
    def execute(self, operation: str, parameters: tuple[str]) -> Any: ...

    def fetchone(self) -> tuple[Any, ...] | None: ...


@dataclass(frozen=True, slots=True)
class PostgresTenantScope:
    """Set one transaction-local tenant after application authorization.

    This helper is a row-isolation coordinate, not an authorization mechanism.
    The deployment identity provider and application policy decide which tenant
    the authenticated request may select before this method is called.
    """

    tenant_id: str
    STATEMENT = "select set_config('app.tenant_id', %s, true)"

    def __post_init__(self) -> None:
        if not self.tenant_id.strip():
            raise ValueError("tenant scope requires a populated tenant identity")

    def bind(self, cursor: TransactionCursor) -> None:
        cursor.execute(self.STATEMENT, (self.tenant_id,))
        if cursor.fetchone() != (self.tenant_id,):
            raise TenantSessionBindingError(
                "database transaction requires the selected tenant scope"
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
                if normalized_key not in self._allowed or self._PROTECTED_NAME.search(
                    normalized_key
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
