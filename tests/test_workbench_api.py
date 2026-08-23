from __future__ import annotations

from base64 import b64encode
import unittest

from fastapi.testclient import TestClient

from lims_eln_implementation.workbench.api import create_app
from lims_eln_implementation.workbench.service import WorkbenchService

from helpers import NOW


class WorkbenchApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app(WorkbenchService(clock=lambda: NOW)))
        self.payload = {
            "run_id": "SYN-RUN-API-001",
            "tenant_id": "SYN-TENANT-A",
            "specimen_id": "SYN-SPECIMEN-API-001",
            "actor_id": "SYN-ACTOR-01",
            "scientist_id": "SYN-SCIENTIST-01",
            "quality_actor_id": "SYN-QUALITY-01",
            "occurred_at": NOW.isoformat(),
            "raw_instrument_payload_base64": b64encode(
                b'{"analyte":"synthetic-dna","value":"12.5","unit":"ng/uL"}'
            ).decode("ascii"),
            "vendor_payload": {"status": "under_review"},
        }

    def test_dashboard_and_security_headers_are_available(self) -> None:
        response = self.client.get("/workbench")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Golden Specimen Workbench", response.text)
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])

    def test_golden_run_and_summary_share_one_tenant_read_model(self) -> None:
        response = self.client.post(
            "/api/workbench/golden-runs",
            headers={"X-Tenant-ID": "SYN-TENANT-A"},
            json=self.payload,
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["specimen"]["state"], "released")

        summary = self.client.get(
            "/api/workbench/summary",
            headers={"X-Tenant-ID": "SYN-TENANT-A"},
            params={"tenant_id": "SYN-TENANT-A"},
        )
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()["specimen_count"], 1)
        self.assertEqual(summary.json()["instrument_receipt_count"], 1)

    def test_exact_api_replay_returns_the_recorded_journey(self) -> None:
        first = self.client.post(
            "/api/workbench/golden-runs",
            headers={"X-Tenant-ID": "SYN-TENANT-A"},
            json=self.payload,
        )
        replay = self.client.post(
            "/api/workbench/golden-runs",
            headers={"X-Tenant-ID": "SYN-TENANT-A"},
            json=self.payload,
        )
        self.assertEqual((first.status_code, replay.status_code), (201, 201))
        self.assertEqual(first.json(), replay.json())

    def test_tenant_context_mismatch_returns_problem_details(self) -> None:
        response = self.client.post(
            "/api/workbench/golden-runs",
            headers={"X-Tenant-ID": "SYN-TENANT-B"},
            json=self.payload,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.headers["content-type"], "application/problem+json")
        self.assertEqual(
            response.json()["type"],
            "urn:lims-eln:problem:tenant_context_mismatch",
        )

    def test_absent_specimen_returns_named_recovery(self) -> None:
        response = self.client.get(
            "/api/workbench/specimens/SYN-MISSING",
            headers={"X-Tenant-ID": "SYN-TENANT-A"},
            params={"tenant_id": "SYN-TENANT-A"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("register it", response.json()["detail"])

    def test_quarantine_and_recovery_are_explicit_api_states(self) -> None:
        invalid_payload = {
            **self.payload,
            "run_id": "SYN-RUN-REVIEW-API-001",
            "specimen_id": "SYN-SPECIMEN-REVIEW-API-001",
            "raw_instrument_payload_base64": b64encode(
                b'{"analyte":" ","value":"12.5","unit":"ng/uL"}'
            ).decode("ascii"),
        }
        review = self.client.post(
            "/api/workbench/golden-runs",
            headers={"X-Tenant-ID": "SYN-TENANT-A"},
            json=invalid_payload,
        )
        self.assertEqual(review.status_code, 409)
        self.assertIn("instrument review required", review.json()["detail"])

        recovery_payload = {
            **self.payload,
            "recovery_of_run_id": "SYN-RUN-REVIEW-API-001",
            "run_id": "SYN-RUN-RECOVERY-API-001",
            "specimen_id": "SYN-SPECIMEN-REVIEW-API-001",
        }
        recovery = self.client.post(
            "/api/workbench/instrument-recovery-runs",
            headers={"X-Tenant-ID": "SYN-TENANT-A"},
            json=recovery_payload,
        )
        self.assertEqual(recovery.status_code, 201, recovery.text)
        self.assertEqual(recovery.json()["specimen"]["state"], "released")

        summary = self.client.get(
            "/api/workbench/summary",
            headers={"X-Tenant-ID": "SYN-TENANT-A"},
            params={"tenant_id": "SYN-TENANT-A"},
        ).json()
        self.assertEqual(summary["quarantine_count"], 0)
        self.assertEqual(summary["quarantine_history_count"], 1)


if __name__ == "__main__":
    unittest.main()
