"""Git-carried evidence tests for the accepted Comparison return."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.validate_received_contracts import (
    ReceivedContractError,
    load_coordinates,
    validate_comparison_return_source,
)


ROOT = Path(__file__).resolve().parents[1]


def _git(root: Path, *arguments: str, text: bool = True) -> str | bytes:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=text,
    )
    return result.stdout.strip() if text else result.stdout


def _write_json(root: Path, relative_path: str, value: object) -> bytes:
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload


class ComparisonReturnTests(unittest.TestCase):
    def _build_evidence_repository(self, root: Path) -> dict:
        for arguments in (
            ("init", "--quiet", "--initial-branch=main"),
            ("config", "user.name", "Coordinate Test"),
            ("config", "user.email", "coordinate-test@example.invalid"),
        ):
            _git(root, *arguments)

        coordinates = deepcopy(load_coordinates(ROOT))
        returned = coordinates["comparison_return"]
        report_coordinate = returned["golden_specimen_report"]
        publication = returned["publication"]

        compared = returned["compared_implementation_release"]
        lock = {
            "implementation": {
                "release": compared["tag"],
                "tag_object_oid": compared["tag_object"],
                "commit": compared["source_commit"],
                "digest": "git-tree-sha1:" + compared["source_tree"],
                "archive_digest": compared["git_archive_sha256"],
            }
        }
        _write_json(root, "constellation.lock.json", lock)
        _git(root, "add", "constellation.lock.json")
        _git(root, "commit", "--quiet", "-m", "Comparison release")
        _git(
            root,
            "tag",
            "--annotate",
            "comparison-v-test",
            "--message",
            "Comparison test release",
        )

        release = returned["comparison_release"]
        release["release"] = "comparison-v-test"
        release["tag_object"] = _git(root, "rev-parse", "refs/tags/comparison-v-test")
        release["source_commit"] = _git(root, "rev-parse", "HEAD")
        release["source_tree"] = _git(root, "rev-parse", "HEAD^{tree}")
        archive = _git(root, "archive", "--format=tar", "HEAD", text=False)
        assert isinstance(archive, bytes)
        release["git_archive_sha256"] = "sha256:" + sha256(archive).hexdigest()

        receipt = {
            "repository": returned["repository"],
            "target_release": release["release"],
            "promotion_state": "release_observed",
            "release_coordinate": {
                "tag": release["release"],
                "tag_object_oid": release["tag_object"],
                "commit_oid": release["source_commit"],
                "tree_oid": release["source_tree"],
                "archive_digest": release["git_archive_sha256"],
            },
        }
        receipt_path = returned["observation_carrier"]["receipt_path"]
        receipt_bytes = _write_json(root, receipt_path, receipt)
        _git(root, "add", receipt_path)
        _git(root, "commit", "--quiet", "-m", "Comparison observation")
        observation_commit = _git(root, "rev-parse", "HEAD")
        returned["observation_carrier"].update(
            {
                "source_commit": observation_commit,
                "receipt_file_sha256": "sha256:" + sha256(receipt_bytes).hexdigest(),
            }
        )

        comparisons = [
            {"path": path, "classification": "material_divergence"}
            for path in report_coordinate["material_divergence_paths"]
        ]
        comparisons[0]["rationale"] = "Observed concentration is 12 µg/L"
        report = {
            "summary": {
                "leaf_paths_compared": report_coordinate["leaf_paths_compared"],
                "classification_counts": report_coordinate["classification_counts"],
            },
            "comparisons": comparisons,
        }
        canonical_report = json.dumps(
            report,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        report_coordinate["report_digest"] = "sha256:" + sha256(
            canonical_report
        ).hexdigest()
        report["report_digest"] = report_coordinate["report_digest"]
        _git(root, "switch", "--quiet", "-c", "docs", release["source_commit"])
        _write_json(root, report_coordinate["report_path"], report)
        manifest = {
            "sourceRevision": observation_commit,
            "goldenSpecimenReportDigest": report_coordinate["report_digest"],
            "canonicalOrigin": publication["canonical_origin"],
        }
        manifest_bytes = _write_json(root, publication["projection_manifest_path"], manifest)
        _git(root, "add", report_coordinate["report_path"], publication["projection_manifest_path"])
        _git(root, "commit", "--quiet", "-m", "Comparison projection")
        publication.update(
            {
                "source_revision": observation_commit,
                "docs_revision": _git(root, "rev-parse", "HEAD"),
                "projection_manifest_sha256": ("sha256:" + sha256(manifest_bytes).hexdigest()),
            }
        )

        _git(root, "switch", "--quiet", "main")
        role = {
            "repository_release": "0.3.2",
            "golden_specimen_verification": {
                "report_digest": report_coordinate["report_digest"],
                "classification_counts": report_coordinate["classification_counts"],
            },
            "publication_coordinates": {
                "source_revision": publication["source_revision"],
                "docs_revision": publication["docs_revision"],
                "projection_manifest_sha256": publication["projection_manifest_sha256"],
                "canonical_origin": publication["canonical_origin"],
            },
        }
        _write_json(root, "release/repository-role.json", role)
        _git(root, "add", "release/repository-role.json")
        _git(root, "commit", "--quiet", "-m", "Comparison publication record")
        publication["record_carrier_commit"] = _git(root, "rev-parse", "HEAD")
        return coordinates

    def test_return_binds_release_observation_report_and_projection(self) -> None:
        with tempfile.TemporaryDirectory(prefix="comparison-return-") as directory:
            root = Path(directory)
            coordinates = self._build_evidence_repository(root)

            validate_comparison_return_source(root, coordinates)

            receipt_path = coordinates["comparison_return"]["observation_carrier"]["receipt_path"]
            (root / receipt_path).write_text('{"worktree": "mutable"}\n', encoding="utf-8")
            validate_comparison_return_source(root, coordinates)

            changed = deepcopy(coordinates)
            changed["comparison_return"]["publication"]["source_revision"] = "0" * 40
            with self.assertRaisesRegex(
                ReceivedContractError, "record publication source_revision"
            ):
                validate_comparison_return_source(root, changed)

    def test_return_requires_observation_to_record_ancestry(self) -> None:
        with tempfile.TemporaryDirectory(prefix="comparison-return-lineage-") as directory:
            root = Path(directory)
            coordinates = self._build_evidence_repository(root)
            returned = coordinates["comparison_return"]
            returned["observation_carrier"]["source_commit"] = returned["publication"][
                "docs_revision"
            ]

            with self.assertRaisesRegex(ReceivedContractError, "record carrier"):
                validate_comparison_return_source(root, coordinates)

    def test_return_reproduces_report_digest_from_committed_semantics(self) -> None:
        with tempfile.TemporaryDirectory(prefix="comparison-return-report-") as directory:
            root = Path(directory)
            coordinates = self._build_evidence_repository(root)
            returned = coordinates["comparison_return"]
            report_coordinate = returned["golden_specimen_report"]
            publication = returned["publication"]

            _git(root, "switch", "--quiet", "docs")
            report_path = root / report_coordinate["report_path"]
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["comparisons"][0]["rationale"] = "Changed committed meaning"
            _write_json(root, report_coordinate["report_path"], report)
            _git(root, "add", report_coordinate["report_path"])
            _git(root, "commit", "--quiet", "-m", "Change report without digest")
            publication["docs_revision"] = _git(root, "rev-parse", "HEAD")

            _git(root, "switch", "--quiet", "main")
            role_path = root / "release/repository-role.json"
            role = json.loads(role_path.read_text(encoding="utf-8"))
            role["publication_coordinates"]["docs_revision"] = publication[
                "docs_revision"
            ]
            _write_json(root, "release/repository-role.json", role)
            _git(root, "add", "release/repository-role.json")
            _git(root, "commit", "--quiet", "-m", "Record changed projection")
            publication["record_carrier_commit"] = _git(root, "rev-parse", "HEAD")

            with self.assertRaisesRegex(ReceivedContractError, "reproduced digest"):
                validate_comparison_return_source(root, coordinates)


if __name__ == "__main__":
    unittest.main()
