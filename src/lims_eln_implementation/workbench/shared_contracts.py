"""Optional adapter from workbench evidence to the shared constellation contract."""

from __future__ import annotations

from hashlib import sha256
from importlib import import_module
from typing import Any, Mapping

from ..model import canonical_digest


EXPECTED_PACKAGE_VERSION = "0.3.1"
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
) -> dict[str, Any]:
    """Validate and serialize one simulated workbench observation."""
    contracts = _contracts_module()
    observation_suffix = sha256(run_id.encode("utf-8")).hexdigest()[:16].upper()
    observation = contracts.ObservationEnvelope(
        observation_id=f"OBS-WORKBENCH-{observation_suffix}",
        evidence_mode=contracts.EvidenceMode.SIMULATED,
        assurance_stage=contracts.AssuranceStage.VERIFIED,
        scenario_id="SCN-GOLDEN-SPECIMEN-001",
        source=contracts.EvidenceSource(
            environment_id="WORKBENCH-SYNTHETIC",
            implementation_commit="lims-eln-enterprise-implementation@0.3.1",
            configuration_digest=(
                "sha256:"
                + canonical_digest(
                    {
                        "state_adapter": "process_local",
                        "vendor_gateway": "synthetic-benchling",
                        "contract_version": EXPECTED_CONTRACT_VERSION,
                    }
                )
            ),
        ),
        result=dict(result),
        provenance=contracts.EvidenceProvenance(
            raw_artifact_digest=f"sha256:{raw_sha256}",
            governed_locator=f"memory://workbench/{run_id}",
            performed_by=actor_id,
            reviewed_by=reviewer_id,
        ),
        classification=contracts.ObservationClassification(
            data_class=contracts.ObservationDataClass.APPROVED_SYNTHETIC_EXEMPLAR,
            redaction_status=contracts.RedactionStatus.GENERATED_IDENTITIES,
        ),
    )
    return observation.model_dump(mode="json")


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
            "lims-eln-program-specification 0.3.1; install the released contract "
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
