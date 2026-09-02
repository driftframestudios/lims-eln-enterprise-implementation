"""Separate, accountable scientific, Quality, and Regulatory decisions."""

from __future__ import annotations

from collections import Counter
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
    release_claim_id: str
    receipt_ids: tuple[str, ...]
    residual_risk: str
    decided_at: datetime

    def __post_init__(self) -> None:
        require_aware_utc(self.decided_at)
        receipt_ids = tuple(self.receipt_ids)
        object.__setattr__(self, "receipt_ids", receipt_ids)
        if self.decision not in {"approve", "approve_with_conditions", "return_for_evidence"}:
            raise DomainError("decision requires an approved acceptance vocabulary")
        required = {
            "approver_id": self.approver_id,
            "role": self.role,
            "intended_use_id": self.intended_use_id,
            "release_claim_id": self.release_claim_id,
            "residual_risk": self.residual_risk,
        }
        empty = sorted(name for name, value in required.items() if not value.strip())
        if empty:
            raise DomainError(
                f"acceptance fields require values: {', '.join(empty)}"
            )
        if (
            not receipt_ids
            or any(
                not isinstance(receipt_id, str) or not receipt_id.strip()
                for receipt_id in receipt_ids
            )
            or len(set(receipt_ids)) != len(receipt_ids)
        ):
            raise DomainError(
                "acceptance requires unique receipt identities for its evidence bundle"
            )


@dataclass(frozen=True, slots=True)
class AcceptanceStatus:
    ready: bool
    accepted_domains: frozenset[AcceptanceDomain]
    pending_domains: frozenset[AcceptanceDomain]
    decision_ids: tuple[str, ...]
    intended_use_id: str | None
    release_claim_id: str | None


class AcceptanceBoard:
    REQUIRED = frozenset(AcceptanceDomain)

    def evaluate(
        self,
        receipts: Iterable[EvidenceReceipt],
        decisions: Iterable[AcceptanceDecision],
    ) -> AcceptanceStatus:
        receipt_items = tuple(receipts)
        receipt_map = {receipt.receipt_id: receipt for receipt in receipt_items}
        if len(receipt_map) != len(receipt_items):
            raise DomainError("acceptance evidence receipt identities require uniqueness")
        decision_items = tuple(decisions)
        intended_uses = {decision.intended_use_id for decision in decision_items}
        release_claims = {decision.release_claim_id for decision in decision_items}
        intended_use_id = next(iter(intended_uses)) if len(intended_uses) == 1 else None
        release_claim_id = (
            next(iter(release_claims)) if len(release_claims) == 1 else None
        )
        eligible: dict[AcceptanceDomain, list[AcceptanceDecision]] = {
            domain: [] for domain in self.REQUIRED
        }
        for decision in decision_items:
            if decision.decision not in {"approve", "approve_with_conditions"}:
                continue
            if (
                intended_use_id is None
                or release_claim_id is None
                or decision.intended_use_id != intended_use_id
                or decision.release_claim_id != release_claim_id
            ):
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
            if any(
                receipt.intended_use_id != intended_use_id
                or receipt.release_claim_id != release_claim_id
                for receipt in bound
                if receipt is not None
            ):
                continue
            eligible[decision.domain].append(decision)
        selected = {
            domain: items[0]
            for domain, items in eligible.items()
            if len(items) == 1
        }
        approver_counts = Counter(
            decision.approver_id for decision in selected.values()
        )
        accepted = {
            domain
            for domain, decision in selected.items()
            if approver_counts[decision.approver_id] == 1
        }
        decision_ids = [
            f"{domain}:{selected[domain].approver_id}" for domain in accepted
        ]
        pending = self.REQUIRED.difference(accepted)
        return AcceptanceStatus(
            ready=not pending,
            accepted_domains=frozenset(accepted),
            pending_domains=frozenset(pending),
            decision_ids=tuple(sorted(decision_ids)),
            intended_use_id=intended_use_id,
            release_claim_id=release_claim_id,
        )
