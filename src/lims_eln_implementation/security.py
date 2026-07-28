"""Tenant authorization and allowlisted evidence redaction."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping


class AccessBoundaryError(PermissionError):
    """An access request requires a matching tenant and capability."""


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

