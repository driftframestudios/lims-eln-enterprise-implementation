from __future__ import annotations

import unittest

from lims_eln_implementation.idempotency import ContentCollision, IdempotencyInProgress
from lims_eln_implementation.observability import OperationalMetrics
from lims_eln_implementation.ports import VendorRevisionConflict
from lims_eln_implementation.vendors import (
    AmbiguousOutcomePending,
    FaultMode,
    InMemoryVendorGateway,
    VendorProjectionService,
)


class VendorProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gateway = InMemoryVendorGateway("synthetic-labkey")
        self.metrics = OperationalMetrics()
        self.service = VendorProjectionService(self.gateway, metrics=self.metrics)

    def project(self, request_id: str = "SYN-REQUEST-001", value: str = "12.5"):
        return self.service.project(
            tenant_id="SYN-TENANT-A",
            request_id=request_id,
            external_identity="SYN-SPECIMEN-0001",
            expected_revision=0,
            payload={"result": value, "unit": "ng/uL"},
        )

    def test_confirmed_projection_records_revision_and_rate(self) -> None:
        outcome = self.project()
        self.assertEqual(outcome.revision, 1)
        self.assertFalse(outcome.reconciled)
        snapshot = self.metrics.vendor_projection.snapshot()
        self.assertEqual((snapshot.numerator, snapshot.denominator), (1, 1))

    def test_timeout_after_commit_resolves_by_authoritative_readback(self) -> None:
        self.gateway.fault_mode = FaultMode.TIMEOUT_AFTER_COMMIT
        outcome = self.project()
        self.assertTrue(outcome.reconciled)
        self.assertEqual(outcome.revision, 1)
        reconciliation = self.metrics.reconciliation.snapshot()
        self.assertEqual((reconciliation.numerator, reconciliation.denominator), (1, 1))

    def test_timeout_before_commit_keeps_reservation_pending(self) -> None:
        self.gateway.fault_mode = FaultMode.TIMEOUT_BEFORE_COMMIT
        with self.assertRaisesRegex(AmbiguousOutcomePending, "retain the reservation"):
            self.project()
        self.assertEqual(
            self.metrics.vendor_projection.snapshot().denominator,
            1,
        )
        self.gateway.fault_mode = FaultMode.CLEAR
        with self.assertRaisesRegex(IdempotencyInProgress, "authoritative readback"):
            self.project()

    def test_exact_request_replay_reuses_outcome(self) -> None:
        first = self.project()
        second = self.project()
        self.assertEqual(second, first)
        self.assertEqual(self.metrics.vendor_projection.snapshot().denominator, 1)

    def test_changed_payload_on_request_identity_is_a_collision(self) -> None:
        self.project()
        with self.assertRaises(ContentCollision):
            self.project(value="13.0")

    def test_stale_external_revision_prompts_authoritative_read(self) -> None:
        self.project()
        with self.assertRaisesRegex(VendorRevisionConflict, "authoritative state"):
            self.service.project(
                tenant_id="SYN-TENANT-A",
                request_id="SYN-REQUEST-002",
                external_identity="SYN-SPECIMEN-0001",
                expected_revision=0,
                payload={"result": "14.0", "unit": "ng/uL"},
            )

    def test_tenant_identity_participates_in_vendor_key(self) -> None:
        first = self.project()
        other = self.service.project(
            tenant_id="SYN-TENANT-B",
            request_id="SYN-REQUEST-001",
            external_identity="SYN-SPECIMEN-0001",
            expected_revision=0,
            payload={"result": "12.5", "unit": "ng/uL"},
        )
        self.assertEqual((first.revision, other.revision), (1, 1))


if __name__ == "__main__":
    unittest.main()
