from __future__ import annotations

import unittest

from lims_eln_implementation.application import GoldenSpecimenApplication
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
        application = GoldenSpecimenApplication(
            lifecycle=LifecycleService(InMemorySpecimenRepository()),
            custody=CustodyService(InMemoryOutbox()),
            ingress=InstrumentIngress(),
            projection=VendorProjectionService(gateway),
        )
        outcome = application.process(
            tenant_id="SYN-TENANT-A",
            specimen_id="SYN-SPECIMEN-0001",
            actor_id="SYN-ACTOR-01",
            occurred_at=NOW,
            raw_instrument_json=(
                b'{"analyte":"synthetic-dna","value":"12.5","unit":"ng/uL"}'
            ),
            vendor_payload={"status": "under_review"},
        )
        self.assertEqual(outcome.aggregate.state, "accessioned")
        self.assertEqual(outcome.custody_location, "SYN-LAB-A/RECEIVING")
        self.assertTrue(outcome.projection.reconciled)
        self.assertEqual(len(outcome.instrument_digest), 64)


if __name__ == "__main__":
    unittest.main()

