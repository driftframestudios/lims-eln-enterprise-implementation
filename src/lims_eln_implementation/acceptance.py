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
    decision_id: str
    approver_id: str
    role: str
    decision: str
    intended_use_id: str
    release_claim_id: str
    receipt_ids: tuple[str, ...]
    residual_risk: str
    decided_at: datetime
    condition_summary: str | None = None
    condition_owner_id: str | None = None
    condition_due_at: datetime | None = None
    supersedes_decision_id: str | None = None
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        require_aware_utc(self.decided_at)
        if self.condition_due_at is not None:
            require_aware_utc(self.condition_due_at)
        if self.expires_at is not None:
            require_aware_utc(self.expires_at)
        receipt_ids = tuple(self.receipt_ids)
        object.__setattr__(self, "receipt_ids", receipt_ids)
        if self.decision not in {"approve", "approve_with_conditions", "return_for_evidence"}:
            raise DomainError("decision requires an approved acceptance vocabulary")
        required = {
            "decision_id": self.decision_id,
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
        if self.supersedes_decision_id is not None:
            if not self.supersedes_decision_id.strip():
                raise DomainError("superseded decision identity requires a value")
            if self.supersedes_decision_id == self.decision_id:
                raise DomainError("an acceptance decision requires a prior decision to supersede")
        condition_values = (
            self.condition_summary,
            self.condition_owner_id,
            self.condition_due_at,
        )
        if self.decision == "approve_with_conditions":
            if any(value is None for value in condition_values):
                raise DomainError(
                    "conditional acceptance requires its condition, owner, and due instant"
                )
            assert self.condition_summary is not None
            assert self.condition_owner_id is not None
            assert self.condition_due_at is not None
            if not self.condition_summary.strip() or not self.condition_owner_id.strip():
                raise DomainError(
                    "conditional acceptance requires its condition and owner values"
                )
            if self.condition_due_at <= self.decided_at:
                raise DomainError("conditional acceptance requires a future due instant")
        elif any(value is not None for value in condition_values):
            raise DomainError(
                "condition fields belong to an approve_with_conditions decision"
            )
        if self.expires_at is not None and self.expires_at <= self.decided_at:
            raise DomainError("acceptance expiry requires an instant after the decision")
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
    conditional_domains: frozenset[AcceptanceDomain]
    ambiguous_domains: frozenset[AcceptanceDomain]
    decision_ids: tuple[str, ...]
    intended_use_id: str | None
    release_claim_id: str | None


class AcceptanceBoard:
    REQUIRED = frozenset(AcceptanceDomain)

    def evaluate(
        self,
        receipts: Iterable[EvidenceReceipt],
        decisions: Iterable[AcceptanceDecision],
        *,
        evaluated_at: datetime,
    ) -> AcceptanceStatus:
        require_aware_utc(evaluated_at)
        receipt_items = tuple(receipts)
        receipt_map = {receipt.receipt_id: receipt for receipt in receipt_items}
        if len(receipt_map) != len(receipt_items):
            raise DomainError("acceptance evidence receipt identities require uniqueness")
        decision_items = tuple(decisions)
        decision_map = {decision.decision_id: decision for decision in decision_items}
        if len(decision_map) != len(decision_items):
            raise DomainError("acceptance decision identities require uniqueness")
        superseded_ids: set[str] = set()
        for decision in decision_items:
            prior_id = decision.supersedes_decision_id
            if prior_id is None:
                continue
            prior = decision_map.get(prior_id)
            if prior is None:
                raise DomainError("acceptance supersession requires a known prior decision")
            if (
                prior.domain is not decision.domain
                or prior.intended_use_id != decision.intended_use_id
                or prior.release_claim_id != decision.release_claim_id
            ):
                raise DomainError(
                    "acceptance supersession requires the same domain and release coordinate"
                )
            if prior.decided_at >= decision.decided_at:
                raise DomainError(
                    "acceptance supersession requires a later decision instant"
                )
            if prior_id in superseded_ids:
                raise DomainError(
                    "an acceptance decision requires one unambiguous direct successor"
                )
            superseded_ids.add(prior_id)
        current_decisions = tuple(
            decision for decision in decision_items if decision.decision_id not in superseded_ids
        )
        intended_uses = {decision.intended_use_id for decision in decision_items}
        release_claims = {decision.release_claim_id for decision in decision_items}
        intended_use_id = next(iter(intended_uses)) if len(intended_uses) == 1 else None
        release_claim_id = (
            next(iter(release_claims)) if len(release_claims) == 1 else None
        )
        current_by_domain: dict[AcceptanceDomain, list[AcceptanceDecision]] = {
            domain: [] for domain in self.REQUIRED
        }
        for decision in current_decisions:
            current_by_domain[decision.domain].append(decision)
        ambiguous = {
            domain for domain, items in current_by_domain.items() if len(items) > 1
        }
        conditional = {
            domain
            for domain, items in current_by_domain.items()
            if len(items) == 1 and items[0].decision == "approve_with_conditions"
        }
        eligible: dict[AcceptanceDomain, list[AcceptanceDecision]] = {
            domain: [] for domain in self.REQUIRED
        }
        for decision in current_decisions:
            # TARGET: a conditional decision remains visible and release-pending.
            # A later evidence-bound approval supersedes it when its condition closes.
            if decision.decision != "approve":
                continue
            if decision.expires_at is not None and decision.expires_at <= evaluated_at:
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
            selected[domain].decision_id for domain in accepted
        ]
        pending = self.REQUIRED.difference(accepted)
        return AcceptanceStatus(
            ready=not pending,
            accepted_domains=frozenset(accepted),
            pending_domains=frozenset(pending),
            conditional_domains=frozenset(conditional),
            ambiguous_domains=frozenset(ambiguous),
            decision_ids=tuple(sorted(decision_ids)),
            intended_use_id=intended_use_id,
            release_claim_id=release_claim_id,
        )
