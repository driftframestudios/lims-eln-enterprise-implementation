"""Application service and read model for the Golden Specimen Workbench."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from threading import RLock
from typing import Any, Callable, Mapping

from ..application import (
    GoldenSpecimenOutcome,
    InstrumentReviewRequired,
    build_reference_golden_specimen_application,
)
from ..custody import CustodyPosition, CustodyService
from ..idempotency import ContentCollision
from ..instrument import IngressDisposition, InstrumentIngress, NormalizedObservation
from ..lifecycle import LifecycleService
from ..model import (
    DomainError,
    DomainEvent,
    SpecimenAggregate,
    canonical_digest,
    require_aware_utc,
)
from ..store import InMemoryOutbox, InMemorySpecimenRepository
from ..vendors import (
    FaultMode,
    InMemoryVendorGateway,
    ProjectionOutcome,
    VendorProjectionService,
)
from .shared_contracts import SharedContractUnavailable, build_observation, contract_available


@dataclass(frozen=True, slots=True)
class InstrumentReceipt:
    tenant_id: str
    specimen_id: str
    message_id: str
    instrument_id: str
    disposition: str
    raw_sha256: str
    normalized_observation: NormalizedObservation | None
    normalized_digest: str | None
    reason_code: str | None
    recovery: str
    captured_at: datetime

    def to_document(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "specimen_id": self.specimen_id,
            "message_id": self.message_id,
            "instrument_id": self.instrument_id,
            "disposition": self.disposition,
            "raw_sha256": self.raw_sha256,
            "normalized_observation": (
                self.normalized_observation.to_document()
                if self.normalized_observation is not None
                else None
            ),
            "normalized_digest": self.normalized_digest,
            "reason_code": self.reason_code,
            "recovery": self.recovery,
            "captured_at": require_aware_utc(self.captured_at).isoformat(),
        }


@dataclass(frozen=True, slots=True)
class SpecimenView:
    aggregate: SpecimenAggregate
    custody: CustodyPosition | None
    instrument_receipts: tuple[InstrumentReceipt, ...]
    projection: ProjectionOutcome | None

    def to_document(self) -> dict[str, Any]:
        return {
            "tenant_id": self.aggregate.tenant_id,
            "specimen_id": self.aggregate.specimen_id,
            "state": self.aggregate.state.value,
            "version": self.aggregate.version,
            "attributes": dict(self.aggregate.attributes),
            "events": [_event_document(event) for event in self.aggregate.events],
            "custody": _custody_document(self.custody),
            "instrument_receipts": [
                receipt.to_document() for receipt in self.instrument_receipts
            ],
            "projection": _projection_document(self.projection),
        }


class SpecimenAbsent(KeyError):
    """The tenant-scoped specimen read model has yet to be established."""


class ObservationAbsent(KeyError):
    """The tenant-scoped workbench run has yet to emit a shared observation."""


class WorkbenchService:
    """Thread-safe composition root for the synthetic functional nucleus.

    The default adapter keeps state in process for a fast local encounter. Its
    domain services and result shapes are the same seams used by durable
    deployment adapters.
    """

    def __init__(
        self,
        *,
        tenant_id: str = "SYN-TENANT-A",
        caller_id: str = "svc-golden-specimen-workbench",
        actor_ids: frozenset[str] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        permitted_actor_ids = actor_ids or frozenset(
            {"SYN-ACTOR-01", "SYN-SCIENTIST-01", "SYN-QUALITY-01"}
        )
        self._lock = RLock()
        self._tenant_id = tenant_id
        self._permitted_actor_ids = permitted_actor_ids
        self._repository = InMemorySpecimenRepository()
        self._outbox = InMemoryOutbox()
        self._custody = CustodyService(self._outbox)
        self._ingress = InstrumentIngress()
        self._gateway = InMemoryVendorGateway("synthetic-benchling")
        self._gateway.fault_mode = FaultMode.TIMEOUT_AFTER_COMMIT
        self._projection = VendorProjectionService(self._gateway)
        self._application = build_reference_golden_specimen_application(
            lifecycle=LifecycleService(self._repository),
            custody=self._custody,
            ingress=self._ingress,
            projection=self._projection,
            tenant_id=tenant_id,
            caller_id=caller_id,
            actor_ids=permitted_actor_ids,
            clock=clock,
        )
        self._instrument_receipts: list[InstrumentReceipt] = []
        self._projections: dict[tuple[str, str], ProjectionOutcome] = {}
        self._observations: dict[tuple[str, str], dict[str, Any]] = {}
        self._completed_runs: dict[
            tuple[str, str], tuple[str, dict[str, Any]]
        ] = {}
        self._resolved_quarantines: set[tuple[str, str]] = set()

    def run_golden_specimen(
        self,
        *,
        run_id: str,
        tenant_id: str,
        specimen_id: str,
        actor_id: str,
        scientist_id: str,
        quality_actor_id: str,
        occurred_at: datetime,
        raw_instrument_json: bytes,
        vendor_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Execute and expose one evidence-bearing specimen journey."""
        _require_identity("run_id", run_id)
        _require_identity("tenant_id", tenant_id)
        _require_identity("specimen_id", specimen_id)
        _require_identity("actor_id", actor_id)
        _require_identity("scientist_id", scientist_id)
        _require_identity("quality_actor_id", quality_actor_id)
        self._authorize_request(
            tenant_id=tenant_id,
            actor_ids=frozenset({actor_id, scientist_id, quality_actor_id}),
        )
        occurred_at = require_aware_utc(occurred_at)
        run_digest = _run_digest(
            mode="initial",
            run_id=run_id,
            tenant_id=tenant_id,
            specimen_id=specimen_id,
            actor_id=actor_id,
            scientist_id=scientist_id,
            quality_actor_id=quality_actor_id,
            occurred_at=occurred_at,
            raw_instrument_json=raw_instrument_json,
            vendor_payload=vendor_payload,
        )
        with self._lock:
            replay = self._completed_run(tenant_id, run_id, run_digest)
            if replay is not None:
                return replay
            try:
                outcome = self._application.process(
                    call_id=run_id,
                    tenant_id=tenant_id,
                    specimen_id=specimen_id,
                    actor_id=actor_id,
                    scientist_id=scientist_id,
                    quality_actor_id=quality_actor_id,
                    occurred_at=occurred_at,
                    raw_instrument_json=raw_instrument_json,
                    vendor_payload=vendor_payload,
                )
            except InstrumentReviewRequired:
                self._record_instrument_receipt(
                    tenant_id=tenant_id,
                    specimen_id=specimen_id,
                    message_id=f"{run_id}:instrument",
                    instrument_id="SYN-INSTRUMENT-01",
                    captured_at=occurred_at,
                )
                raise
            result = self._complete_run(
                outcome=outcome,
                tenant_id=tenant_id,
                specimen_id=specimen_id,
                run_id=run_id,
                actor_id=actor_id,
                reviewer_id=scientist_id,
                captured_at=occurred_at,
            )
            self._completed_runs[(tenant_id, run_id)] = (
                run_digest,
                deepcopy(result),
            )
            return result

    def resume_instrument_review(
        self,
        *,
        recovery_of_run_id: str,
        run_id: str,
        tenant_id: str,
        specimen_id: str,
        actor_id: str,
        scientist_id: str,
        quality_actor_id: str,
        occurred_at: datetime,
        raw_instrument_json: bytes,
        vendor_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Carry corrected instrument evidence from review to release."""
        for name, value in (
            ("recovery_of_run_id", recovery_of_run_id),
            ("run_id", run_id),
            ("tenant_id", tenant_id),
            ("specimen_id", specimen_id),
            ("actor_id", actor_id),
            ("scientist_id", scientist_id),
            ("quality_actor_id", quality_actor_id),
        ):
            _require_identity(name, value)
        self._authorize_request(
            tenant_id=tenant_id,
            actor_ids=frozenset({actor_id, scientist_id, quality_actor_id}),
        )
        if recovery_of_run_id == run_id:
            raise DomainError(
                "instrument recovery requires a new run identity linked to the original run"
            )
        occurred_at = require_aware_utc(occurred_at)
        run_digest = _run_digest(
            mode="instrument_recovery",
            recovery_of_run_id=recovery_of_run_id,
            run_id=run_id,
            tenant_id=tenant_id,
            specimen_id=specimen_id,
            actor_id=actor_id,
            scientist_id=scientist_id,
            quality_actor_id=quality_actor_id,
            occurred_at=occurred_at,
            raw_instrument_json=raw_instrument_json,
            vendor_payload=vendor_payload,
        )
        with self._lock:
            replay = self._completed_run(tenant_id, run_id, run_digest)
            if replay is not None:
                return replay
            original_message = (tenant_id, f"{recovery_of_run_id}:instrument")
            original = next(
                (
                    receipt
                    for receipt in self._instrument_receipts
                    if (receipt.tenant_id, receipt.message_id) == original_message
                    and receipt.disposition == IngressDisposition.QUARANTINED.value
                ),
                None,
            )
            if original is None:
                raise DomainError(
                    f"run {recovery_of_run_id} requires a quarantined instrument receipt"
                )
            if original.specimen_id != specimen_id:
                raise DomainError(
                    f"run {recovery_of_run_id} carries instrument review for specimen "
                    f"{original.specimen_id}; resume that specimen or select its own "
                    "quarantined run"
                )
            if original_message in self._resolved_quarantines:
                raise DomainError(
                    f"run {recovery_of_run_id} already has a completed recovery; "
                    "reuse that recovery result or establish a new review receipt"
                )
            try:
                outcome = self._application.resume_after_instrument_review(
                    recovery_of_call_id=recovery_of_run_id,
                    call_id=run_id,
                    tenant_id=tenant_id,
                    specimen_id=specimen_id,
                    actor_id=actor_id,
                    scientist_id=scientist_id,
                    quality_actor_id=quality_actor_id,
                    occurred_at=occurred_at,
                    raw_instrument_json=raw_instrument_json,
                    vendor_payload=vendor_payload,
                )
            except InstrumentReviewRequired:
                self._record_instrument_receipt(
                    tenant_id=tenant_id,
                    specimen_id=specimen_id,
                    message_id=f"{run_id}:instrument",
                    instrument_id="SYN-INSTRUMENT-01",
                    captured_at=occurred_at,
                )
                raise
            result = self._complete_run(
                outcome=outcome,
                tenant_id=tenant_id,
                specimen_id=specimen_id,
                run_id=run_id,
                actor_id=actor_id,
                reviewer_id=scientist_id,
                captured_at=occurred_at,
            )
            self._resolved_quarantines.add(original_message)
            self._completed_runs[(tenant_id, run_id)] = (
                run_digest,
                deepcopy(result),
            )
            return result

    def _authorize_request(
        self,
        *,
        tenant_id: str,
        actor_ids: frozenset[str],
    ) -> None:
        if tenant_id != self._tenant_id:
            raise DomainError(
                f"tenant {tenant_id} is outside this workbench authority; "
                f"use the {self._tenant_id} encounter or compose a tenant-specific service"
            )
        if not actor_ids.issubset(self._permitted_actor_ids):
            raise DomainError(
                "workbench actors require identities in the configured reference grant"
            )

    def specimen(self, tenant_id: str, specimen_id: str) -> dict[str, Any]:
        _require_identity("tenant_id", tenant_id)
        _require_identity("specimen_id", specimen_id)
        with self._lock:
            aggregate = self._repository.get(tenant_id, specimen_id)
            if aggregate is None:
                raise SpecimenAbsent(
                    f"specimen {specimen_id} is absent from tenant {tenant_id}; "
                    "register it or select an existing specimen"
                )
            return self._view(aggregate).to_document()

    def summary(self, tenant_id: str) -> dict[str, Any]:
        _require_identity("tenant_id", tenant_id)
        with self._lock:
            aggregates = self._repository.list_for_tenant(tenant_id)
            lifecycle = Counter(aggregate.state.value for aggregate in aggregates)
            receipts = [
                receipt
                for receipt in self._instrument_receipts
                if receipt.tenant_id == tenant_id
            ]
            return {
                "tenant_id": tenant_id,
                "specimen_count": len(aggregates),
                "lifecycle_counts": dict(sorted(lifecycle.items())),
                "instrument_receipt_count": len(receipts),
                "quarantine_count": sum(
                    receipt.disposition == IngressDisposition.QUARANTINED.value
                    and (receipt.tenant_id, receipt.message_id)
                    not in self._resolved_quarantines
                    for receipt in receipts
                ),
                "quarantine_history_count": sum(
                    receipt.disposition == IngressDisposition.QUARANTINED.value
                    for receipt in receipts
                ),
                "pending_outbox_count": sum(
                    message.tenant_id == tenant_id for message in self._outbox.messages
                ),
                "shared_contract": {
                    "available": contract_available(),
                    "contract_version": "1.0.0",
                },
                "specimens": [
                    {
                        "specimen_id": item.specimen_id,
                        "state": item.state.value,
                        "version": item.version,
                    }
                    for item in aggregates
                ],
            }

    def observation(self, tenant_id: str, run_id: str) -> dict[str, Any]:
        _require_identity("tenant_id", tenant_id)
        _require_identity("run_id", run_id)
        with self._lock:
            observation = self._observations.get((tenant_id, run_id))
            if observation is None:
                raise ObservationAbsent(
                    f"run {run_id} has no shared observation for tenant {tenant_id}; "
                    "execute the run with the contract package installed"
                )
            return dict(observation)

    def _completed_run(
        self,
        tenant_id: str,
        run_id: str,
        run_digest: str,
    ) -> dict[str, Any] | None:
        prior = self._completed_runs.get((tenant_id, run_id))
        if prior is None:
            return None
        prior_digest, result = prior
        if prior_digest != run_digest:
            raise ContentCollision(
                f"workbench run {run_id} already represents different content; "
                "reuse the original inputs or allocate a new run identity"
            )
        return deepcopy(result)

    def _complete_run(
        self,
        *,
        outcome: GoldenSpecimenOutcome,
        tenant_id: str,
        specimen_id: str,
        run_id: str,
        actor_id: str,
        reviewer_id: str,
        captured_at: datetime,
    ) -> dict[str, Any]:
        self._record_instrument_receipt(
            tenant_id=tenant_id,
            specimen_id=specimen_id,
            message_id=f"{run_id}:instrument",
            instrument_id="SYN-INSTRUMENT-01",
            captured_at=captured_at,
        )
        self._projections[(tenant_id, specimen_id)] = outcome.projection
        specimen = self._view(outcome.aggregate).to_document()
        observation = self._build_observation(
            tenant_id=tenant_id,
            run_id=run_id,
            actor_id=actor_id,
            reviewer_id=reviewer_id,
            specimen=specimen,
        )
        return {
            "run_id": run_id,
            "outcome": _golden_outcome_document(outcome),
            "specimen": specimen,
            "observation": observation,
        }

    def _build_observation(
        self,
        *,
        tenant_id: str,
        run_id: str,
        actor_id: str,
        reviewer_id: str,
        specimen: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        receipt = next(
            (
                item
                for item in reversed(self._instrument_receipts)
                if item.tenant_id == tenant_id
                and item.specimen_id == specimen["specimen_id"]
            ),
            None,
        )
        if receipt is None:
            raise RuntimeError("shared observation requires instrument evidence")
        try:
            observation = build_observation(
                run_id=run_id,
                actor_id=actor_id,
                reviewer_id=reviewer_id,
                raw_sha256=receipt.raw_sha256,
                result=specimen,
            )
        except SharedContractUnavailable:
            return None
        self._observations[(tenant_id, run_id)] = observation
        return observation

    def _record_instrument_receipt(
        self,
        *,
        tenant_id: str,
        specimen_id: str,
        message_id: str,
        instrument_id: str,
        captured_at: datetime,
    ) -> None:
        result = self._ingress.result(tenant_id, message_id)
        if result is None:
            raise RuntimeError("instrument ingress requires a recorded disposition")
        receipt = InstrumentReceipt(
            tenant_id=tenant_id,
            specimen_id=specimen_id,
            message_id=message_id,
            instrument_id=instrument_id,
            disposition=result.disposition.value,
            raw_sha256=result.raw_sha256,
            normalized_observation=result.normalized_observation,
            normalized_digest=result.normalized_digest,
            reason_code=result.reason_code,
            recovery=result.recovery,
            captured_at=captured_at,
        )
        if receipt not in self._instrument_receipts:
            self._instrument_receipts.append(receipt)

    def _view(self, aggregate: SpecimenAggregate) -> SpecimenView:
        identity = (aggregate.tenant_id, aggregate.specimen_id)
        return SpecimenView(
            aggregate=aggregate,
            custody=self._custody.current(*identity),
            instrument_receipts=tuple(
                receipt
                for receipt in self._instrument_receipts
                if (receipt.tenant_id, receipt.specimen_id) == identity
            ),
            projection=self._projections.get(identity),
        )


def _require_identity(name: str, value: str) -> None:
    if not value.strip():
        raise DomainError(f"{name} requires a non-empty value")


def _run_digest(
    *,
    mode: str,
    run_id: str,
    tenant_id: str,
    specimen_id: str,
    actor_id: str,
    scientist_id: str,
    quality_actor_id: str,
    occurred_at: datetime,
    raw_instrument_json: bytes,
    vendor_payload: Mapping[str, Any],
    recovery_of_run_id: str | None = None,
) -> str:
    return canonical_digest(
        {
            "mode": mode,
            "recovery_of_run_id": recovery_of_run_id,
            "run_id": run_id,
            "tenant_id": tenant_id,
            "specimen_id": specimen_id,
            "actor_id": actor_id,
            "scientist_id": scientist_id,
            "quality_actor_id": quality_actor_id,
            "occurred_at": require_aware_utc(occurred_at).isoformat(),
            "raw_instrument_sha256": sha256(raw_instrument_json).hexdigest(),
            "vendor_payload": dict(vendor_payload),
        }
    )


def _event_document(event: DomainEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "aggregate_version": event.aggregate_version,
        "actor_id": event.actor_id,
        "command_id": event.command_id,
        "command_digest": event.command_digest,
        "occurred_at": require_aware_utc(event.occurred_at).isoformat(),
        "payload": dict(event.payload),
        "reason_code": event.reason_code,
    }


def _custody_document(position: CustodyPosition | None) -> dict[str, Any] | None:
    if position is None:
        return None
    return {
        "location": position.location,
        "version": position.version,
        "custodian_id": position.custodian_id,
        "occurred_at": require_aware_utc(position.occurred_at).isoformat(),
    }


def _projection_document(outcome: ProjectionOutcome | None) -> dict[str, Any] | None:
    if outcome is None:
        return None
    return asdict(outcome)


def _golden_outcome_document(outcome: GoldenSpecimenOutcome) -> dict[str, Any]:
    return {
        "lifecycle_state": outcome.aggregate.state.value,
        "lifecycle_version": outcome.aggregate.version,
        "instrument_digest": outcome.instrument_digest,
        "custody_location": outcome.custody_location,
        "call_receipt_id": outcome.call_receipt_id,
        "call_decision": outcome.call_decision,
        "projection": _projection_document(outcome.projection),
    }
