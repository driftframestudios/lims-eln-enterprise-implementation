from __future__ import annotations

import unittest

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
        status = AcceptanceBoard().evaluate(receipts, decisions)
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
        status = AcceptanceBoard().evaluate(receipts, decisions)
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
        status = AcceptanceBoard().evaluate(receipts, decisions)
        self.assertIn(AcceptanceDomain.SCIENTIFIC, status.pending_domains)

    def test_each_domain_requires_its_own_decision(self) -> None:
        item = receipt("R-1")
        status = AcceptanceBoard().evaluate(
            [item], [decision(AcceptanceDomain.SCIENTIFIC, "R-1")]
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

        status = AcceptanceBoard().evaluate(receipts, decisions)

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

        status = AcceptanceBoard().evaluate(receipts, decisions)

        self.assertFalse(status.ready)
        self.assertEqual(status.accepted_domains, frozenset())


if __name__ == "__main__":
    unittest.main()
