from __future__ import annotations

import unittest

from lims_eln_implementation.custody import CustodyService
from lims_eln_implementation.application import InstrumentReviewRequired
from lims_eln_implementation.idempotency import (
    IdempotencyLedger,
    ReservationInProgress,
)
from lims_eln_implementation.instrument import (
    IngressDisposition,
    InstrumentEnvelope,
    InstrumentIngress,
)
from lims_eln_implementation.lifecycle import LifecycleService
from lims_eln_implementation.model import DomainError
from lims_eln_implementation.store import InMemoryOutbox, InMemorySpecimenRepository
from lims_eln_implementation.workbench.service import WorkbenchService

from helpers import NOW, command


RAW_INSTRUMENT_JSON = b'{"analyte":"synthetic-dna","value":"12.5","unit":"ng/uL"}'


class WorkbenchServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = WorkbenchService(clock=lambda: NOW)

    def run_specimen(self, run_id: str, specimen_id: str) -> dict[str, object]:
        return self.service.run_golden_specimen(
            run_id=run_id,
            tenant_id="SYN-TENANT-A",
            specimen_id=specimen_id,
            actor_id="SYN-ACTOR-01",
            scientist_id="SYN-SCIENTIST-01",
            quality_actor_id="SYN-QUALITY-01",
            occurred_at=NOW,
            raw_instrument_json=RAW_INSTRUMENT_JSON,
            vendor_payload={"status": "under_review"},
        )

    def test_run_exposes_evidence_across_all_boundaries(self) -> None:
        result = self.run_specimen("SYN-RUN-001", "SYN-SPECIMEN-0001")
        specimen = result["specimen"]
        self.assertEqual(specimen["state"], "released")
        self.assertEqual(specimen["version"], 5)
        self.assertEqual(len(specimen["events"]), 5)
        self.assertEqual(specimen["custody"]["location"], "SYN-LAB-A/RECEIVING")
        self.assertEqual(
            specimen["instrument_receipts"][0]["disposition"], "accepted"
        )
        self.assertEqual(len(specimen["instrument_receipts"][0]["raw_sha256"]), 64)
        self.assertEqual(
            specimen["instrument_receipts"][0]["normalized_observation"]["analyte"],
            "SYNTHETIC-DNA",
        )
        self.assertEqual(
            specimen["instrument_receipts"][0]["normalized_observation"]["value"],
            "12.5",
        )
        self.assertEqual(
            specimen["instrument_receipts"][0]["normalized_observation"]["unit"],
            "ng/uL",
        )
        self.assertTrue(specimen["projection"]["reconciled"])
        self.assertEqual(result["outcome"]["call_decision"], "succeeded")
        self.assertTrue(result["outcome"]["call_receipt_id"])
        self.assertEqual(specimen["events"][3]["actor_id"], "SYN-SCIENTIST-01")
        self.assertEqual(specimen["events"][4]["actor_id"], "SYN-QUALITY-01")

    def test_exact_run_replay_preserves_one_custody_and_ingress_result(self) -> None:
        first = self.run_specimen("SYN-RUN-001", "SYN-SPECIMEN-0001")
        replay = self.run_specimen("SYN-RUN-001", "SYN-SPECIMEN-0001")
        self.assertEqual(first, replay)
        summary = self.service.summary("SYN-TENANT-A")
        self.assertEqual(summary["specimen_count"], 1)
        self.assertEqual(summary["instrument_receipt_count"], 1)
        self.assertEqual(summary["pending_outbox_count"], 1)

    def test_run_scoped_command_identities_support_multiple_specimens(self) -> None:
        self.run_specimen("SYN-RUN-001", "SYN-SPECIMEN-0001")
        self.run_specimen("SYN-RUN-002", "SYN-SPECIMEN-0002")
        summary = self.service.summary("SYN-TENANT-A")
        self.assertEqual(summary["specimen_count"], 2)
        self.assertEqual(summary["lifecycle_counts"], {"released": 2})

    def test_instrument_review_is_visible_and_resumable(self) -> None:
        with self.assertRaisesRegex(
            InstrumentReviewRequired,
            "analyte_requires_mapping",
        ):
            self.service.run_golden_specimen(
                run_id="SYN-RUN-REVIEW-001",
                tenant_id="SYN-TENANT-A",
                specimen_id="SYN-SPECIMEN-REVIEW-001",
                actor_id="SYN-ACTOR-01",
                scientist_id="SYN-SCIENTIST-01",
                quality_actor_id="SYN-QUALITY-01",
                occurred_at=NOW,
                raw_instrument_json=b'{"analyte":" ","value":"12.5","unit":"ng/uL"}',
                vendor_payload={"status": "under_review"},
            )
        review_summary = self.service.summary("SYN-TENANT-A")
        self.assertEqual(review_summary["lifecycle_counts"], {"in_process": 1})
        self.assertEqual(review_summary["quarantine_count"], 1)
        self.assertEqual(review_summary["quarantine_history_count"], 1)

        recovered = self.service.resume_instrument_review(
            recovery_of_run_id="SYN-RUN-REVIEW-001",
            run_id="SYN-RUN-RECOVERY-001",
            tenant_id="SYN-TENANT-A",
            specimen_id="SYN-SPECIMEN-REVIEW-001",
            actor_id="SYN-ACTOR-01",
            scientist_id="SYN-SCIENTIST-01",
            quality_actor_id="SYN-QUALITY-01",
            occurred_at=NOW,
            raw_instrument_json=RAW_INSTRUMENT_JSON,
            vendor_payload={"status": "under_review"},
        )
        self.assertEqual(recovered["specimen"]["state"], "released")
        self.assertEqual(len(recovered["specimen"]["instrument_receipts"]), 2)
        recovered_summary = self.service.summary("SYN-TENANT-A")
        self.assertEqual(recovered_summary["quarantine_count"], 0)
        self.assertEqual(recovered_summary["quarantine_history_count"], 1)

        replay = self.service.resume_instrument_review(
            recovery_of_run_id="SYN-RUN-REVIEW-001",
            run_id="SYN-RUN-RECOVERY-001",
            tenant_id="SYN-TENANT-A",
            specimen_id="SYN-SPECIMEN-REVIEW-001",
            actor_id="SYN-ACTOR-01",
            scientist_id="SYN-SCIENTIST-01",
            quality_actor_id="SYN-QUALITY-01",
            occurred_at=NOW,
            raw_instrument_json=RAW_INSTRUMENT_JSON,
            vendor_payload={"status": "under_review"},
        )
        self.assertEqual(replay, recovered)

    def test_instrument_recovery_retains_the_quarantined_specimen_identity(self) -> None:
        for run_id, specimen_id in (
            ("SYN-RUN-REVIEW-A", "SYN-SPECIMEN-REVIEW-A"),
            ("SYN-RUN-REVIEW-B", "SYN-SPECIMEN-REVIEW-B"),
        ):
            with self.assertRaises(InstrumentReviewRequired):
                self.service.run_golden_specimen(
                    run_id=run_id,
                    tenant_id="SYN-TENANT-A",
                    specimen_id=specimen_id,
                    actor_id="SYN-ACTOR-01",
                    scientist_id="SYN-SCIENTIST-01",
                    quality_actor_id="SYN-QUALITY-01",
                    occurred_at=NOW,
                    raw_instrument_json=b'{"analyte":" ","value":"12.5","unit":"ng/uL"}',
                    vendor_payload={"status": "under_review"},
                )

        with self.assertRaisesRegex(DomainError, "resume that specimen"):
            self.service.resume_instrument_review(
                recovery_of_run_id="SYN-RUN-REVIEW-A",
                run_id="SYN-RUN-RECOVERY-CROSS-SPECIMEN",
                tenant_id="SYN-TENANT-A",
                specimen_id="SYN-SPECIMEN-REVIEW-B",
                actor_id="SYN-ACTOR-01",
                scientist_id="SYN-SCIENTIST-01",
                quality_actor_id="SYN-QUALITY-01",
                occurred_at=NOW,
                raw_instrument_json=RAW_INSTRUMENT_JSON,
                vendor_payload={"status": "under_review"},
            )

        summary = self.service.summary("SYN-TENANT-A")
        self.assertEqual(summary["lifecycle_counts"], {"in_process": 2})
        self.assertEqual(summary["quarantine_count"], 2)


class ReplayBoundaryTests(unittest.TestCase):
    def test_custody_exact_replay_returns_original_position(self) -> None:
        outbox = InMemoryOutbox()
        service = CustodyService(outbox)
        arguments = {
            "tenant_id": "SYN-TENANT-A",
            "specimen_id": "SYN-SPECIMEN-0001",
            "location": "SYN-RECEIVING",
            "custodian_id": "SYN-ACTOR-01",
            "expected_version": 0,
            "transfer_id": "SYN-TRANSFER-001",
            "occurred_at": NOW,
        }
        first = service.place(**arguments)
        replay = service.place(**arguments)
        self.assertEqual(first, replay)
        self.assertEqual(len(outbox.messages), 1)

    def test_custody_changed_content_collides_on_transfer_identity(self) -> None:
        service = CustodyService(InMemoryOutbox())
        service.place(
            tenant_id="SYN-TENANT-A",
            specimen_id="SYN-SPECIMEN-0001",
            location="SYN-RECEIVING",
            custodian_id="SYN-ACTOR-01",
            expected_version=0,
            transfer_id="SYN-TRANSFER-001",
            occurred_at=NOW,
        )
        with self.assertRaisesRegex(DomainError, "different content"):
            service.place(
                tenant_id="SYN-TENANT-A",
                specimen_id="SYN-SPECIMEN-0001",
                location="SYN-FREEZER",
                custodian_id="SYN-ACTOR-01",
                expected_version=0,
                transfer_id="SYN-TRANSFER-001",
                occurred_at=NOW,
            )

    def test_quarantined_ingress_has_stable_exact_replay(self) -> None:
        ingress = InstrumentIngress()
        envelope = InstrumentEnvelope(
            tenant_id="SYN-TENANT-A",
            message_id="SYN-MESSAGE-001",
            instrument_id="SYN-INSTRUMENT-01",
            specimen_id="SYN-SPECIMEN-0001",
            captured_at=NOW,
            media_type="application/json",
            raw_bytes=b"{broken",
        )
        first = ingress.ingest(envelope)
        replay = ingress.ingest(envelope)
        self.assertEqual(first.disposition, IngressDisposition.QUARANTINED)
        self.assertEqual(replay.disposition, IngressDisposition.REPLAYED)
        self.assertEqual(replay.reason_code, "malformed_json")
        self.assertEqual(len(ingress.quarantine), 1)

    def test_active_lifecycle_reservation_surfaces_reconciliation(self) -> None:
        ledger = IdempotencyLedger()
        pending = command("SYN-COMMAND-001", "register", 0)
        ledger.reserve(pending.tenant_id, pending.command_id, pending.content_digest)
        lifecycle = LifecycleService(InMemorySpecimenRepository(), ledger)
        with self.assertRaisesRegex(ReservationInProgress, "reconcile"):
            lifecycle.register(pending)


if __name__ == "__main__":
    unittest.main()
