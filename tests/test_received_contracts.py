"""Accepted external-coordinate and source-identity proofs."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.validate_received_contracts import (
    COORDINATE_PATH,
    ReceivedContractError,
    load_coordinates,
    program_source_digest_from_git,
    validate_coordinate_document,
    validate_declared_program_requirement,
    validate_governance_source,
    validate_installed_program,
    validate_selected_future_source,
)


ROOT = Path(__file__).resolve().parents[1]


class ReceivedContractTests(unittest.TestCase):
    def _installed_fixture(
        self,
        root: Path,
        *,
        direct_url_text: str | None = None,
        operation_count: int = 3,
        scenario_id: str = "SCN-GOLDEN-SPECIMEN-001",
        schema_count: int = 7,
        schema_is_object: bool = True,
        shadow_import: bool = False,
    ) -> tuple[SimpleNamespace, SimpleNamespace]:
        package_root = root / "site-packages" / "lims_eln_contracts"
        package_root.mkdir(parents=True)
        module_path = package_root / "__init__.py"
        module_path.write_text("# installed fixture\n", encoding="utf-8")
        if shadow_import:
            shadow_root = root / "shadow" / "lims_eln_contracts"
            shadow_root.mkdir(parents=True)
            module_path = shadow_root / "__init__.py"
            module_path.write_text("# shadow fixture\n", encoding="utf-8")

        if direct_url_text is None:
            direct_url_text = json.dumps(
                {
                    "url": (
                        "https://github.com/driftframestudios/"
                        "lims-eln-program-specification.git"
                    ),
                    "vcs_info": {
                        "vcs": "git",
                        "requested_revision": (
                            "4d06eeb7f96910311fbcb7f51547c978b6a07290"
                        ),
                        "commit_id": (
                            "4d06eeb7f96910311fbcb7f51547c978b6a07290"
                        ),
                    },
                }
            )

        distribution = SimpleNamespace(
            version="0.3.1",
            files=[Path("lims_eln_contracts/__init__.py")],
            locate_file=lambda relative_path: root / "site-packages" / relative_path,
            read_text=lambda name: direct_url_text if name == "direct_url.json" else None,
        )
        scenario = SimpleNamespace(scenario_id=scenario_id)
        schema_names = [f"schema-{index}.json" for index in range(schema_count)]
        contracts = SimpleNamespace(
            __file__=str(module_path),
            __version__="0.3.1",
            CONTRACT_VERSION="1.0.0",
            SCHEMA_RESOURCE_NAMES=schema_names,
            load_operation_catalog=lambda: SimpleNamespace(
                operations=[object() for _ in range(operation_count)]
            ),
            load_golden_specimen_scenario=lambda: scenario,
            load_golden_specimen_observation_example=lambda producer: SimpleNamespace(
                scenario_id=scenario.scenario_id
            ),
            load_generated_schema=lambda name: {} if schema_is_object else [],
        )
        return distribution, contracts

    def test_current_coordinate_is_complete_and_exact(self) -> None:
        coordinates = load_coordinates(ROOT)
        self.assertEqual(
            coordinates["program_contract"]["source_commit"],
            "4d06eeb7f96910311fbcb7f51547c978b6a07290",
        )
        self.assertEqual(coordinates["governance"]["schema_release"], "2.1.0")
        self.assertEqual(
            coordinates["selected_future"]["canonical_closure_digest"],
            "sha256:33bcc14da24309b7716728b3f0204008e8f7ebf58de75f9e40a5986b421f06b5",
        )
        self.assertEqual(
            [
                source["role"]
                for source in coordinates["selected_future"]["accepted_sources"]
            ],
            ["simulated_final_state", "comparative_evidence"],
        )
        self.assertEqual(
            {
                source["role"]: source["closure_artifact_path"]
                for source in coordinates["selected_future"]["accepted_sources"]
            },
            {
                "simulated_final_state": (
                    "release/future-reality-2028-06-30-v1.json"
                ),
                "comparative_evidence": (
                    "fixtures/simulated-closures/"
                    "future-reality-2028-06-30-v1.json"
                ),
            },
        )

        changed = deepcopy(coordinates)
        changed["program_contract"]["source_commit"] = "0" * 40
        with self.assertRaisesRegex(ReceivedContractError, "program source_commit"):
            validate_coordinate_document(changed)

        changed = deepcopy(coordinates)
        changed["selected_future"]["canonical_closure_digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(
            ReceivedContractError, "selected future canonical_closure_digest"
        ):
            validate_coordinate_document(changed)

    def test_program_digest_reads_the_reviewed_commit_tree(self) -> None:
        with tempfile.TemporaryDirectory(prefix="received-program-") as directory:
            root = Path(directory)
            package = root / "src" / "lims_eln_contracts"
            package.mkdir(parents=True)
            (root / "pyproject.toml").write_text(
                '[project]\nname = "example"\n', encoding="utf-8"
            )
            module = package / "__init__.py"
            module.write_text("VALUE = 1\n", encoding="utf-8")
            for command in (
                ["git", "init", "--quiet"],
                ["git", "config", "user.name", "Coordinate Test"],
                ["git", "config", "user.email", "coordinate-test@example.invalid"],
                ["git", "add", "pyproject.toml", "src/lims_eln_contracts"],
                ["git", "commit", "--quiet", "-m", "Program source"],
            ):
                subprocess.run(command, cwd=root, check=True)
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

            expected = (
                "sha256:b01c3276a1f5e554c59784d01786233cec3dbf673973fb921094866732c605c7"
            )
            self.assertEqual(expected, program_source_digest_from_git(root, commit))

            module.write_text("VALUE = 2\n", encoding="utf-8")
            cache = package / "__pycache__"
            cache.mkdir()
            (cache / "__init__.cpython-312.pyc").write_bytes(b"runtime cache")
            self.assertEqual(expected, program_source_digest_from_git(root, commit))

    def test_declared_dependency_matches_the_accepted_program_requirement(self) -> None:
        coordinates = load_coordinates(ROOT)
        validate_declared_program_requirement(ROOT, coordinates)

        with tempfile.TemporaryDirectory(prefix="program-requirement-") as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text(
                "[project]\n"
                'name = "receiving-example"\n'
                "[project.optional-dependencies]\n"
                'contracts = ["lims-eln-program-specification>=0.3.1,<0.4"]\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ReceivedContractError, "declared Program contracts dependency"
            ):
                validate_declared_program_requirement(root, coordinates)

    def test_governance_identity_binds_tag_commit_tree_and_archive(self) -> None:
        with tempfile.TemporaryDirectory(prefix="received-governance-") as directory:
            root = Path(directory)
            (root / "governance.txt").write_text("release source\n", encoding="utf-8")
            for command in (
                ["git", "init", "--quiet"],
                ["git", "config", "user.name", "Coordinate Test"],
                ["git", "config", "user.email", "coordinate-test@example.invalid"],
                ["git", "add", "governance.txt"],
                ["git", "commit", "--quiet", "-m", "Governance source"],
                [
                    "git",
                    "tag",
                    "--annotate",
                    "governance-v2.1.0",
                    "--message",
                    "Governance 2.1.0",
                ],
            ):
                subprocess.run(command, cwd=root, check=True)

            def git(*arguments: str, text: bool = True) -> str | bytes:
                result = subprocess.run(
                    ["git", *arguments],
                    cwd=root,
                    check=True,
                    capture_output=True,
                    text=text,
                )
                return result.stdout.strip() if text else result.stdout

            coordinates = json.loads((ROOT / COORDINATE_PATH).read_text())
            governance = coordinates["governance"]
            governance["tag_object"] = git(
                "rev-parse", "refs/tags/governance-v2.1.0"
            )
            governance["source_commit"] = git("rev-parse", "HEAD")
            governance["source_tree"] = git("rev-parse", "HEAD^{tree}")
            archive = git("archive", "--format=tar", "HEAD", text=False)
            assert isinstance(archive, bytes)
            governance["git_archive_sha256"] = "sha256:" + sha256(archive).hexdigest()

            validate_governance_source(root, coordinates)
            governance["source_tree"] = "0" * 40
            with self.assertRaisesRegex(ReceivedContractError, "accepted tree"):
                validate_governance_source(root, coordinates)

    def test_selected_future_identity_binds_release_and_closure_artifact(self) -> None:
        with tempfile.TemporaryDirectory(prefix="received-selected-future-") as directory:
            root = Path(directory)
            artifact = root / "release" / "future-reality-2028-06-30-v1.json"
            artifact.parent.mkdir(parents=True)
            governance_closure = {
                "closure_id": "CLOSURE-SIM-SUBSTANTIVE-2028-V1",
                "closure_status": "closed_in_simulation",
                "evidence_mode": "simulated",
                "aggregate_outcome": {
                    "closed_family_count": 4,
                    "expected_family_count": 4,
                    "result": "passed",
                },
                "receipt_closures": [
                    {"family": family, "outcome": "passed"}
                    for family in (
                        "configured_vendor_environments",
                        "representative_migration_restore_rehearsals",
                        "production_security_observability",
                        "accountable_scientific_quality_regulatory_acceptance",
                    )
                ],
                "environment_observed_closure": "separate_unasserted_state",
                "production_authorization_effect": "none",
            }
            closure_digest = "sha256:" + sha256(
                json.dumps(
                    governance_closure,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("utf-8")
            ).hexdigest()
            bundle = {
                "bundle_version": "2.0.1",
                "future_reality_version": "future-reality-2028-06-30-v1",
                "governance_closure": governance_closure,
                "governance_closure_digest": closure_digest,
                "detailed_receipts": [],
                "source_result_digest": "sha256:" + "1" * 64,
            }
            artifact.write_text(
                json.dumps(bundle, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            for command in (
                ["git", "init", "--quiet"],
                ["git", "config", "user.name", "Coordinate Test"],
                ["git", "config", "user.email", "coordinate-test@example.invalid"],
                ["git", "add", artifact.relative_to(root).as_posix()],
                ["git", "commit", "--quiet", "-m", "Selected future source"],
                [
                    "git",
                    "tag",
                    "--annotate",
                    "forecast-2028-FR-v1",
                    "--message",
                    "Selected future",
                ],
            ):
                subprocess.run(command, cwd=root, check=True)

            def git(*arguments: str, text: bool = True) -> str | bytes:
                result = subprocess.run(
                    ["git", *arguments],
                    cwd=root,
                    check=True,
                    capture_output=True,
                    text=text,
                )
                return result.stdout.strip() if text else result.stdout

            coordinates = json.loads((ROOT / COORDINATE_PATH).read_text())
            coordinates["selected_future"]["canonical_closure_digest"] = closure_digest
            source = coordinates["selected_future"]["accepted_sources"][0]

            def bind_current_release() -> None:
                source["tag_object"] = git(
                    "rev-parse", "refs/tags/forecast-2028-FR-v1"
                )
                source["source_commit"] = git("rev-parse", "HEAD")
                source["source_tree"] = git("rev-parse", "HEAD^{tree}")
                archive = git("archive", "--format=tar", "HEAD", text=False)
                assert isinstance(archive, bytes)
                source["git_archive_sha256"] = (
                    "sha256:" + sha256(archive).hexdigest()
                )

            def retag_head() -> None:
                subprocess.run(
                    ["git", "tag", "--delete", "forecast-2028-FR-v1"],
                    cwd=root,
                    check=True,
                    capture_output=True,
                )
                subprocess.run(
                    [
                        "git",
                        "tag",
                        "--annotate",
                        "forecast-2028-FR-v1",
                        "--message",
                        "Selected future",
                    ],
                    cwd=root,
                    check=True,
                    capture_output=True,
                )
                bind_current_release()

            bind_current_release()

            validate_selected_future_source(
                root,
                coordinates,
                role="simulated_final_state",
            )

            artifact.write_text('{"worktree": "mutable"}\n', encoding="utf-8")
            validate_selected_future_source(
                root,
                coordinates,
                role="simulated_final_state",
            )

            source["source_tree"] = "0" * 40
            with self.assertRaisesRegex(ReceivedContractError, "accepted tree"):
                validate_selected_future_source(
                    root,
                    coordinates,
                    role="simulated_final_state",
                )
            source["source_tree"] = git("rev-parse", "HEAD^{tree}")

            changed_bundle = deepcopy(bundle)
            changed_bundle["governance_closure"]["aggregate_outcome"][
                "result"
            ] = "changed"
            artifact.write_text(
                json.dumps(changed_bundle, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            subprocess.run(
                ["git", "add", artifact.relative_to(root).as_posix()],
                cwd=root,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "--quiet", "-m", "Closure digest drift"],
                cwd=root,
                check=True,
            )
            retag_head()
            with self.assertRaisesRegex(
                ReceivedContractError, "bundle governance_closure_digest"
            ):
                validate_selected_future_source(
                    root,
                    coordinates,
                    role="simulated_final_state",
                )

            artifact.write_text(
                '{"governance_closure": {}, "governance_closure": {}}\n',
                encoding="utf-8",
            )
            subprocess.run(
                ["git", "add", artifact.relative_to(root).as_posix()],
                cwd=root,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "--quiet", "-m", "Malformed closure bundle"],
                cwd=root,
                check=True,
            )
            retag_head()
            with self.assertRaisesRegex(
                ReceivedContractError, "duplicate-free finite UTF-8 JSON"
            ):
                validate_selected_future_source(
                    root,
                    coordinates,
                    role="simulated_final_state",
                )

    def test_installed_program_accepts_the_exact_distribution_and_import(self) -> None:
        coordinates = load_coordinates(ROOT)
        with tempfile.TemporaryDirectory(prefix="installed-program-") as directory:
            distribution, contracts = self._installed_fixture(Path(directory))
            with (
                patch(
                    "scripts.validate_received_contracts.metadata.distribution",
                    return_value=distribution,
                ),
                patch(
                    "scripts.validate_received_contracts.import_module",
                    return_value=contracts,
                ),
            ):
                validate_installed_program(coordinates)

    def test_installed_program_rejects_material_provenance_and_behavior_drift(
        self,
    ) -> None:
        coordinates = load_coordinates(ROOT)
        exact_commit = coordinates["program_contract"]["source_commit"]
        valid_record = {
            "url": (
                "https://github.com/driftframestudios/"
                "lims-eln-program-specification.git"
            ),
            "vcs_info": {
                "vcs": "git",
                "requested_revision": exact_commit,
                "commit_id": exact_commit,
            },
        }
        cases = {
            "missing PEP 610 record": {
                "direct_url_text": "__MISSING__",
                "message": "requires its PEP 610",
            },
            "malformed PEP 610 record": {
                "direct_url_text": "{",
                "message": "requires valid JSON",
            },
            "different source URL": {
                "record_change": ("url", "https://example.invalid/fork.git"),
                "message": "source URL",
            },
            "different requested revision": {
                "vcs_change": ("requested_revision", "0" * 40),
                "message": "requested revision",
            },
            "different commit": {
                "vcs_change": ("commit_id", "0" * 40),
                "message": "installed Program commit",
            },
            "shadow import": {
                "shadow_import": True,
                "message": "reviewed distribution owner",
            },
            "operation drift": {
                "operation_count": 2,
                "message": "operation count",
            },
            "scenario drift": {
                "scenario_id": "SCN-DIFFERENT",
                "message": "Golden Specimen scenario",
            },
            "schema inventory drift": {
                "schema_count": 6,
                "message": "schema inventory count",
            },
            "schema shape drift": {
                "schema_is_object": False,
                "message": "requires one JSON object",
            },
        }

        for label, case in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory(
                prefix="installed-program-drift-"
            ) as directory:
                fixture_arguments = {
                    key: value
                    for key, value in case.items()
                    if key
                    in {
                        "operation_count",
                        "scenario_id",
                        "schema_count",
                        "schema_is_object",
                        "shadow_import",
                    }
                }
                record = deepcopy(valid_record)
                if "record_change" in case:
                    key, value = case["record_change"]
                    record[key] = value
                if "vcs_change" in case:
                    key, value = case["vcs_change"]
                    record["vcs_info"][key] = value
                if case.get("direct_url_text") == "__MISSING__":
                    direct_url_text = None
                elif "direct_url_text" in case:
                    direct_url_text = case["direct_url_text"]
                else:
                    direct_url_text = json.dumps(record)

                distribution, contracts = self._installed_fixture(
                    Path(directory),
                    direct_url_text=direct_url_text,
                    **fixture_arguments,
                )
                if case.get("direct_url_text") == "__MISSING__":
                    distribution.read_text = lambda name: None
                with (
                    patch(
                        "scripts.validate_received_contracts.metadata.distribution",
                        return_value=distribution,
                    ),
                    patch(
                        "scripts.validate_received_contracts.import_module",
                        return_value=contracts,
                    ),
                    self.assertRaisesRegex(ReceivedContractError, case["message"]),
                ):
                    validate_installed_program(coordinates)


if __name__ == "__main__":
    unittest.main()
