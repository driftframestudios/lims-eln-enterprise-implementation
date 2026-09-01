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
        self.assertEqual(manifest["release_state"], "repository_owned_candidate")

        groups = {
            group["name"]: {artifact["path"] for artifact in group["artifacts"]}
            for group in manifest["artifact_groups"]
        }
        self.assertTrue(
            {
                "src/lims_eln_implementation/workbench/api.py",
                "src/lims_eln_implementation/workbench/service.py",
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
                "tests/test_postgres_integration.py",
                "tests/test_shared_contract_binding.py",
                "tests/test_workbench_service.py",
            }.issubset(groups["behavior_proofs"])
        )
        self.assertTrue(
            {"AUTHORS", "README.md"}.issubset(
                groups["collaboration_and_orientation"]
            )
        )

        artifact_paths = set().union(*groups.values())
        self.assertTrue(set(manifest["manifest_carriers"]).isdisjoint(artifact_paths))

    def test_runtime_byte_change_breaks_the_candidate_identity(self) -> None:
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

    def test_missing_recovery_proof_breaks_the_candidate_identity(self) -> None:
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

    def test_foreign_coordinates_wait_for_their_accepted_revisions(self) -> None:
        coordinates = self.manifest()["coordinate_boundaries"]
        self.assertEqual(
            {coordinate["role"] for coordinate in coordinates},
            {"program_contract", "governance_schema"},
        )
        for coordinate in coordinates:
            with self.subTest(role=coordinate["role"]):
                self.assertEqual(
                    coordinate["coordinate_state"],
                    "awaiting_accepted_revision",
                )
                self.assertNotIn("accepted_revision", coordinate)

    def test_manifest_carriers_bind_the_exact_inventory_document(self) -> None:
        digest = "sha256:" + sha256((ROOT / MANIFEST_PATH).read_bytes()).hexdigest()
        manifest = self.manifest()
        root_manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        release_role = json.loads(
            (ROOT / "release" / "repository-role.json").read_text(encoding="utf-8")
        )

        self.assertEqual(
            manifest["manifest_carriers"],
            ["manifest.json", "release/repository-role.json"],
        )
        self.assertEqual(
            root_manifest["public_inspection"]["manifest_digest"], digest
        )
        self.assertEqual(release_role["public_inspection_manifest_digest"], digest)


if __name__ == "__main__":
    unittest.main()
