from __future__ import annotations

import unittest
from datetime import timedelta

from lims_eln_implementation.acceptance import (
    AcceptanceBoard,
    AcceptanceDecision,
    AcceptanceDomain,
)
from lims_eln_implementation.model import DomainError
from lims_eln_implementation.receipts import (
    AssuranceStage,
    EvidenceMode,
    EvidenceReceipt,
)
from lims_eln_implementation.security import (
    AccessBoundaryError,
    AccessContext,
    EvidenceRedactor,
)

from helpers import NOW


def receipt(
    receipt_id: str,
    *,
    mode: EvidenceMode = EvidenceMode.OBSERVED,
    stage: AssuranceStage = AssuranceStage.VALIDATED,
) -> EvidenceReceipt:
    return EvidenceReceipt(
        receipt_id=receipt_id,
        claim_id="CLAIM-INTENDED-USE-01",
        intended_use_id="SYN-INTENDED-USE-01",
        release_claim_id="SYN-RELEASE-CLAIM-01",
        evidence_mode=mode,
        assurance_stage=stage,
        environment="SYN-QUALIFICATION-ENV",
        version_bindings={"commit": "a" * 40, "schema": "1.0.0"},
        scenario_ids=("SCN-001",),
        artifact_digests=("sha256:" + "b" * 64,),
        observed_at=NOW,
        performer_id="SYN-PERFORMER-01",
        reviewer_id="SYN-REVIEWER-01",
    )


def decision(domain: AcceptanceDomain, receipt_id: str) -> AcceptanceDecision:
    return AcceptanceDecision(
        domain=domain,
        decision_id=f"DEC-{domain.upper()}-{receipt_id}",
        approver_id=f"SYN-{domain.upper()}-APPROVER",
        role=f"{domain} accountable owner",
        decision="approve",
        intended_use_id="SYN-INTENDED-USE-01",
        release_claim_id="SYN-RELEASE-CLAIM-01",
        receipt_ids=(receipt_id,),
        residual_risk="bounded and accepted for the stated synthetic intended use",
        decided_at=NOW,
    )


class SecurityTests(unittest.TestCase):
    def test_tenant_and_capability_both_authorize_access(self) -> None:
        context = AccessContext(
            tenant_id="SYN-TENANT-A",
            actor_id="SYN-ACTOR-01",
            capabilities=frozenset({"specimen.read"}),
        )
        context.authorize(tenant_id="SYN-TENANT-A", capability="specimen.read")
        with self.assertRaisesRegex(AccessBoundaryError, "authorized tenant context"):
            context.authorize(tenant_id="SYN-TENANT-B", capability="specimen.read")
        with self.assertRaisesRegex(AccessBoundaryError, "accountable owner"):
            context.authorize(tenant_id="SYN-TENANT-A", capability="specimen.release")

    def test_redactor_preserves_shape_and_replaces_protected_values(self) -> None:
        redactor = EvidenceRedactor(
            {"tenant_id", "trace_id", "status", "details", "patient_name"}
        )
        output = redactor.redact(
            {
                "tenant_id": "SYN-TENANT-A",
                "trace_id": "SYN-TRACE-01",
                "status": "quarantined",
                "patient_name": "Synthetic Person",
                "details": {
                    "token": "secret-value",
                    "reason": "unit_mapping",
                },
            }
        )
        self.assertEqual(output["tenant_id"], "SYN-TENANT-A")
        self.assertEqual(output["patient_name"], "[REDACTED]")
        self.assertEqual(output["details"]["token"], "[REDACTED]")
        self.assertEqual(output["details"]["reason"], "[REDACTED]")


class ReceiptTests(unittest.TestCase):
    def test_receipt_requires_independent_reviewer(self) -> None:
        with self.assertRaisesRegex(DomainError, "independent reviewer"):
            EvidenceReceipt(
                receipt_id="R-001",
                claim_id="C-001",
                intended_use_id="SYN-INTENDED-USE-01",
                release_claim_id="SYN-RELEASE-CLAIM-01",
                evidence_mode=EvidenceMode.OBSERVED,
                assurance_stage=AssuranceStage.VERIFIED,
                environment="SYN-ENV",
                version_bindings={"commit": "a" * 40},
                scenario_ids=("S-001",),
                artifact_digests=("sha256:" + "b" * 64,),
                observed_at=NOW,
                performer_id="SYN-ACTOR",
                reviewer_id="SYN-ACTOR",
            )

    def test_assurance_stage_order_is_explicit(self) -> None:
        item = receipt("R-001", stage=AssuranceStage.QUALIFIED)
        self.assertTrue(item.reaches(AssuranceStage.VERIFIED))
        self.assertFalse(item.reaches(AssuranceStage.VALIDATED))


class AcceptanceTests(unittest.TestCase):
    def test_three_separate_observed_decisions_create_ready_status(self) -> None:
        receipts = [receipt(f"R-{index}") for index in range(1, 4)]
        decisions = [
            decision(AcceptanceDomain.SCIENTIFIC, "R-1"),
            decision(AcceptanceDomain.QUALITY, "R-2"),
            decision(AcceptanceDomain.REGULATORY, "R-3"),
        ]
        status = AcceptanceBoard().evaluate(receipts, decisions, evaluated_at=NOW)
        self.assertTrue(status.ready)
        self.assertEqual(status.accepted_domains, AcceptanceBoard.REQUIRED)

    def test_simulated_receipt_returns_domain_to_evidence_gathering(self) -> None:
        receipts = [
            receipt("R-1", mode=EvidenceMode.SIMULATED),
            receipt("R-2"),
            receipt("R-3"),
        ]
        decisions = [
            decision(AcceptanceDomain.SCIENTIFIC, "R-1"),
            decision(AcceptanceDomain.QUALITY, "R-2"),
            decision(AcceptanceDomain.REGULATORY, "R-3"),
        ]
        status = AcceptanceBoard().evaluate(receipts, decisions, evaluated_at=NOW)
        self.assertFalse(status.ready)
        self.assertIn(AcceptanceDomain.SCIENTIFIC, status.pending_domains)

    def test_verified_receipt_returns_domain_to_validation(self) -> None:
        receipts = [
            receipt("R-1", stage=AssuranceStage.VERIFIED),
            receipt("R-2"),
            receipt("R-3"),
        ]
        decisions = [
            decision(AcceptanceDomain.SCIENTIFIC, "R-1"),
            decision(AcceptanceDomain.QUALITY, "R-2"),
            decision(AcceptanceDomain.REGULATORY, "R-3"),
        ]
        status = AcceptanceBoard().evaluate(receipts, decisions, evaluated_at=NOW)
        self.assertIn(AcceptanceDomain.SCIENTIFIC, status.pending_domains)

    def test_each_domain_requires_its_own_decision(self) -> None:
        item = receipt("R-1")
        status = AcceptanceBoard().evaluate(
            [item],
            [decision(AcceptanceDomain.SCIENTIFIC, "R-1")],
            evaluated_at=NOW,
        )
        self.assertFalse(status.ready)
        self.assertEqual(
            status.pending_domains,
            frozenset({AcceptanceDomain.QUALITY, AcceptanceDomain.REGULATORY}),
        )

    def test_mixed_intended_use_or_release_claim_keeps_board_pending(self) -> None:
        receipts = [receipt(f"R-{index}") for index in range(1, 4)]
        decisions = [
            decision(AcceptanceDomain.SCIENTIFIC, "R-1"),
            decision(AcceptanceDomain.QUALITY, "R-2"),
            AcceptanceDecision(
                domain=AcceptanceDomain.REGULATORY,
                decision_id="DEC-REGULATORY-R-3",
                approver_id="SYN-REGULATORY-APPROVER",
                role="regulatory accountable owner",
                decision="approve",
                intended_use_id="SYN-OTHER-INTENDED-USE",
                release_claim_id="SYN-OTHER-RELEASE",
                receipt_ids=("R-3",),
                residual_risk="bounded for the alternate synthetic use",
                decided_at=NOW,
            ),
        ]

        status = AcceptanceBoard().evaluate(receipts, decisions, evaluated_at=NOW)

        self.assertFalse(status.ready)
        self.assertIsNone(status.intended_use_id)
        self.assertIsNone(status.release_claim_id)

    def test_receipt_and_decision_capture_immutable_snapshots(self) -> None:
        bindings = {"commit": "a" * 40}
        scenarios = ["SCN-001"]
        evidence = EvidenceReceipt(
            receipt_id="R-SNAPSHOT",
            claim_id="CLAIM-SNAPSHOT",
            intended_use_id="SYN-INTENDED-USE-01",
            release_claim_id="SYN-RELEASE-CLAIM-01",
            evidence_mode=EvidenceMode.OBSERVED,
            assurance_stage=AssuranceStage.VALIDATED,
            environment="SYN-ENV",
            version_bindings=bindings,
            scenario_ids=scenarios,
            artifact_digests=("sha256:" + "c" * 64,),
            observed_at=NOW,
            performer_id="SYN-PERFORMER",
            reviewer_id="SYN-REVIEWER",
        )
        bindings["commit"] = "mutated"
        scenarios[0] = "SCN-MUTATED"

        self.assertEqual(evidence.version_bindings["commit"], "a" * 40)
        self.assertEqual(evidence.scenario_ids, ("SCN-001",))
        with self.assertRaises(TypeError):
            evidence.version_bindings["commit"] = "changed"  # type: ignore[index]

    def test_acceptance_domains_require_distinct_accountable_approvers(self) -> None:
        receipts = [receipt(f"R-{index}") for index in range(1, 4)]
        decisions = [
            AcceptanceDecision(
                domain=domain,
                decision_id=f"DEC-{domain.upper()}-R-{index}",
                approver_id="SYN-SHARED-APPROVER",
                role=f"{domain} accountable owner",
                decision="approve",
                intended_use_id="SYN-INTENDED-USE-01",
                release_claim_id="SYN-RELEASE-CLAIM-01",
                receipt_ids=(f"R-{index}",),
                residual_risk="bounded for the synthetic intended use",
                decided_at=NOW,
            )
            for index, domain in enumerate(AcceptanceBoard.REQUIRED, start=1)
        ]

        status = AcceptanceBoard().evaluate(receipts, decisions, evaluated_at=NOW)

        self.assertFalse(status.ready)
        self.assertEqual(status.accepted_domains, frozenset())

    def test_conditional_decision_stays_pending_until_superseded(self) -> None:
        receipts = [receipt(f"R-{index}") for index in range(1, 5)]
        conditional = AcceptanceDecision(
            domain=AcceptanceDomain.SCIENTIFIC,
            decision_id="DEC-SCI-CONDITIONAL",
            approver_id="SYN-SCIENTIFIC-APPROVER",
            role="scientific accountable owner",
            decision="approve_with_conditions",
            intended_use_id="SYN-INTENDED-USE-01",
            release_claim_id="SYN-RELEASE-CLAIM-01",
            receipt_ids=("R-1",),
            residual_risk="bounded after the stated condition closes",
            decided_at=NOW,
            condition_summary="Complete the assay-range reconciliation",
            condition_owner_id="SYN-SCIENTIFIC-CONDITION-OWNER",
            condition_due_at=NOW + timedelta(days=7),
        )
        other_domains = [
            decision(AcceptanceDomain.QUALITY, "R-2"),
            decision(AcceptanceDomain.REGULATORY, "R-3"),
        ]

        pending = AcceptanceBoard().evaluate(
            receipts,
            [conditional, *other_domains],
            evaluated_at=NOW,
        )

        self.assertFalse(pending.ready)
        self.assertEqual(
            pending.conditional_domains,
            frozenset({AcceptanceDomain.SCIENTIFIC}),
        )

        closing_approval = AcceptanceDecision(
            domain=AcceptanceDomain.SCIENTIFIC,
            decision_id="DEC-SCI-CLOSED",
            approver_id="SYN-SCIENTIFIC-APPROVER",
            role="scientific accountable owner",
            decision="approve",
            intended_use_id="SYN-INTENDED-USE-01",
            release_claim_id="SYN-RELEASE-CLAIM-01",
            receipt_ids=("R-4",),
            residual_risk="condition closure is bound to observed evidence",
            decided_at=NOW + timedelta(days=1),
            supersedes_decision_id="DEC-SCI-CONDITIONAL",
        )
        ready = AcceptanceBoard().evaluate(
            receipts,
            [conditional, closing_approval, *other_domains],
            evaluated_at=NOW + timedelta(days=1),
        )

        self.assertTrue(ready.ready)
        self.assertEqual(ready.conditional_domains, frozenset())
        self.assertIn("DEC-SCI-CLOSED", ready.decision_ids)

    def test_return_for_evidence_supersedes_an_approval(self) -> None:
        receipts = [receipt(f"R-{index}") for index in range(1, 4)]
        approval = decision(AcceptanceDomain.SCIENTIFIC, "R-1")
        returned = AcceptanceDecision(
            domain=AcceptanceDomain.SCIENTIFIC,
            decision_id="DEC-SCI-RETURNED",
            approver_id="SYN-SCIENTIFIC-APPROVER",
            role="scientific accountable owner",
            decision="return_for_evidence",
            intended_use_id="SYN-INTENDED-USE-01",
            release_claim_id="SYN-RELEASE-CLAIM-01",
            receipt_ids=("R-1",),
            residual_risk="additional assay evidence is required",
            decided_at=NOW + timedelta(hours=1),
            supersedes_decision_id=approval.decision_id,
        )
        status = AcceptanceBoard().evaluate(
            receipts,
            [
                approval,
                returned,
                decision(AcceptanceDomain.QUALITY, "R-2"),
                decision(AcceptanceDomain.REGULATORY, "R-3"),
            ],
            evaluated_at=NOW + timedelta(hours=1),
        )

        self.assertFalse(status.ready)
        self.assertIn(AcceptanceDomain.SCIENTIFIC, status.pending_domains)

    def test_expired_approval_returns_its_domain_to_acceptance(self) -> None:
        receipts = [receipt(f"R-{index}") for index in range(1, 4)]
        expiring = AcceptanceDecision(
            domain=AcceptanceDomain.SCIENTIFIC,
            decision_id="DEC-SCI-EXPIRING",
            approver_id="SYN-SCIENTIFIC-APPROVER",
            role="scientific accountable owner",
            decision="approve",
            intended_use_id="SYN-INTENDED-USE-01",
            release_claim_id="SYN-RELEASE-CLAIM-01",
            receipt_ids=("R-1",),
            residual_risk="bounded for the declared acceptance window",
            decided_at=NOW,
            expires_at=NOW + timedelta(days=30),
        )
        status = AcceptanceBoard().evaluate(
            receipts,
            [
                expiring,
                decision(AcceptanceDomain.QUALITY, "R-2"),
                decision(AcceptanceDomain.REGULATORY, "R-3"),
            ],
            evaluated_at=NOW + timedelta(days=31),
        )

        self.assertFalse(status.ready)
        self.assertIn(AcceptanceDomain.SCIENTIFIC, status.pending_domains)


if __name__ == "__main__":
    unittest.main()
