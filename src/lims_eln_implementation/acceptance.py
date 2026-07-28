"""Separate, accountable scientific, Quality, and Regulatory decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Iterable

from .model import DomainError, require_aware_utc
from .receipts import AssuranceStage, EvidenceMode, EvidenceReceipt


class AcceptanceDomain(StrEnum):
    SCIENTIFIC = "scientific"
    QUALITY = "quality"
    REGULATORY = "regulatory"


@dataclass(frozen=True, slots=True)
class AcceptanceDecision:
    domain: AcceptanceDomain
    approver_id: str
    role: str
    decision: str
    intended_use_id: str
    receipt_ids: tuple[str, ...]
    residual_risk: str
    decided_at: datetime

    def __post_init__(self) -> None:
        require_aware_utc(self.decided_at)
        if self.decision not in {"approve", "approve_with_conditions", "return_for_evidence"}:
            raise DomainError("decision requires an approved acceptance vocabulary")
        if not self.approver_id.strip() or not self.role.strip():
            raise DomainError("acceptance requires a named approver and accountable role")


@dataclass(frozen=True, slots=True)
class AcceptanceStatus:
    ready: bool
    accepted_domains: frozenset[AcceptanceDomain]
    pending_domains: frozenset[AcceptanceDomain]
    decision_ids: tuple[str, ...]


class AcceptanceBoard:
    REQUIRED = frozenset(AcceptanceDomain)

    def evaluate(
        self,
        receipts: Iterable[EvidenceReceipt],
        decisions: Iterable[AcceptanceDecision],
    ) -> AcceptanceStatus:
        receipt_map = {receipt.receipt_id: receipt for receipt in receipts}
        accepted: set[AcceptanceDomain] = set()
        decision_ids: list[str] = []
        for decision in decisions:
            if decision.decision not in {"approve", "approve_with_conditions"}:
                continue
            bound = [receipt_map.get(receipt_id) for receipt_id in decision.receipt_ids]
            if not bound or any(item is None for item in bound):
                continue
            # SAFETY: accountable acceptance is grounded in observed, validated
            # evidence; planned or simulated material returns to evidence gathering.
            if any(
                receipt.evidence_mode is not EvidenceMode.OBSERVED
                or not receipt.reaches(AssuranceStage.VALIDATED)
                for receipt in bound
                if receipt is not None
            ):
                continue
            accepted.add(decision.domain)
            decision_ids.append(f"{decision.domain}:{decision.approver_id}")
        pending = self.REQUIRED.difference(accepted)
        return AcceptanceStatus(
            ready=not pending,
            accepted_domains=frozenset(accepted),
            pending_domains=frozenset(pending),
            decision_ids=tuple(sorted(decision_ids)),
        )

