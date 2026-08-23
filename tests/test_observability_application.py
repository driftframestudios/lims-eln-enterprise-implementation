from __future__ import annotations

import unittest

from lims_eln_implementation.application import (
    InstrumentReviewRequired,
    build_reference_golden_specimen_application,
)
from lims_eln_implementation.bounded_caller import CallDenied
from lims_eln_implementation.custody import CustodyService
from lims_eln_implementation.instrument import InstrumentIngress
from lims_eln_implementation.lifecycle import LifecycleService
from lims_eln_implementation.observability import RatioMetric
from lims_eln_implementation.store import InMemoryOutbox, InMemorySpecimenRepository
from lims_eln_implementation.vendors import (
    FaultMode,
    InMemoryVendorGateway,
    VendorProjectionService,
)

from helpers import NOW


class ObservabilityTests(unittest.TestCase):
    def test_ratio_retains_good_and_valid_event_counts(self) -> None:
        metric = RatioMetric("semantic_success", window="rolling_24h", target=0.99)
        metric.observe(good=True)
        metric.observe(good=False)
        metric.observe(good=True, valid=False)
        snapshot = metric.snapshot()
        self.assertEqual(snapshot.numerator, 1)
        self.assertEqual(snapshot.denominator, 2)
        self.assertEqual(snapshot.ratio, 0.5)
        self.assertEqual(snapshot.target, 0.99)

    def test_empty_ratio_is_unknown_instead_of_invented_success(self) -> None:
        snapshot = RatioMetric("empty", window="current_release").snapshot()
        self.assertIsNone(snapshot.ratio)
        self.assertEqual(snapshot.denominator, 0)


class GoldenSpecimenTests(unittest.TestCase):
    def test_end_to_end_slice_preserves_evidence_across_boundaries(self) -> None:
        gateway = InMemoryVendorGateway("synthetic-benchling")
        gateway.fault_mode = FaultMode.TIMEOUT_AFTER_COMMIT
        application = build_reference_golden_specimen_application(
            lifecycle=LifecycleService(InMemorySpecimenRepository()),
            custody=CustodyService(InMemoryOutbox()),
            ingress=InstrumentIngress(),
            projection=VendorProjectionService(gateway),
            tenant_id="SYN-TENANT-A",
            caller_id="svc-reference-workflow",
            actor_ids=frozenset({"SYN-ACTOR-01"}),
            clock=lambda: NOW,
        )
        outcome = application.process(
            call_id="SYN-GOLDEN-CALL-001",
            tenant_id="SYN-TENANT-A",
            specimen_id="SYN-SPECIMEN-0001",
            actor_id="SYN-ACTOR-01",
            occurred_at=NOW,
            raw_instrument_json=(
                b'{"analyte":"synthetic-dna","value":"12.5","unit":"ng/uL"}'
            ),
            vendor_payload={"status": "under_review"},
        )
        self.assertEqual(outcome.aggregate.state, "released")
        self.assertEqual(outcome.aggregate.version, 5)
        self.assertEqual(outcome.custody_location, "SYN-LAB-A/RECEIVING")
        self.assertTrue(outcome.projection.reconciled)
        self.assertEqual(len(outcome.instrument_digest), 64)
        self.assertEqual(outcome.call_decision, "succeeded")
        self.assertTrue(outcome.call_receipt_id)

    def test_distinct_scientific_and_quality_actors_are_grant_bound(self) -> None:
        actors = frozenset(
            {"SYN-ACTOR-01", "SYN-SCIENTIST-01", "SYN-QUALITY-01"}
        )
        application = build_reference_golden_specimen_application(
            lifecycle=LifecycleService(InMemorySpecimenRepository()),
            custody=CustodyService(InMemoryOutbox()),
            ingress=InstrumentIngress(),
            projection=VendorProjectionService(
                InMemoryVendorGateway("synthetic-labkey")
            ),
            tenant_id="SYN-TENANT-A",
            caller_id="svc-reference-workflow",
            actor_ids=actors,
            clock=lambda: NOW,
        )
        outcome = application.process(
            call_id="SYN-GOLDEN-CALL-ROLES",
            tenant_id="SYN-TENANT-A",
            specimen_id="SYN-SPECIMEN-ROLES",
            actor_id="SYN-ACTOR-01",
            scientist_id="SYN-SCIENTIST-01",
            quality_actor_id="SYN-QUALITY-01",
            occurred_at=NOW,
            raw_instrument_json=(
                b'{"analyte":"synthetic-dna","value":"12.5","unit":"ng/uL"}'
            ),
            vendor_payload={"status": "under_review"},
        )
        self.assertEqual(outcome.aggregate.events[-2].actor_id, "SYN-SCIENTIST-01")
        self.assertEqual(outcome.aggregate.events[-1].actor_id, "SYN-QUALITY-01")

    def test_application_boundary_denies_actor_outside_issued_grant(self) -> None:
        application = build_reference_golden_specimen_application(
            lifecycle=LifecycleService(InMemorySpecimenRepository()),
            custody=CustodyService(InMemoryOutbox()),
            ingress=InstrumentIngress(),
            projection=VendorProjectionService(
                InMemoryVendorGateway("synthetic-labkey")
            ),
            tenant_id="SYN-TENANT-A",
            caller_id="svc-reference-workflow",
            actor_ids=frozenset({"SYN-ACTOR-01"}),
            clock=lambda: NOW,
        )

        with self.assertRaises(CallDenied) as captured:
            application.process(
                call_id="SYN-GOLDEN-CALL-DENIED",
                tenant_id="SYN-TENANT-A",
                specimen_id="SYN-SPECIMEN-0002",
                actor_id="SYN-ACTOR-OUTSIDE-GRANT",
                occurred_at=NOW,
                raw_instrument_json=(
                    b'{"analyte":"synthetic-dna","value":"12.5","unit":"ng/uL"}'
                ),
                vendor_payload={"status": "under_review"},
            )

        self.assertEqual(captured.exception.reason_code, "actor_outside_grant")

    def test_quarantine_requires_a_distinct_bounded_recovery_call(self) -> None:
        repository = InMemorySpecimenRepository()
        application = build_reference_golden_specimen_application(
            lifecycle=LifecycleService(repository),
            custody=CustodyService(InMemoryOutbox()),
            ingress=InstrumentIngress(),
            projection=VendorProjectionService(
                InMemoryVendorGateway("synthetic-labkey")
            ),
            tenant_id="SYN-TENANT-A",
            caller_id="svc-reference-workflow",
            actor_ids=frozenset({"SYN-ACTOR-01"}),
            clock=lambda: NOW,
        )
        arguments = {
            "call_id": "SYN-GOLDEN-CALL-REVIEW",
            "tenant_id": "SYN-TENANT-A",
            "specimen_id": "SYN-SPECIMEN-REVIEW",
            "actor_id": "SYN-ACTOR-01",
            "occurred_at": NOW,
            "raw_instrument_json": (
                b'{"analyte":" ","value":"12.5","unit":"ng/uL"}'
            ),
            "vendor_payload": {"status": "under_review"},
        }
        with self.assertRaises(InstrumentReviewRequired):
            application.process(**arguments)
        with self.assertRaises(CallDenied) as recovery_required:
            application.process(**arguments)
        self.assertEqual(
            recovery_required.exception.reason_code,
            "invocation_recovery_required",
        )

        recovered = application.resume_after_instrument_review(
            recovery_of_call_id="SYN-GOLDEN-CALL-REVIEW",
            call_id="SYN-GOLDEN-CALL-RECOVERY",
            tenant_id="SYN-TENANT-A",
            specimen_id="SYN-SPECIMEN-REVIEW",
            actor_id="SYN-ACTOR-01",
            scientist_id="SYN-ACTOR-01",
            quality_actor_id="SYN-ACTOR-01",
            occurred_at=NOW,
            raw_instrument_json=(
                b'{"analyte":"synthetic-dna","value":"12.5","unit":"ng/uL"}'
            ),
            vendor_payload={"status": "under_review"},
        )
        self.assertEqual(recovered.aggregate.state, "released")
        self.assertEqual(recovered.call_decision, "succeeded")


if __name__ == "__main__":
    unittest.main()
