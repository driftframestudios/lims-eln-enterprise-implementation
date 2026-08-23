"""Instrument ingress with byte-level provenance and explainable quarantine."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
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
class NormalizedObservation:
    """Readable projection beside the released precision-bearing document."""

    tenant_id: str
    specimen_id: str
    instrument_id: str
    captured_at: datetime
    analyte: str
    value: str
    unit: str
    raw_sha256: str

    def to_document(self) -> dict[str, str]:
        return {
            "tenant_id": self.tenant_id,
            "specimen_id": self.specimen_id,
            "instrument_id": self.instrument_id,
            "captured_at": require_aware_utc(self.captured_at).isoformat(),
            "analyte": self.analyte,
            "value": self.value,
            "unit": self.unit,
            "raw_sha256": self.raw_sha256,
        }


@dataclass(frozen=True, slots=True)
class IngressResult:
    disposition: IngressDisposition
    raw_sha256: str
    normalized_digest: str | None
    normalized_document_json: str | None
    normalized_observation: NormalizedObservation | None
    reason_code: str | None
    recovery: str


class DuplicateJsonMember(ValueError):
    """A JSON object repeated a member whose winning value would be ambiguous."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise DuplicateJsonMember(key)
        document[key] = value
    return document


def _reject_nonfinite_constant(value: str) -> object:
    raise ValueError(f"JSON numeric constant {value!r} requires finite decimal content")


class InstrumentIngress:
    """Accept exact replays and route ambiguous content to a reviewable queue."""

    _MAX_PAYLOAD_BYTES = 1024 * 1024
    _RELEASED_FIELDS = frozenset({"analyte", "value", "unit"})
    _UNIT_PROFILE = {
        "ng/uL": ("ng/uL", "http://unitsofmeasure.org"),
        "copies/uL": ("{copies}/uL", "http://unitsofmeasure.org"),
        "{copies}/uL": ("{copies}/uL", "http://unitsofmeasure.org"),
    }

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
                    normalized_document_json=prior.normalized_document_json,
                    normalized_observation=prior.normalized_observation,
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
        if len(envelope.raw_bytes) > self._MAX_PAYLOAD_BYTES:
            return self._quarantine(
                envelope,
                "payload_limit_exceeded",
                "store the source artifact and submit one bounded measurement document",
            )
        try:
            payload = json.loads(
                envelope.raw_bytes,
                parse_float=Decimal,
                parse_int=Decimal,
                parse_constant=_reject_nonfinite_constant,
                object_pairs_hook=_unique_object,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, DuplicateJsonMember, ValueError):
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
        missing = sorted(self._RELEASED_FIELDS.difference(payload))
        if missing:
            return self._quarantine(
                envelope,
                "missing_required_fields",
                f"supply the required fields: {', '.join(missing)}",
            )
        additional = sorted(set(payload).difference(self._RELEASED_FIELDS))
        if additional:
            return self._quarantine(
                envelope,
                "unreleased_fields",
                "map additional fields through a versioned instrument profile: "
                + ", ".join(additional),
            )
        analyte = payload["analyte"]
        if not isinstance(analyte, str) or not analyte.strip() or len(analyte) > 128:
            return self._quarantine(
                envelope,
                "analyte_requires_mapping",
                "supply a 1..128 character analyte code from the approved profile",
            )
        unit = payload["unit"]
        if not isinstance(unit, str) or unit not in self._UNIT_PROFILE:
            return self._quarantine(
                envelope,
                "unsupported_unit",
                "map the value through an approved unit conversion with scientific review",
            )
        raw_value = payload["value"]
        if isinstance(raw_value, bool) or not isinstance(raw_value, (str, Decimal)):
            return self._quarantine(
                envelope,
                "quantity_requires_mapping",
                "supply a finite decimal number or decimal string from the approved profile",
            )
        try:
            quantity = Decimal(raw_value.strip()) if isinstance(raw_value, str) else raw_value
        except (InvalidOperation, ValueError):
            return self._quarantine(
                envelope,
                "quantity_requires_mapping",
                "supply a finite decimal number or decimal string from the approved profile",
            )
        if not quantity.is_finite():
            return self._quarantine(
                envelope,
                "quantity_requires_mapping",
                "supply a finite decimal quantity from the approved profile",
            )
        quantity_tuple = quantity.as_tuple()
        precision = len(quantity_tuple.digits)
        scale = max(-quantity_tuple.exponent, 0)
        integer_digits = max(precision + quantity_tuple.exponent, 0)
        if precision > 38 or scale > 18 or integer_digits > 20:
            return self._quarantine(
                envelope,
                "quantity_precision_exceeded",
                "route the measurement through a reviewed profile with a wider decimal model",
            )
        unit_code, unit_system = self._UNIT_PROFILE[unit]
        normalized = {
            "tenant_id": envelope.tenant_id,
            "specimen_id": envelope.specimen_id,
            "instrument_id": envelope.instrument_id,
            "captured_at": require_aware_utc(envelope.captured_at).isoformat(),
            "analyte": analyte.strip().upper(),
            "quantity": {
                "decimal": format(quantity, "f"),
                "precision": precision,
                "scale": scale,
                "unit_code": unit_code,
                "unit_system": unit_system,
            },
            "raw_sha256": envelope.raw_sha256,
        }
        normalized_document_json = json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        result = IngressResult(
            disposition=IngressDisposition.ACCEPTED,
            raw_sha256=envelope.raw_sha256,
            normalized_digest=canonical_digest(normalized),
            normalized_document_json=normalized_document_json,
            normalized_observation=NormalizedObservation(
                tenant_id=envelope.tenant_id,
                specimen_id=envelope.specimen_id,
                instrument_id=envelope.instrument_id,
                captured_at=envelope.captured_at,
                analyte=analyte.strip().upper(),
                value=format(quantity, "f"),
                unit=unit_code,
                raw_sha256=envelope.raw_sha256,
            ),
            reason_code=None,
            recovery="continue to scientific review",
        )
        self._ledger[identity] = result
        return result

    def result(self, tenant_id: str, message_id: str) -> IngressResult | None:
        """Return the first recorded disposition for one source identity."""

        return self._ledger.get((tenant_id, message_id))

    def _quarantine(
        self, envelope: InstrumentEnvelope, reason_code: str, recovery: str
    ) -> IngressResult:
        result = IngressResult(
            disposition=IngressDisposition.QUARANTINED,
            raw_sha256=envelope.raw_sha256,
            normalized_digest=None,
            normalized_document_json=None,
            normalized_observation=None,
            reason_code=reason_code,
            recovery=recovery,
        )
        self.quarantine.append((envelope, result))
        self._ledger.setdefault((envelope.tenant_id, envelope.message_id), result)
        return result
