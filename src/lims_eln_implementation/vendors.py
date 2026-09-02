"""Authoritative-readback vendor projection and deterministic conformance double."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping
from uuid import UUID, uuid5

from .idempotency import IdempotencyInProgress, IdempotencyLedger, ReservationState
from .model import canonical_digest
from .observability import OperationalMetrics
from .ports import (
    ExternalRecord,
    VendorGateway,
    VendorRevisionConflict,
    WriteCertainty,
    WriteResult,
)


_TRACE_NAMESPACE = UUID("51570d34-c434-41b7-a3cf-5f6a577fe3d4")


class FaultMode(StrEnum):
    CLEAR = "clear"
    TIMEOUT_BEFORE_COMMIT = "timeout_before_commit"
    TIMEOUT_AFTER_COMMIT = "timeout_after_commit"


class InMemoryVendorGateway:
    """A deterministic contract double for Sapio, Benchling, and LabKey seams."""

    def __init__(self, vendor_name: str) -> None:
        self.vendor_name = vendor_name
        self.fault_mode = FaultMode.CLEAR
        self._records: dict[tuple[str, str], ExternalRecord] = {}

    def write(
        self,
        *,
        tenant_id: str,
        external_identity: str,
        expected_revision: int,
        payload: Mapping[str, Any],
        request_id: str,
    ) -> WriteResult:
        trace_id = str(uuid5(_TRACE_NAMESPACE, f"{self.vendor_name}:{request_id}"))
        if self.fault_mode is FaultMode.TIMEOUT_BEFORE_COMMIT:
            return WriteResult(
                certainty=WriteCertainty.AMBIGUOUS,
                external_identity=external_identity,
                revision=None,
                trace_id=trace_id,
            )
        identity = (tenant_id, external_identity)
        current = self._records.get(identity)
        actual_revision = current.revision if current else 0
        if actual_revision != expected_revision:
            raise VendorRevisionConflict(
                f"{self.vendor_name} record is revision {actual_revision}; "
                "read its authoritative state and replan the projection"
            )
        record = ExternalRecord(
            tenant_id=tenant_id,
            external_identity=external_identity,
            revision=actual_revision + 1,
            canonical_digest=canonical_digest(dict(payload)),
            payload=dict(payload),
        )
        self._records[identity] = record
        if self.fault_mode is FaultMode.TIMEOUT_AFTER_COMMIT:
            return WriteResult(
                certainty=WriteCertainty.AMBIGUOUS,
                external_identity=external_identity,
                revision=None,
                trace_id=trace_id,
            )
        return WriteResult(
            certainty=WriteCertainty.CONFIRMED,
            external_identity=external_identity,
            revision=record.revision,
            trace_id=trace_id,
        )

    def read(self, *, tenant_id: str, external_identity: str) -> ExternalRecord | None:
        return self._records.get((tenant_id, external_identity))


@dataclass(frozen=True, slots=True)
class ProjectionOutcome:
    vendor_name: str
    external_identity: str
    revision: int
    canonical_digest: str
    reconciled: bool
    trace_id: str


class AmbiguousOutcomePending(RuntimeError):
    """Authoritative readback has yet to show the requested external effect."""


class VendorProjectionService:
    def __init__(
        self,
        gateway: VendorGateway,
        *,
        idempotency: IdempotencyLedger[ProjectionOutcome] | None = None,
        metrics: OperationalMetrics | None = None,
    ) -> None:
        self._gateway = gateway
        self._idempotency = idempotency or IdempotencyLedger()
        self._metrics = metrics or OperationalMetrics()

    def project(
        self,
        *,
        tenant_id: str,
        request_id: str,
        external_identity: str,
        expected_revision: int,
        payload: Mapping[str, Any],
    ) -> ProjectionOutcome:
        payload_digest = canonical_digest(dict(payload))
        reservation = self._idempotency.reserve(tenant_id, request_id, payload_digest)
        if reservation.state is ReservationState.REPLAY:
            assert reservation.outcome is not None
            return reservation.outcome
        if reservation.state is ReservationState.IN_PROGRESS:
            raise IdempotencyInProgress(
                f"vendor request {request_id} is already in progress; "
                "use authoritative readback and an accountable recovery decision"
            )
        write = self._gateway.write(
            tenant_id=tenant_id,
            external_identity=external_identity,
            expected_revision=expected_revision,
            payload=payload,
            request_id=request_id,
        )
        reconciled = False
        if write.certainty is WriteCertainty.AMBIGUOUS:
            authoritative = self._gateway.read(
                tenant_id=tenant_id, external_identity=external_identity
            )
            is_match = bool(
                authoritative and authoritative.canonical_digest == payload_digest
            )
            self._metrics.reconciliation.observe(good=is_match)
            if not is_match:
                self._metrics.vendor_projection.observe(good=False)
                raise AmbiguousOutcomePending(
                    f"{self._gateway.vendor_name} outcome is pending; "
                    "retain the reservation and reconcile by stable external identity"
                )
            reconciled = True
            revision = authoritative.revision
        else:
            assert write.revision is not None
            revision = write.revision
        outcome = ProjectionOutcome(
            vendor_name=self._gateway.vendor_name,
            external_identity=external_identity,
            revision=revision,
            canonical_digest=payload_digest,
            reconciled=reconciled,
            trace_id=write.trace_id,
        )
        self._idempotency.commit(tenant_id, request_id, outcome)
        self._metrics.vendor_projection.observe(good=True)
        return outcome
