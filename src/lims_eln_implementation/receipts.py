"""Evidence records that bind claims to environments, versions, and owners."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
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
        required = {
            "receipt_id": self.receipt_id,
            "claim_id": self.claim_id,
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
        if not self.version_bindings:
            raise DomainError("receipt requires version bindings for its environment")
        if not self.scenario_ids:
            raise DomainError("receipt requires at least one executed scenario")
        if not self.artifact_digests:
            raise DomainError("receipt requires at least one immutable artifact digest")

    def reaches(self, stage: AssuranceStage) -> bool:
        return _STAGE_ORDER[self.assurance_stage] >= _STAGE_ORDER[stage]

