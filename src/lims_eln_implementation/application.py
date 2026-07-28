"""A small end-to-end slice that composes the independently testable services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from .custody import CustodyService
from .instrument import IngressDisposition, InstrumentEnvelope, InstrumentIngress
from .lifecycle import LifecycleService
from .model import Command, SpecimenAggregate
from .vendors import ProjectionOutcome, VendorProjectionService


@dataclass(frozen=True, slots=True)
class GoldenSpecimenOutcome:
    aggregate: SpecimenAggregate
    instrument_digest: str
    projection: ProjectionOutcome
    custody_location: str


class GoldenSpecimenApplication:
    """Compose one inspectable journey without hiding service boundaries."""

    def __init__(
        self,
        lifecycle: LifecycleService,
        custody: CustodyService,
        ingress: InstrumentIngress,
        projection: VendorProjectionService,
    ) -> None:
        self._lifecycle = lifecycle
        self._custody = custody
        self._ingress = ingress
        self._projection = projection

    def process(
        self,
        *,
        tenant_id: str,
        specimen_id: str,
        actor_id: str,
        occurred_at: datetime,
        raw_instrument_json: bytes,
        vendor_payload: Mapping[str, Any],
    ) -> GoldenSpecimenOutcome:
        aggregate = self._lifecycle.register(
            Command(
                "cmd-register",
                tenant_id,
                specimen_id,
                actor_id,
                "register",
                0,
                occurred_at,
                {"specimen_type": "synthetic_plasma"},
            )
        )
        aggregate = self._lifecycle.transition(
            Command(
                "cmd-accession",
                tenant_id,
                specimen_id,
                actor_id,
                "accession",
                aggregate.version,
                occurred_at,
            )
        )
        position = self._custody.place(
            tenant_id=tenant_id,
            specimen_id=specimen_id,
            location="SYN-LAB-A/RECEIVING",
            custodian_id=actor_id,
            expected_version=0,
            transfer_id="transfer-001",
            occurred_at=occurred_at,
        )
        ingress = self._ingress.ingest(
            InstrumentEnvelope(
                tenant_id=tenant_id,
                message_id="instrument-message-001",
                instrument_id="SYN-INSTRUMENT-01",
                specimen_id=specimen_id,
                captured_at=occurred_at,
                media_type="application/json",
                raw_bytes=raw_instrument_json,
            )
        )
        if ingress.disposition is not IngressDisposition.ACCEPTED:
            raise RuntimeError(f"instrument review required: {ingress.reason_code}")
        assert ingress.normalized_digest is not None
        projection = self._projection.project(
            tenant_id=tenant_id,
            request_id="vendor-request-001",
            external_identity=specimen_id,
            expected_revision=0,
            payload={**dict(vendor_payload), "instrument_digest": ingress.normalized_digest},
        )
        return GoldenSpecimenOutcome(
            aggregate=aggregate,
            instrument_digest=ingress.normalized_digest,
            projection=projection,
            custody_location=position.location,
        )

