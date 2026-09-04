"""Content-addressed public inspection manifest proofs."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts.build_public_inspection_manifest import (
    InspectionManifestError,
    MANIFEST_PATH,
    build_manifest,
    verify_manifest,
    write_manifest,
)


ROOT = Path(__file__).resolve().parents[1]


class PublicInspectionManifestTests(unittest.TestCase):
    def manifest(self) -> dict[str, object]:
        return json.loads((ROOT / MANIFEST_PATH).read_text(encoding="utf-8"))

    def copy_inventory(self, target: Path) -> None:
        manifest = self.manifest()
        manifest_destination = target / MANIFEST_PATH
        manifest_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / MANIFEST_PATH, manifest_destination)
        for group in manifest["artifact_groups"]:
            for artifact in group["artifacts"]:
                relative_path = Path(artifact["path"])
                destination = target / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative_path, destination)

    def test_manifest_binds_current_repository_owned_bytes(self) -> None:
        manifest = verify_manifest(ROOT)
        self.assertEqual(
            manifest["release_state"], "post_release_development_carrier"
        )
        release_subject = manifest["release_subject"]
        self.assertEqual(release_subject["tag"], "v0.3.2")
        self.assertEqual(
            release_subject["tag_object_oid"],
            "c3db01079b88622f06e8714c8bcbdf0dc1803a10",
        )
        self.assertEqual(
            release_subject["commit_oid"],
            "fe0bd2a08ac1697ce18ca583d9631faae7db7132",
        )
        self.assertEqual(
            release_subject["archive_digest"],
            "sha256:0ea3db3099e3485f65d238fb2e194c6bfd9b9a90f6642431c4a96974ebcc3c16",
        )
        self.assertEqual(
            release_subject["review_observation"],
            {
                "merge_admission": "configured_ordinary_bypass",
                "independent_review": "deputized_independent_review_completed",
                "github_review_record": "no_formal_review_submitted",
            },
        )
        self.assertEqual(
            manifest["prior_release_subject"],
            {
                "promotion_receipt": "receipts/promotion-receipt.json",
                "tag": "v0.3.1",
                "tag_object_oid": "8b1013ff6a116b64e5d31c2870b574f641ee88f6",
                "commit_oid": "44a4b8e67ff2e6af232b12daf3692bee8e8f3a3a",
                "tree_oid": "cc1bb335c0cdd1a37d1b6554480b3afdb9c9f360",
                "archive_digest": (
                    "sha256:00da1be41bdf23a21124d600f3788464bfd8f590c819f6a9c74b98671edb2174"
                ),
            },
        )

        groups = {
            group["name"]: {artifact["path"] for artifact in group["artifacts"]}
            for group in manifest["artifact_groups"]
        }
        self.assertTrue(
            {
                "src/lims_eln_implementation/workbench/api.py",
                "src/lims_eln_implementation/workbench/postgres.py",
                "src/lims_eln_implementation/workbench/service.py",
                "src/lims_eln_implementation/workbench/shared_contracts.py",
                "src/lims_eln_implementation/production_adapters.py",
            }.issubset(groups["runtime_source"])
        )
        self.assertTrue(
            {
                "sql/V001__laboratory_core.sql",
                "sql/V002__principal_data_boundaries.sql",
                "sql/V003__trusted_routines_and_outbox_cas.sql",
                "sql/V004__outbox_attempt_evidence_and_recovery.sql",
                "sql/V005__golden_specimen_workbench.sql",
            }.issubset(groups["database_evolution"])
        )
        self.assertTrue(
            {
                "infra/otel-collector.yaml",
                "infra/terraform/runtime_configuration.tf",
                ".dockerignore",
                ".gitignore",
            }.issubset(groups["operational_configuration"])
        )
        self.assertTrue(
            {
                "scripts/build_package_archive.py",
                "scripts/validate_received_contracts.py",
                "tests/test_postgres_integration.py",
                "tests/test_shared_contract_binding.py",
                "tests/test_received_contracts.py",
                "tests/test_workbench_service.py",
                "tests/test_workbench_postgres_adapter.py",
                ".github/workflows/ci.yml",
                ".github/workflows/pull-request.yml",
            }.issubset(groups["behavior_proofs"])
        )
        self.assertIn(
            "release/external-contract-coordinates.json",
            groups["contracts_and_synthetic_inputs"],
        )
        self.assertIn(
            "contracts/promotion-receipt.v1.schema.json",
            groups["contracts_and_synthetic_inputs"],
        )
        self.assertIn(
            "contracts/promotion-observation.v1.schema.json",
            groups["contracts_and_synthetic_inputs"],
        )
        self.assertIn("receipts/promotion-receipt.json", groups["evidence_records"])
        self.assertIn(
            "receipts/promotion-observation-v0.3.2.json",
            groups["evidence_records"],
        )
        self.assertNotIn(
            "receipts/promotion-candidate.json",
            groups["evidence_records"],
        )
        self.assertTrue(
            {"AUTHORS", "README.md", ".github/dependabot.yml"}.issubset(
                groups["collaboration_and_orientation"]
            )
        )

        artifact_paths = set().union(*groups.values())
        self.assertTrue(set(manifest["manifest_carriers"]).isdisjoint(artifact_paths))

    def test_runtime_byte_change_breaks_the_inspection_identity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="inspection-runtime-") as directory:
            target = Path(directory)
            self.copy_inventory(target)
            service_path = (
                target
                / "src"
                / "lims_eln_implementation"
                / "workbench"
                / "service.py"
            )
            service_path.write_bytes(service_path.read_bytes() + b"\n")

            with self.assertRaisesRegex(
                InspectionManifestError,
                "inspection artifact bytes differ for .*workbench/service.py",
            ):
                verify_manifest(target)

    def test_manifest_carrier_rejects_symbolic_link_substitution(self) -> None:
        with tempfile.TemporaryDirectory(prefix="inspection-carrier-") as directory:
            target = Path(directory)
            self.copy_inventory(target)
            external = target / "external-manifest.json"
            external.write_bytes((target / MANIFEST_PATH).read_bytes())
            (target / MANIFEST_PATH).unlink()
            (target / MANIFEST_PATH).symlink_to(external)

            with self.assertRaisesRegex(
                InspectionManifestError,
                "regular repository-owned file",
            ):
                verify_manifest(target)

    def test_manifest_write_rejects_symbolic_link_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="inspection-write-") as directory:
            target = Path(directory)
            self.copy_inventory(target)
            external = target / "external-manifest.json"
            external.write_bytes(b"outside remains unchanged\n")
            (target / MANIFEST_PATH).unlink()
            (target / MANIFEST_PATH).symlink_to(external)

            with self.assertRaisesRegex(
                InspectionManifestError,
                "write target requires a regular repository-owned file",
            ):
                write_manifest(target)
            self.assertEqual(b"outside remains unchanged\n", external.read_bytes())

    def test_manifest_check_requires_canonical_bytes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="inspection-canonical-") as directory:
            target = Path(directory)
            self.copy_inventory(target)
            document = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
            (target / MANIFEST_PATH).write_text(
                json.dumps(document, separators=(",", ":")),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                InspectionManifestError,
                "canonical sorted, indented JSON form",
            ):
                verify_manifest(target)

    def test_missing_recovery_proof_breaks_the_release_identity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="inspection-proof-") as directory:
            target = Path(directory)
            self.copy_inventory(target)
            (target / "tests" / "test_workbench_service.py").unlink()

            with self.assertRaisesRegex(
                InspectionManifestError,
                "inspection artifact paths differ for behavior_proofs",
            ):
                verify_manifest(target)

    def test_symbolic_link_substitution_cannot_redirect_source_identity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="inspection-link-") as directory:
            target = Path(directory)
            self.copy_inventory(target)
            service_path = (
                target
                / "src"
                / "lims_eln_implementation"
                / "workbench"
                / "service.py"
            )
            service_path.unlink()
            service_path.symlink_to(target / "README.md")

            with self.assertRaisesRegex(
                InspectionManifestError,
                "inspection artifact path crosses a symbolic link",
            ):
                verify_manifest(target)

    def test_external_coordinates_project_their_accepted_revisions(self) -> None:
        coordinates = build_manifest(ROOT)["coordinate_boundaries"]
        self.assertEqual(
            {coordinate["role"] for coordinate in coordinates},
            {
                "program_contract",
                "governance_schema",
                "simulated_final_state",
                "comparative_evidence",
                "comparison_return",
            },
        )
        by_role = {coordinate["role"]: coordinate for coordinate in coordinates}
        program = by_role["program_contract"]
        self.assertEqual(program["coordinate_state"], "accepted_source_consumer_observed")
        self.assertEqual(
            program["accepted_revision"],
            "4d06eeb7f96910311fbcb7f51547c978b6a07290",
        )
        self.assertEqual(program["declared_release"], "0.3.1")
        governance = by_role["governance_schema"]
        self.assertEqual(governance["coordinate_state"], "accepted_release")
        self.assertEqual(governance["declared_release"], "2.1.0")
        self.assertEqual(governance["schema_release"], "2.1.0")
        expected_artifacts = {
            "simulated_final_state": "release/future-reality-2028-06-30-v1.json",
            "comparative_evidence": (
                "fixtures/simulated-closures/future-reality-2028-06-30-v1.json"
            ),
        }
        for role in ("simulated_final_state", "comparative_evidence"):
            selected_future = by_role[role]
            self.assertEqual(
                selected_future["closure_artifact_path"], expected_artifacts[role]
            )
            self.assertEqual(
                selected_future["canonical_closure_digest"],
                "sha256:33bcc14da24309b7716728b3f0204008e8f7ebf58de75f9e40a5986b421f06b5",
            )
            self.assertRegex(selected_future["tag_object_oid"], r"^[a-f0-9]{40}$")
            self.assertRegex(
                selected_future["archive_digest"],
                r"^sha256:[a-f0-9]{64}$",
            )
        comparison_return = by_role["comparison_return"]
        self.assertEqual(comparison_return["coordinate_state"], "accepted_return")
        self.assertEqual(
            comparison_return["declared_release"], "comparison-v0.3.2"
        )
        self.assertEqual(
            comparison_return["classification_counts"],
            {
                "agreement": 10,
                "explainable_variation": 4,
                "material_divergence": 3,
            },
        )
        self.assertEqual(
            comparison_return["material_divergence_paths"],
            [
                "$.measurement.analyte",
                "$.measurement.value",
                "$.measurement.unit",
            ],
        )
        self.assertEqual(
            comparison_return["material_divergence_receiver"],
            "accountable_scientific_mapping",
        )
        self.assertEqual(
            comparison_return["canonical_origin"], "https://cometspectrum.io/"
        )
        for coordinate in coordinates:
            with self.subTest(role=coordinate["role"]):
                self.assertEqual(
                    coordinate["coordinate_manifest"],
                    "release/external-contract-coordinates.json",
                )
                self.assertRegex(
                    coordinate["coordinate_manifest_sha256"],
                    r"^sha256:[a-f0-9]{64}$",
                )

    def test_manifest_carriers_bind_the_exact_inventory_document(self) -> None:
        digest = "sha256:" + sha256((ROOT / MANIFEST_PATH).read_bytes()).hexdigest()
        manifest = self.manifest()
        root_manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        release_role = json.loads(
            (ROOT / "release" / "repository-role.json").read_text(encoding="utf-8")
        )

        self.assertEqual(
            manifest["manifest_carriers"],
            [
                "manifest.json",
                "release/repository-role.json",
                "receipts/promotion-candidate.json",
            ],
        )
        self.assertEqual(
            root_manifest["public_inspection"]["manifest_digest"], digest
        )
        self.assertEqual(
            root_manifest["public_inspection"]["authority"],
            "repository_owned_inspection_bytes",
        )
        self.assertEqual(release_role["public_inspection_manifest_digest"], digest)


if __name__ == "__main__":
    unittest.main()
