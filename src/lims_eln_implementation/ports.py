"""Vendor-neutral integration contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, Protocol


class WriteCertainty(StrEnum):
    CONFIRMED = "confirmed"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class ExternalRecord:
    tenant_id: str
    external_identity: str
    revision: int
    canonical_digest: str
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class WriteResult:
    certainty: WriteCertainty
    external_identity: str
    revision: int | None
    trace_id: str


class VendorGateway(Protocol):
    vendor_name: str

    def write(
        self,
        *,
        tenant_id: str,
        external_identity: str,
        expected_revision: int,
        payload: Mapping[str, Any],
        request_id: str,
    ) -> WriteResult: ...

    def read(self, *, tenant_id: str, external_identity: str) -> ExternalRecord | None: ...


class VendorRevisionConflict(RuntimeError):
    """The external record advanced beyond the caller's source revision."""

