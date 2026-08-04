"""Direct composition for the inspectable specimen journey."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .custody import CustodyService
from .instrument import IngressDisposition, InstrumentEnvelope, InstrumentIngress
from .lifecycle import LifecycleService
from .model import Command, SpecimenAggregate, require_aware_utc
from .vendors import ProjectionOutcome, VendorProjectionService


@dataclass(frozen=True, slots=True)
class GoldenSpecimenOutcome:
    """Material outcomes produced by one specimen-processing request."""

    aggregate: SpecimenAggregate
    instrument_digest: str
    projection: ProjectionOutcome
    custody_location: str


class GoldenSpecimenApplication:
    """Compose domain services without inventing a second authorization plane.

    Authentication and authorization belong at the deployment boundary. This
    service receives an already-authenticated actor and preserves that identity
    in lifecycle and custody records.
    """

    def __init__(
        self,
        *,
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
        call_id: str,
        tenant_id: str,
        specimen_id: str,
        actor_id: str,
        occurred_at: datetime,
        raw_instrument_json: bytes,
        vendor_payload: Mapping[str, Any],
    ) -> GoldenSpecimenOutcome:
        for name, value in (
            ("call_id", call_id),
            ("tenant_id", tenant_id),
            ("specimen_id", specimen_id),
            ("actor_id", actor_id),
        ):
            if not value.strip():
                raise ValueError(f"{name} requires a populated value")
        requested_at = require_aware_utc(occurred_at)

        aggregate = self._lifecycle.register(
            _command(
                call_id=call_id,
                tenant_id=tenant_id,
                specimen_id=specimen_id,
                actor_id=actor_id,
                occurred_at=requested_at,
                suffix="register",
                action="register",
                expected_version=0,
                payload={"specimen_type": "synthetic_plasma"},
            )
        )
        aggregate = self._lifecycle.transition(
            _command(
                call_id=call_id,
                tenant_id=tenant_id,
                specimen_id=specimen_id,
                actor_id=actor_id,
                occurred_at=requested_at,
                suffix="accession",
                action="accession",
                expected_version=aggregate.version,
            )
        )
        position = self._custody.place(
            tenant_id=tenant_id,
            specimen_id=specimen_id,
            location="SYN-LAB-A/RECEIVING",
            custodian_id=actor_id,
            expected_version=0,
            transfer_id=f"{call_id}:custody",
            occurred_at=requested_at,
        )
        ingress = self._ingress.ingest(
            InstrumentEnvelope(
                tenant_id=tenant_id,
                message_id=f"{call_id}:instrument",
                instrument_id="SYN-INSTRUMENT-01",
                specimen_id=specimen_id,
                captured_at=requested_at,
                media_type="application/json",
                raw_bytes=raw_instrument_json,
            )
        )
        if ingress.disposition is not IngressDisposition.ACCEPTED:
            raise RuntimeError(f"instrument review required: {ingress.reason_code}")
        assert ingress.normalized_digest is not None
        projection = self._projection.project(
            tenant_id=tenant_id,
            request_id=f"{call_id}:vendor",
            external_identity=specimen_id,
            expected_revision=0,
            payload={
                **dict(vendor_payload),
                "instrument_digest": ingress.normalized_digest,
            },
        )
        return GoldenSpecimenOutcome(
            aggregate=aggregate,
            instrument_digest=ingress.normalized_digest,
            projection=projection,
            custody_location=position.location,
        )


def build_reference_golden_specimen_application(
    *,
    lifecycle: LifecycleService,
    custody: CustodyService,
    ingress: InstrumentIngress,
    projection: VendorProjectionService,
) -> GoldenSpecimenApplication:
    """Build the direct reference service from explicit domain dependencies."""

    return GoldenSpecimenApplication(
        lifecycle=lifecycle,
        custody=custody,
        ingress=ingress,
        projection=projection,
    )


def _command(
    *,
    call_id: str,
    tenant_id: str,
    specimen_id: str,
    actor_id: str,
    occurred_at: datetime,
    suffix: str,
    action: str,
    expected_version: int,
    payload: Mapping[str, Any] | None = None,
) -> Command:
    return Command(
        command_id=f"{call_id}:{suffix}",
        tenant_id=tenant_id,
        specimen_id=specimen_id,
        actor_id=actor_id,
        action=action,
        expected_version=expected_version,
        occurred_at=occurred_at,
        payload=dict(payload or {}),
    )
