"""Instrument ingress with byte-level provenance and explainable quarantine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
import json

from .model import canonical_digest, require_aware_utc


class IngressDisposition(StrEnum):
    ACCEPTED = "accepted"
    REPLAYED = "replayed"
    QUARANTINED = "quarantined"


@dataclass(frozen=True, slots=True)
class InstrumentEnvelope:
    tenant_id: str
    message_id: str
    instrument_id: str
    specimen_id: str
    captured_at: datetime
    media_type: str
    raw_bytes: bytes

    @property
    def raw_sha256(self) -> str:
        return sha256(self.raw_bytes).hexdigest()


@dataclass(frozen=True, slots=True)
class IngressResult:
    disposition: IngressDisposition
    raw_sha256: str
    normalized_digest: str | None
    reason_code: str | None
    recovery: str


class InstrumentIngress:
    """Accept exact replays and route ambiguous content to a reviewable queue."""

    _SUPPORTED_UNITS = {"ng/uL", "copies/uL"}

    def __init__(self) -> None:
        self._ledger: dict[tuple[str, str], IngressResult] = {}
        self.quarantine: list[tuple[InstrumentEnvelope, IngressResult]] = []

    def ingest(self, envelope: InstrumentEnvelope) -> IngressResult:
        require_aware_utc(envelope.captured_at)
        identity = (envelope.tenant_id, envelope.message_id)
        prior = self._ledger.get(identity)
        if prior is not None:
            if prior.raw_sha256 == envelope.raw_sha256:
                return IngressResult(
                    disposition=IngressDisposition.REPLAYED,
                    raw_sha256=prior.raw_sha256,
                    normalized_digest=prior.normalized_digest,
                    reason_code=prior.reason_code,
                    recovery=(
                        "reuse the original normalized outcome"
                        if prior.normalized_digest is not None
                        else "reuse the original quarantine decision"
                    ),
                )
            return self._quarantine(
                envelope,
                "message_identity_collision",
                "allocate a new source message identity after instrument-side review",
            )
        if envelope.media_type != "application/json":
            return self._quarantine(
                envelope,
                "unsupported_media_type",
                "transcode through the approved JSON instrument profile",
            )
        try:
            payload = json.loads(envelope.raw_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._quarantine(
                envelope,
                "malformed_json",
                "repair the source export and submit it with a new message identity",
            )
        if not isinstance(payload, dict):
            return self._quarantine(
                envelope,
                "invalid_document_shape",
                "supply one JSON object through the approved instrument profile",
            )
        required = {"analyte", "value", "unit"}
        missing = sorted(required.difference(payload))
        if missing:
            return self._quarantine(
                envelope,
                "missing_required_fields",
                f"supply the required fields: {', '.join(missing)}",
            )
        if payload["unit"] not in self._SUPPORTED_UNITS:
            return self._quarantine(
                envelope,
                "unsupported_unit",
                "map the value through an approved unit conversion with scientific review",
            )
        normalized = {
            "tenant_id": envelope.tenant_id,
            "specimen_id": envelope.specimen_id,
            "instrument_id": envelope.instrument_id,
            "captured_at": require_aware_utc(envelope.captured_at).isoformat(),
            "analyte": str(payload["analyte"]).strip().upper(),
            "value": str(payload["value"]),
            "unit": payload["unit"],
            "raw_sha256": envelope.raw_sha256,
        }
        result = IngressResult(
            disposition=IngressDisposition.ACCEPTED,
            raw_sha256=envelope.raw_sha256,
            normalized_digest=canonical_digest(normalized),
            reason_code=None,
            recovery="continue to scientific review",
        )
        self._ledger[identity] = result
        return result

    def _quarantine(
        self, envelope: InstrumentEnvelope, reason_code: str, recovery: str
    ) -> IngressResult:
        result = IngressResult(
            disposition=IngressDisposition.QUARANTINED,
            raw_sha256=envelope.raw_sha256,
            normalized_digest=None,
            reason_code=reason_code,
            recovery=recovery,
        )
        self.quarantine.append((envelope, result))
        self._ledger.setdefault((envelope.tenant_id, envelope.message_id), result)
        return result
