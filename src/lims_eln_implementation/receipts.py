"""Evidence records that bind claims to environments, versions, and owners."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import re
from types import MappingProxyType
from typing import Mapping

from .model import DomainError, require_aware_utc


class EvidenceMode(StrEnum):
    PLANNED = "planned"
    SIMULATED = "simulated"
    OBSERVED = "observed"


class AssuranceStage(StrEnum):
    SPECIFIED = "specified"
    VERIFIED = "verified"
    QUALIFIED = "qualified"
    VALIDATED = "validated"
    ACCEPTED = "accepted"


_STAGE_ORDER = {
    AssuranceStage.SPECIFIED: 0,
    AssuranceStage.VERIFIED: 1,
    AssuranceStage.QUALIFIED: 2,
    AssuranceStage.VALIDATED: 3,
    AssuranceStage.ACCEPTED: 4,
}


@dataclass(frozen=True, slots=True)
class EvidenceReceipt:
    receipt_id: str
    claim_id: str
    intended_use_id: str
    release_claim_id: str
    evidence_mode: EvidenceMode
    assurance_stage: AssuranceStage
    environment: str
    version_bindings: Mapping[str, str]
    scenario_ids: tuple[str, ...]
    artifact_digests: tuple[str, ...]
    observed_at: datetime
    performer_id: str
    reviewer_id: str
    limitations: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        require_aware_utc(self.observed_at)
        bindings = MappingProxyType(dict(self.version_bindings))
        scenario_ids = tuple(self.scenario_ids)
        artifact_digests = tuple(self.artifact_digests)
        limitations = tuple(self.limitations)
        object.__setattr__(self, "version_bindings", bindings)
        object.__setattr__(self, "scenario_ids", scenario_ids)
        object.__setattr__(self, "artifact_digests", artifact_digests)
        object.__setattr__(self, "limitations", limitations)
        required = {
            "receipt_id": self.receipt_id,
            "claim_id": self.claim_id,
            "intended_use_id": self.intended_use_id,
            "release_claim_id": self.release_claim_id,
            "environment": self.environment,
            "performer_id": self.performer_id,
            "reviewer_id": self.reviewer_id,
        }
        empty = sorted(key for key, value in required.items() if not value.strip())
        if empty:
            raise DomainError(f"receipt fields require values: {', '.join(empty)}")
        if self.performer_id == self.reviewer_id:
            raise DomainError(
                "receipt review requires a second accountable identity; "
                "assign an independent reviewer"
            )
        if not bindings or any(
            not isinstance(key, str)
            or not key.strip()
            or not isinstance(value, str)
            or not value.strip()
            for key, value in bindings.items()
        ):
            raise DomainError("receipt requires version bindings for its environment")
        if (
            not scenario_ids
            or any(
                not isinstance(scenario_id, str) or not scenario_id.strip()
                for scenario_id in scenario_ids
            )
            or len(set(scenario_ids)) != len(scenario_ids)
        ):
            raise DomainError("receipt requires at least one executed scenario")
        if not artifact_digests or any(
            not isinstance(digest, str)
            or re.fullmatch(r"sha256:[a-f0-9]{64}", digest) is None
            for digest in artifact_digests
        ):
            raise DomainError("receipt requires at least one immutable artifact digest")
        if len(set(artifact_digests)) != len(artifact_digests):
            raise DomainError("receipt artifact digests require uniqueness")
        if any(
            not isinstance(limitation, str) or not limitation.strip()
            for limitation in limitations
        ):
            raise DomainError("receipt limitations require populated text")

    def reaches(self, stage: AssuranceStage) -> bool:
        return _STAGE_ORDER[self.assurance_stage] >= _STAGE_ORDER[stage]
