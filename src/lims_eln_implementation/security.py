"""Tenant authorization and allowlisted evidence redaction."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Callable, ClassVar, Mapping, Protocol


class AccessBoundaryError(PermissionError):
    """An access request requires a matching tenant and capability."""


class TenantSessionBindingError(RuntimeError):
    """A database transaction requires a verified tenant session setting."""


class TransactionCursor(Protocol):
    def execute(self, operation: str, parameters: tuple[str]) -> Any: ...

    def fetchone(self) -> tuple[Any, ...] | None: ...


_IDENTITY = re.compile(r"^[\x20-\x7e]{1,128}$")
_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_NONCE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_SHA256_HEX = re.compile(r"^[a-f0-9]{64}$")


def tenant_context_signing_message(
    *,
    tenant_id: str,
    subject_id: str,
    key_id: str,
    issued_at_epoch: int,
    expires_at_epoch: int,
    nonce: str,
) -> bytes:
    """Return the released byte contract shared by issuer and PostgreSQL."""
    return "\n".join(
        (
            tenant_id,
            subject_id,
            key_id,
            str(issued_at_epoch),
            str(expires_at_epoch),
            nonce,
        )
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class SignedTenantContext:
    """A short-lived tenant assertion signed by the trusted identity plane.

    The application receives the signed assertion as an opaque capability. Key
    material remains with the issuer and the database verifies the assertion
    independently before row-level policies expose tenant state.
    """

    tenant_id: str
    subject_id: str
    key_id: str
    issued_at_epoch: int
    expires_at_epoch: int
    nonce: str
    signature_hex: str

    MAX_LIFETIME_SECONDS: ClassVar[int] = 15 * 60

    def __post_init__(self) -> None:
        for field_name in ("tenant_id", "subject_id"):
            field_value = getattr(self, field_name)
            if not field_value.strip() or _IDENTITY.fullmatch(field_value) is None:
                raise ValueError(f"{field_name} requires 1..128 printable ASCII characters")
        if _KEY_ID.fullmatch(self.key_id) is None:
            raise ValueError("key_id requires a stable 1..64 character identifier")
        if _NONCE.fullmatch(self.nonce) is None:
            raise ValueError("nonce requires 16..128 URL-safe characters")
        if _SHA256_HEX.fullmatch(self.signature_hex) is None:
            raise ValueError("signature_hex requires a lowercase SHA-256 HMAC")
        if self.issued_at_epoch < 0 or self.expires_at_epoch <= self.issued_at_epoch:
            raise ValueError("tenant context requires an ordered positive validity window")
        if self.expires_at_epoch - self.issued_at_epoch > self.MAX_LIFETIME_SECONDS:
            raise ValueError("tenant context lifetime requires 900 seconds or less")

    def as_document(self) -> dict[str, str | int]:
        return {
            "expires_at_epoch": self.expires_at_epoch,
            "issued_at_epoch": self.issued_at_epoch,
            "key_id": self.key_id,
            "nonce": self.nonce,
            "signature_hex": self.signature_hex,
            "subject_id": self.subject_id,
            "tenant_id": self.tenant_id,
        }

    def as_json(self) -> str:
        return json.dumps(self.as_document(), sort_keys=True, separators=(",", ":"))


TenantContextProvider = Callable[[str], SignedTenantContext]


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
    """Ask PostgreSQL to verify one signed tenant context for this transaction."""

    context: SignedTenantContext
    STATEMENT: ClassVar[str] = (
        "select laboratory_security.bind_tenant_context(%s::jsonb)"
    )

    @property
    def tenant_id(self) -> str:
        return self.context.tenant_id

    def bind(
        self,
        cursor: TransactionCursor,
        *,
        expected_tenant_id: str | None = None,
    ) -> None:
        if expected_tenant_id is not None and expected_tenant_id != self.tenant_id:
            raise TenantSessionBindingError(
                "tenant context provider returned another tenant; "
                "route the request to identity reconciliation"
            )
        cursor.execute(self.STATEMENT, (self.context.as_json(),))
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
