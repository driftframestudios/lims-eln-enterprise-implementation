"""Admission controls for exact configured observations and their current artifacts."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.validate_repository import (
    HOSTED_RESOURCE_CLEANUP_RECEIPT_CONTENT_DIGEST,
    HOSTED_V007_RECEIPT_CONTENT_DIGEST,
    OWNED_PG17_RECEIPT_CONTENT_DIGEST,
    OWNED_RESOURCE_CLEANUP_RECEIPT_CONTENT_DIGEST,
    file_digest,
    validate_current_database_observations,
    validate_observed_execution_receipt,
)

ROOT = Path(__file__).resolve().parents[1]


def content_digest(receipt):
    return "sha256:" + sha256(json.dumps(
        receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


class DatabaseObservationReceiptTests(unittest.TestCase):
    def setUp(self):
        self.observations = [
            (json.loads((ROOT / path).read_text()), digest)
            for path, digest in (
                ("receipts/hosted-postgresql-v007-proof.json", HOSTED_V007_RECEIPT_CONTENT_DIGEST),
                ("receipts/owned-postgresql17-recovery-proof.json", OWNED_PG17_RECEIPT_CONTENT_DIGEST),
                ("receipts/hosted-postgresql-resource-cleanup-proof.json", HOSTED_RESOURCE_CLEANUP_RECEIPT_CONTENT_DIGEST),
                ("receipts/owned-postgresql17-resource-cleanup-proof.json", OWNED_RESOURCE_CLEANUP_RECEIPT_CONTENT_DIGEST),
            )
        ]

    def test_recorded_content_admits_its_observed_artifacts(self):
        for receipt, recorded in self.observations:
            with self.subTest(receipt=receipt["receipt_id"]):
                validate_observed_execution_receipt(
                    receipt, observed_content_digest=recorded,
                    current_artifact_digests=tuple(receipt["artifact_digests"]),
                )

    def test_changed_coordinate_or_evidence_requires_its_own_admission(self):
        mutations = {
            "source": lambda r: r["version_bindings"].__setitem__("repository_commit", "1" * 40),
            "engine": lambda r: r["version_bindings"].__setitem__("postgresql", "99.0"),
            "scenario": lambda r: r["scenario_ids"].pop(),
            "artifact": lambda r: r["artifact_digests"].pop(),
            "time": lambda r: r.__setitem__("observed_at", "2025-01-01T00:00:00Z"),
            "performer": lambda r: r.__setitem__("performer_id", "SYN-UNOBSERVED-PERFORMER"),
            "reviewer": lambda r: r.__setitem__("reviewer_id", "SYN-UNOBSERVED-REVIEWER"),
            "limitation": lambda r: r["limitations"].pop(),
        }
        for receipt, recorded in self.observations:
            coordinate = "workflow_run" if "workflow_run" in receipt["version_bindings"] else "data_checksums"
            route_mutations = mutations | {
                coordinate: lambda r: r["version_bindings"].__setitem__(coordinate, "SYN-CHANGED")
            }
            for label, mutate in route_mutations.items():
                with self.subTest(receipt=receipt["receipt_id"], field=label):
                    changed = deepcopy(receipt)
                    mutate(changed)
                    with self.assertRaisesRegex(AssertionError, "exact recorded evidence"):
                        validate_observed_execution_receipt(
                            changed, observed_content_digest=recorded,
                        )

    def test_current_artifact_drift_requires_a_successor_coordinate(self):
        for receipt, recorded in self.observations:
            with self.subTest(receipt=receipt["receipt_id"]):
                with self.assertRaisesRegex(AssertionError, "exact observed bindings"):
                    validate_observed_execution_receipt(
                        receipt, observed_content_digest=recorded,
                        current_artifact_digests=("sha256:" + "0" * 64,),
                    )

    def test_typed_contract_precedes_admission(self):
        for receipt, _ in self.observations:
            for change in ({"observed_at": "SYN-INVALID-DATE"}, {"extra_field": "SYN-EXTRA"}):
                changed = receipt | change
                with self.subTest(receipt=receipt["receipt_id"], change=next(iter(change))):
                    with self.assertRaisesRegex(AssertionError, "typed v1.1 contract"):
                        validate_observed_execution_receipt(
                            changed, observed_content_digest=content_digest(changed),
                        )

    def test_current_artifacts_match_successors_and_historical_evidence_is_retained(self):
        validate_current_database_observations()

    def test_production_admission_preserves_each_recorded_receipt(self):
        original_read = Path.read_text
        for relative_path in (
            "receipts/hosted-postgresql-v007-proof.json",
            "receipts/owned-postgresql17-recovery-proof.json",
            "receipts/hosted-postgresql-resource-cleanup-proof.json",
            "receipts/owned-postgresql17-resource-cleanup-proof.json",
        ):
            target = ROOT / relative_path
            def changed_receipt(path, *args, **kwargs):
                value = original_read(path, *args, **kwargs)
                if path == target:
                    receipt = json.loads(value)
                    receipt["version_bindings"]["repository_commit"] = "1" * 40
                    return json.dumps(receipt)
                return value
            with self.subTest(path=relative_path):
                with patch.object(Path, "read_text", changed_receipt):
                    with self.assertRaisesRegex(AssertionError, "exact recorded evidence"):
                        validate_current_database_observations()

    def test_production_admission_checks_each_current_artifact_family(self):
        for relative_path in (
            "release/bounded-caller-bindings.json", "database/flyway-release.json",
            "database/flyway-artifact-inventory.json", "receipts/postgresql-resource-cleanup-plan-observations.json",
            ".github/workflows/ci.yml", "database/provision_cluster_roles.sql", "sql/V007__pending_outbox_specimen_index.sql",
        ):
            target = ROOT / relative_path
            def altered_digest(path):
                return "sha256:" + "0" * 64 if path == target else file_digest(path)
            with self.subTest(path=relative_path):
                with patch("scripts.validate_repository.file_digest", side_effect=altered_digest):
                    with self.assertRaisesRegex(AssertionError, "exact observed bindings"):
                        validate_current_database_observations()

    def test_production_admission_preserves_the_retained_plan_binding(self):
        target = ROOT / "receipts/postgresql-v007-plan-observations.json"
        def altered_digest(path):
            return "sha256:" + "0" * 64 if path == target else file_digest(path)
        with patch("scripts.validate_repository.file_digest", side_effect=altered_digest):
            with self.assertRaisesRegex(AssertionError, "exact observed bindings"):
                validate_current_database_observations()

    def test_production_admission_checks_native_runtime_source(self):
        original_read = Path.read_bytes
        for relative_path in (
            "scripts/check_database_restart.py",
            "src/lims_eln_implementation/resource_cleanup.py",
        ):
            target = ROOT / relative_path
            def changed_runtime(path):
                value = original_read(path)
                return value + b"\n" if path == target else value
            with self.subTest(path=relative_path):
                with patch.object(Path, "read_bytes", changed_runtime):
                    with self.assertRaisesRegex(AssertionError, "exact observed bindings"):
                        validate_current_database_observations()

    def test_historical_v005_receipt_retains_its_exact_bytes(self):
        self.assertEqual(
            file_digest(ROOT / "receipts/hosted-postgresql-proof.json"),
            "sha256:6833e9072dcbbe6078970391f7df5829a0e70ce6b976e3431970f81bc7af3c52",
        )

    def test_historical_v007_observations_retain_their_exact_bytes(self):
        for relative_path, expected in (
            ("receipts/hosted-postgresql-v007-proof.json", "b2a8157bbe4edac5bb7dc56093b6ac90f5884fef2e39cd20240b6a7a51356650"),
            ("receipts/owned-postgresql17-recovery-proof.json", "84b26e3bc522d3cf77b772b84b1c589c0bc0cc23a3df7c85e00672e1dd5dea78"),
            ("receipts/postgresql-v007-plan-observations.json", "b7d9255e186f065c9b3b211e6ca09feb513dd2282e1a71d70b8c48e10b8a8a2f"),
        ):
            with self.subTest(path=relative_path):
                self.assertEqual(file_digest(ROOT / relative_path), "sha256:" + expected)
