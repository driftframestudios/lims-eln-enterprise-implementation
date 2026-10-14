"""Optional adapter from workbench evidence to the shared constellation contract."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from importlib import import_module
import json
from typing import Any, Mapping


EXPECTED_PACKAGE_VERSION = "0.5.0"
EXPECTED_CONTRACT_VERSION = "1.0.0"


class SharedContractUnavailable(RuntimeError):
    """The independently distributed constellation contract awaits installation."""


def build_observation(
    *,
    run_id: str,
    actor_id: str,
    reviewer_id: str,
    raw_sha256: str,
    result: Mapping[str, Any],
    state_adapter: str = "process_local",
    governed_locator: str | None = None,
    configuration_detail: Mapping[str, Any] | None = None,
    producer_detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and serialize one typed Golden Specimen observation."""
    contracts = _contracts_module()
    observation_suffix = sha256(run_id.encode("utf-8")).hexdigest()[:16].upper()
    projection, observation_detail = _golden_result(
        contracts=contracts,
        raw_sha256=raw_sha256,
        specimen=result,
        state_adapter=state_adapter,
        configuration_detail=configuration_detail,
    )
    overlap = set(observation_detail).intersection(producer_detail or {})
    if overlap:
        raise ValueError(
            "Golden Specimen producer detail requires distinct extension fields: "
            + ", ".join(sorted(overlap))
        )
    observation_detail.update(dict(producer_detail or {}))
    observation_result = contracts.GoldenSpecimenObservationResult(
        projection=projection,
        producer_detail=observation_detail,
    )
    observation = contracts.GoldenSpecimenObservation(
        observation_id=f"OBS-WORKBENCH-{observation_suffix}",
        evidence_mode=contracts.EvidenceMode.SIMULATED,
        assurance_stage=contracts.AssuranceStage.VERIFIED,
        scenario_id=contracts.GOLDEN_SPECIMEN_SCENARIO_ID,
        scenario_version=contracts.GOLDEN_SPECIMEN_SCENARIO_VERSION,
        scenario_digest=contracts.GOLDEN_SPECIMEN_SCENARIO_DIGEST,
        source=contracts.EvidenceSource(
            environment_id="WORKBENCH-SYNTHETIC",
            implementation_commit="lims-eln-enterprise-implementation@0.3.2",
            configuration_digest=contracts.canonical_sha256(
                observation_detail["configuration"]
            ),
        ),
        result=observation_result,
        provenance=contracts.EvidenceProvenance(
            raw_artifact_digest=f"sha256:{raw_sha256}",
            governed_locator=governed_locator or f"memory://workbench/{run_id}",
            performed_by=actor_id,
            reviewed_by=reviewer_id,
        ),
        classification=contracts.ObservationClassification(
            data_class=contracts.ObservationDataClass.APPROVED_SYNTHETIC_EXEMPLAR,
            redaction_status=contracts.RedactionStatus.GENERATED_IDENTITIES,
        ),
    )
    return observation.model_dump(mode="json")


def _golden_result(
    *,
    contracts: Any,
    raw_sha256: str,
    specimen: Mapping[str, Any],
    state_adapter: str,
    configuration_detail: Mapping[str, Any] | None,
) -> tuple[Any, dict[str, Any]]:
    lifecycle_events = _required_sequence(specimen, "events")
    review_event = _event(lifecycle_events, "specimen.submit_review")
    release_event = _event(lifecycle_events, "specimen.release")
    review_payload = _required_mapping(review_event, "payload")
    release_payload = _required_mapping(release_event, "payload")
    custody = _required_mapping(specimen, "custody")
    receipts = _required_sequence(specimen, "instrument_receipts")
    receipt = _latest_accepted_receipt(receipts)
    if _required_text(receipt, "raw_sha256") != raw_sha256:
        raise ValueError(
            "Golden Specimen result requires the selected receipt raw digest"
        )
    measurement = _required_mapping(receipt, "normalized_observation")
    vendor_projection = _required_mapping(specimen, "projection")
    configuration = {
        "contract_version": EXPECTED_CONTRACT_VERSION,
        "state_adapter": state_adapter,
        "vendor_gateway": _required_text(vendor_projection, "vendor_name"),
        **dict(configuration_detail or {}),
    }
    projection_document = {
        "projection_id": contracts.GOLDEN_SPECIMEN_RESULT_PROJECTION_ID,
        "projection_version": contracts.GOLDEN_SPECIMEN_RESULT_PROJECTION_VERSION,
        "comparison_compatibility": contracts.GOLDEN_SPECIMEN_RESULT_COMPATIBILITY,
        "tenant_id": _required_text(specimen, "tenant_id"),
        "specimen_id": _required_text(specimen, "specimen_id"),
        "lifecycle": {
            "state": _required_text(specimen, "state"),
            "aggregate_version": _required_int(specimen, "version"),
        },
        "custody": {"current_location": _required_text(custody, "location")},
        "measurement": {
            "analyte": _required_text(measurement, "analyte"),
            "value": float(_required_text(measurement, "value")),
            "unit": _required_text(measurement, "unit"),
            "quality_flag": _required_text(review_payload, "quality_flag"),
        },
        "review_resolution": {
            "review_id": _required_text(review_payload, "review_id"),
            "decision": _required_text(review_payload, "decision"),
            "resolved_at": _utc_timestamp(
                _required_text(review_event, "occurred_at")
            ),
        },
        "release": {
            "approval_receipt_id": _required_text(
                release_payload,
                "approval_receipt_id",
            ),
            "released_at": _utc_timestamp(
                _required_text(release_event, "occurred_at")
            ),
        },
    }
    projection = contracts.model_from_strict_json(
        contracts.GoldenSpecimenResultProjection,
        json.dumps(
            projection_document,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
    )
    producer_detail = {
        "configuration": configuration,
        "instrument_message_id": _required_text(receipt, "message_id"),
        "instrument_raw_digest": f"sha256:{raw_sha256}",
        "normalized_measurement_digest": (
            "sha256:" + _required_text(receipt, "normalized_digest")
        ),
        "vendor_projection": dict(vendor_projection),
        "lifecycle_event_ids": [
            _required_text(event, "event_id") for event in lifecycle_events
        ],
    }
    return projection, producer_detail


def _event(events: tuple[Mapping[str, Any], ...], event_type: str) -> Mapping[str, Any]:
    matches = [event for event in events if event.get("event_type") == event_type]
    if len(matches) != 1:
        raise ValueError(f"Golden Specimen result requires one {event_type} event")
    return matches[0]


def _latest_accepted_receipt(
    receipts: tuple[Mapping[str, Any], ...],
) -> Mapping[str, Any]:
    matches = [
        receipt
        for receipt in receipts
        if receipt.get("disposition") in {"accepted", "replayed"}
        and isinstance(receipt.get("normalized_observation"), Mapping)
    ]
    if not matches:
        raise ValueError("Golden Specimen result requires an accepted instrument receipt")
    return matches[-1]


def _required_mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    nested = value.get(key)
    if not isinstance(nested, Mapping):
        raise ValueError(f"Golden Specimen result requires object field {key}")
    return nested


def _required_sequence(
    value: Mapping[str, Any], key: str
) -> tuple[Mapping[str, Any], ...]:
    nested = value.get(key)
    if not isinstance(nested, (list, tuple)) or not nested:
        raise ValueError(f"Golden Specimen result requires populated array field {key}")
    if any(not isinstance(item, Mapping) for item in nested):
        raise ValueError(f"Golden Specimen result requires object members in {key}")
    return tuple(nested)


def _required_text(value: Mapping[str, Any], key: str) -> str:
    nested = value.get(key)
    if not isinstance(nested, str) or not nested.strip():
        raise ValueError(f"Golden Specimen result requires text field {key}")
    return nested


def _required_int(value: Mapping[str, Any], key: str) -> int:
    nested = value.get(key)
    if isinstance(nested, bool) or not isinstance(nested, int):
        raise ValueError(f"Golden Specimen result requires integer field {key}")
    return nested


def _utc_timestamp(value: str) -> str:
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("Golden Specimen timestamps require explicit UTC offsets")
    return instant.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def contract_available() -> bool:
    try:
        _contracts_module()
    except SharedContractUnavailable:
        return False
    return True


def _contracts_module() -> Any:
    try:
        contracts = import_module("lims_eln_contracts")
    except ModuleNotFoundError as error:
        raise SharedContractUnavailable(
            "shared observation generation requires "
            "lims-eln-program-specification 0.5.0; install the released contract "
            "package for the integrated constellation encounter"
        ) from error
    package_version = getattr(contracts, "__version__", "unversioned")
    if package_version != EXPECTED_PACKAGE_VERSION:
        raise SharedContractUnavailable(
            f"workbench expects shared package {EXPECTED_PACKAGE_VERSION}; "
            f"installed package exposes {package_version}"
        )
    contract_version = getattr(contracts, "CONTRACT_VERSION", "unversioned")
    if contract_version != EXPECTED_CONTRACT_VERSION:
        raise SharedContractUnavailable(
            f"workbench expects contract {EXPECTED_CONTRACT_VERSION}; "
            f"installed package exposes {contract_version}"
        )
    return contracts


def validate_observation_bytes(payload: bytes, *, tenant_id: str, run_id: str) -> None:
    """Validate the existing envelope and its requested workbench identity."""
    for identity in (tenant_id, run_id):
        if (
            not isinstance(identity, str) or not 3 <= len(identity) <= 128
            or not identity.isascii() or not identity[0].isalnum()
            or not identity[-1].isalnum()
            or any(not (character.isalnum() or character in "._:@/-") for character in identity)
        ):
            raise ValueError("observation identity requires the workbench identifier grammar")
    contracts = _contracts_module()
    observation = contracts.model_from_strict_json(
        contracts.GoldenSpecimenObservation, payload.decode("utf-8")
    )
    expected_id = "OBS-WORKBENCH-" + sha256(run_id.encode("utf-8")).hexdigest()[:16].upper()
    if (
        observation.observation_id != expected_id
        or observation.result.projection.tenant_id != tenant_id
        or observation.scenario_coordinate() != (
            contracts.GOLDEN_SPECIMEN_SCENARIO_ID,
            contracts.GOLDEN_SPECIMEN_SCENARIO_VERSION,
            contracts.GOLDEN_SPECIMEN_SCENARIO_DIGEST,
        )
    ):
        raise ValueError("observation requires the requested run, tenant, and scenario")
