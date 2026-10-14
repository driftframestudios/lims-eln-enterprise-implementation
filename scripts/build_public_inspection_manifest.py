#!/usr/bin/env python3
"""Build or verify the repository-owned post-release development inventory."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import stat
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path("release/public-inspection-manifest.json")
EXTERNAL_COORDINATE_PATH = Path("release/external-contract-coordinates.json")
PROMOTION_RECEIPT_PATH = Path("receipts/promotion-receipt.json")
PROMOTION_CANDIDATE_PATH = Path("receipts/promotion-candidate.json")
PROMOTION_OBSERVATION_PATH = Path("receipts/promotion-observation-v0.3.2.json")
CANONICALIZATION = "ordered-path-nul-sha256-lf-v1"
MANIFEST_CARRIER_PATHS = (
    "manifest.json",
    "release/repository-role.json",
    PROMOTION_CANDIDATE_PATH.as_posix(),
)

ARTIFACT_GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "runtime_source",
        "FastAPI, domain, adapter, and package source that defines executable behavior.",
        (
            "pyproject.toml",
            "uv.lock",
            ".python-version",
            "src/lims_eln_implementation/**/*.py",
            "src/lims_eln_implementation/workbench/static/*",
            "src/lims_eln_implementation/workbench/templates/*",
        ),
    ),
    (
        "database_evolution",
        "Flyway V001 through V007, its bounded identity, and deployment-shape database support.",
        (
            "flyway.conf",
            "database/*.json",
            "database/*.sql",
            "sql/*.sql",
            "infra/docker-compose.yml",
            "infra/migrator.Dockerfile",
            "infra/application.Dockerfile",
            "infra/*.sh",
            "infra/postgres-init/*.sh",
        ),
    ),
    (
        "contracts_and_synthetic_inputs",
        (
            "Versioned local contracts and invented inputs used to preserve "
            "exact scientific values and lineage."
        ),
        (
            "contracts/*.json",
            "fixtures/synthetic/*.json",
            "release/bounded-caller-bindings.json",
            "release/external-contract-coordinates.json",
        ),
    ),
    (
        "operational_configuration",
        (
            "Runtime, telemetry, infrastructure, and exclusion configuration "
            "that shapes deployment and protected-material handling."
        ),
        (
            ".dockerignore",
            ".gitignore",
            "infra/otel-collector.yaml",
            "infra/secrets/.gitignore",
            "infra/terraform/*.tf",
        ),
    ),
    (
        "behavior_proofs",
        (
            "Repository validation and tests for tenant isolation, scientific "
            "correctness, replay, recovery, and delivery evidence."
        ),
        (
            "Makefile",
            "scripts/*.py",
            "tests/*.py",
            ".github/workflows/*.yml",
        ),
    ),
    (
        "evidence_records",
        (
            "Synthetic verification records whose own mode, stage, environment, "
            "and limitations define their evidence reach."
        ),
        (
            "receipts/*.json",
        ),
    ),
    (
        "collaboration_and_orientation",
        "Public orientation, release guidance, ownership, provenance, and operational runbooks.",
        (
            "README.md",
            "AGENTS.md",
            "AUTHORS",
            "CHANGELOG.md",
            "CONTRIBUTING.md",
            "LICENSE",
            "NOTICE.md",
            "SECURITY.md",
            "provenance.json",
            "machine-node.json",
            "first-receipt.json",
            "COORDINATION-HORIZON.json",
            "release/seed-lineage-machine-node-v0.2.json",
            "docs/**/*.md",
            "infra/README.md",
            ".github/AUTOMATION.md",
            ".github/CODEOWNERS",
            ".github/dependabot.yml",
            ".github/pull_request_template.md",
            ".agents/skills/README.md",
            ".agents/skills/*/SKILL.md",
        ),
    ),
)


class InspectionManifestError(ValueError):
    """The checked-in inventory differs from repository-owned source."""


def _digest(path: Path) -> str:
    return "sha256:" + sha256(path.read_bytes()).hexdigest()


def _safe_file(root: Path, relative_path: str) -> Path:
    pure_path = PurePosixPath(relative_path)
    if (
        pure_path.is_absolute()
        or not pure_path.parts
        or any(part in {"", ".", ".."} for part in pure_path.parts)
        or pure_path.as_posix() != relative_path
    ):
        raise InspectionManifestError(
            "inspection artifact path requires normalized repository-relative form: "
            f"{relative_path!r}"
        )

    root_resolved = root.resolve(strict=True)
    candidate = root.joinpath(*pure_path.parts)
    cursor = root
    for part in pure_path.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise InspectionManifestError(
                f"inspection artifact path crosses a symbolic link: {relative_path}"
            )
    try:
        candidate.resolve(strict=True).relative_to(root_resolved)
    except (FileNotFoundError, ValueError) as error:
        raise InspectionManifestError(
            "inspection artifact stays within the repository and resolves to a file: "
            f"{relative_path}"
        ) from error
    if not candidate.is_file():
        raise InspectionManifestError(
            f"inspection artifact requires a regular file: {relative_path}"
        )
    return candidate


def _group_paths(root: Path, patterns: tuple[str, ...]) -> list[str]:
    paths: set[str] = set()
    for pattern in patterns:
        matches = sorted(path for path in root.glob(pattern) if path.is_file())
        if not matches:
            raise InspectionManifestError(
                f"inspection artifact selector requires at least one file: {pattern}"
            )
        for path in matches:
            relative_path = path.relative_to(root).as_posix()
            _safe_file(root, relative_path)
            paths.add(relative_path)
    return sorted(paths)


def _aggregate(artifacts: list[dict[str, Any]]) -> str:
    payload = "".join(
        f"{artifact['path']}\0{artifact['sha256']}\n" for artifact in artifacts
    ).encode("utf-8")
    return "sha256:" + sha256(payload).hexdigest()


def build_manifest(root: Path = ROOT) -> dict[str, Any]:
    coordinate_path = _safe_file(root, EXTERNAL_COORDINATE_PATH.as_posix())
    try:
        coordinates = json.loads(coordinate_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise InspectionManifestError(
            "external coordinates require one UTF-8 JSON document"
        ) from error
    program = coordinates["program_contract"]
    governance = coordinates["governance"]
    selected_future = coordinates["selected_future"]
    comparison_return = coordinates["comparison_return"]
    coordinate_digest = _digest(coordinate_path)

    promotion_path = _safe_file(root, PROMOTION_RECEIPT_PATH.as_posix())
    try:
        promotion = json.loads(promotion_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise InspectionManifestError(
            "promotion receipt requires one UTF-8 JSON document"
        ) from error
    release_coordinate = promotion.get("release_coordinate")
    if (
        promotion.get("promotion_state") != "release_observed"
        or not isinstance(release_coordinate, dict)
    ):
        raise InspectionManifestError(
            "candidate history requires the observed prior-release promotion receipt"
        )

    observation_path = _safe_file(root, PROMOTION_OBSERVATION_PATH.as_posix())
    try:
        observation = json.loads(observation_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise InspectionManifestError(
            "promotion observation requires one UTF-8 JSON document"
        ) from error
    observed_release_coordinate = observation.get("release_coordinate")
    if (
        observation.get("promotion_state") != "release_observed"
        or not isinstance(observed_release_coordinate, dict)
    ):
        raise InspectionManifestError(
            "release inventory requires the observed 0.3.2 promotion receipt"
        )

    groups: list[dict[str, Any]] = []
    all_artifacts: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    for name, responsibility, patterns in ARTIFACT_GROUPS:
        artifacts: list[dict[str, Any]] = []
        for relative_path in _group_paths(root, patterns):
            if relative_path in MANIFEST_CARRIER_PATHS:
                continue
            if relative_path in seen_paths:
                raise InspectionManifestError(
                    f"inspection artifact belongs to one group: {relative_path}"
                )
            seen_paths.add(relative_path)
            path = _safe_file(root, relative_path)
            artifact = {
                "path": relative_path,
                "sha256": _digest(path),
                "size_bytes": path.stat().st_size,
            }
            artifacts.append(artifact)
            all_artifacts.append(artifact)
        groups.append(
            {
                "name": name,
                "responsibility": responsibility,
                "aggregate_sha256": _aggregate(artifacts),
                "artifacts": artifacts,
            }
        )

    return {
        "schema_version": "1.0.0",
        "repository": "lims-eln-enterprise-implementation",
        "repository_release": "0.3.2",
        "release_state": "post_release_development_carrier",
        "canonicalization": CANONICALIZATION,
        "source_identity": {
            "kind": "content_addressed_artifact_inventory",
            "aggregate_sha256": _aggregate(all_artifacts),
        },
        "release_subject": observed_release_coordinate,
        "prior_release_subject": {
            "promotion_receipt": PROMOTION_RECEIPT_PATH.as_posix(),
            "tag": release_coordinate["tag"],
            "tag_object_oid": release_coordinate["tag_object_oid"],
            "commit_oid": release_coordinate["commit_oid"],
            "tree_oid": release_coordinate["tree_oid"],
            "archive_digest": release_coordinate["archive_digest"],
        },
        "coordinate_boundaries": [
            {
                "role": "program_contract",
                "coordinate_manifest": EXTERNAL_COORDINATE_PATH.as_posix(),
                "coordinate_manifest_sha256": coordinate_digest,
                "declared_release": program["package_version"],
                "accepted_revision": program["source_commit"],
                "source_digest": program["source_identity"]["digest"],
                "coordinate_state": "accepted_source_consumer_observed",
            },
            {
                "role": "governance_schema",
                "coordinate_manifest": EXTERNAL_COORDINATE_PATH.as_posix(),
                "coordinate_manifest_sha256": coordinate_digest,
                "declared_release": governance["release"],
                "schema_release": governance["schema_release"],
                "accepted_revision": governance["source_commit"],
                "coordinate_state": "accepted_release",
            },
            *[
                {
                    "role": source["role"],
                    "coordinate_manifest": EXTERNAL_COORDINATE_PATH.as_posix(),
                    "coordinate_manifest_sha256": coordinate_digest,
                    "declared_release": source["release"],
                    "accepted_revision": source["source_commit"],
                    "accepted_tree": source["source_tree"],
                    "tag_object_oid": source["tag_object"],
                    "archive_digest": source["git_archive_sha256"],
                    "closure_artifact_path": source["closure_artifact_path"],
                    "canonical_closure_digest": selected_future[
                        "canonical_closure_digest"
                    ],
                    "coordinate_state": "accepted_release",
                }
                for source in selected_future["accepted_sources"]
            ],
            {
                "role": "comparison_return",
                "coordinate_manifest": EXTERNAL_COORDINATE_PATH.as_posix(),
                "coordinate_manifest_sha256": coordinate_digest,
                "declared_release": comparison_return["comparison_release"]["release"],
                "accepted_revision": comparison_return["comparison_release"]["source_commit"],
                "accepted_tree": comparison_return["comparison_release"]["source_tree"],
                "tag_object_oid": comparison_return["comparison_release"]["tag_object"],
                "archive_digest": comparison_return["comparison_release"]["git_archive_sha256"],
                "observation_carrier_revision": comparison_return["observation_carrier"][
                    "source_commit"
                ],
                "record_carrier_revision": comparison_return["publication"][
                    "record_carrier_commit"
                ],
                "report_digest": comparison_return["golden_specimen_report"]["report_digest"],
                "classification_counts": comparison_return["golden_specimen_report"][
                    "classification_counts"
                ],
                "material_divergence_paths": comparison_return["golden_specimen_report"][
                    "material_divergence_paths"
                ],
                "material_divergence_receiver": comparison_return["golden_specimen_report"][
                    "material_divergence_receiver"
                ],
                "docs_revision": comparison_return["publication"]["docs_revision"],
                "projection_manifest_sha256": comparison_return["publication"][
                    "projection_manifest_sha256"
                ],
                "canonical_origin": comparison_return["publication"]["canonical_origin"],
                "coordinate_state": "accepted_return",
            },
        ],
        "evidence_boundary": {
            "repository_owned_inspection": (
                "The inventory establishes the exact post-release development bytes "
                "carried above the observed 0.3.2 release coordinate and its retained "
                "evidence."
            ),
            "configured_environment": (
                "Environment receipts retain their named system, time, performer, reviewer, "
                "artifact bindings, assurance stage, and limitations."
            ),
            "promotion": (
                "The 0.3.2 observation records the accepted immutable coordinate. The "
                "0.3.2 candidate and prior 0.3.1 receipt retain their original evidence roles."
            ),
        },
        "manifest_carriers": list(MANIFEST_CARRIER_PATHS),
        "artifact_groups": groups,
    }


def _difference(expected: dict[str, Any], actual: dict[str, Any]) -> str:
    expected_groups = expected.get("artifact_groups", [])
    actual_groups = actual.get("artifact_groups", [])
    expected_names = [group.get("name") for group in expected_groups]
    actual_names = [group.get("name") for group in actual_groups]
    if expected_names != actual_names:
        return "inspection artifact groups differ from the released group order"

    for expected_group, actual_group in zip(expected_groups, actual_groups):
        name = expected_group["name"]
        expected_artifacts = expected_group.get("artifacts", [])
        actual_artifacts = actual_group.get("artifacts", [])
        expected_paths = [artifact.get("path") for artifact in expected_artifacts]
        actual_paths = [artifact.get("path") for artifact in actual_artifacts]
        if expected_paths != actual_paths:
            return f"inspection artifact paths differ for {name}"
        for expected_artifact, actual_artifact in zip(
            expected_artifacts, actual_artifacts
        ):
            if expected_artifact != actual_artifact:
                return (
                    "inspection artifact bytes differ for "
                    f"{expected_artifact['path']}"
                )
        if expected_group != actual_group:
            return f"inspection artifact group metadata differs for {name}"

    return "inspection manifest metadata differs from the repository-owned inspection state"


def verify_manifest(root: Path = ROOT) -> dict[str, Any]:
    manifest_bytes = _read_manifest_bytes(root)
    try:
        actual = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InspectionManifestError(
            "inspection manifest requires one UTF-8 JSON document"
        ) from error
    expected = build_manifest(root)
    if actual != expected:
        raise InspectionManifestError(_difference(expected, actual))
    if manifest_bytes != _serialize(expected).encode("utf-8"):
        raise InspectionManifestError(
            "inspection manifest bytes require the canonical sorted, indented JSON form"
        )
    return actual


def _serialize(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def _manifest_parent_fd(root: Path) -> tuple[Path, int]:
    root_resolved = root.resolve(strict=True)
    parent = root / MANIFEST_PATH.parent
    if parent.is_symlink():
        raise InspectionManifestError(
            "inspection manifest parent stays within a regular repository directory"
        )
    try:
        parent.resolve(strict=True).relative_to(root_resolved)
    except (FileNotFoundError, ValueError) as error:
        raise InspectionManifestError(
            "inspection manifest parent stays within a regular repository directory"
        ) from error
    if not parent.is_dir():
        raise InspectionManifestError(
            "inspection manifest parent stays within a regular repository directory"
        )

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        return parent, os.open(parent, flags)
    except OSError as error:
        raise InspectionManifestError(
            "inspection manifest parent stays within a regular repository directory"
        ) from error


def _read_manifest_bytes(root: Path) -> bytes:
    _, parent_fd = _manifest_parent_fd(root)
    file_fd: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            file_fd = os.open(MANIFEST_PATH.name, flags, dir_fd=parent_fd)
        except OSError as error:
            raise InspectionManifestError(
                "inspection manifest requires a regular repository-owned file"
            ) from error
        if not stat.S_ISREG(os.fstat(file_fd).st_mode):
            raise InspectionManifestError(
                "inspection manifest requires a regular repository-owned file"
            )
        with os.fdopen(file_fd, "rb") as handle:
            file_fd = None
            return handle.read()
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(parent_fd)


def write_manifest(root: Path = ROOT) -> Path:
    payload = _serialize(build_manifest(root)).encode("utf-8")
    parent, parent_fd = _manifest_parent_fd(root)
    temporary_name = f".{MANIFEST_PATH.name}.{secrets.token_hex(8)}.tmp"
    temporary_fd: int | None = None
    temporary_exists = False
    try:
        try:
            destination_stat = os.stat(
                MANIFEST_PATH.name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            destination_stat = None
        if destination_stat is not None and not stat.S_ISREG(destination_stat.st_mode):
            raise InspectionManifestError(
                "inspection manifest write target requires a regular repository-owned file"
            )

        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
        )
        temporary_fd = os.open(
            temporary_name,
            flags,
            0o644,
            dir_fd=parent_fd,
        )
        temporary_exists = True
        with os.fdopen(temporary_fd, "wb") as handle:
            temporary_fd = None
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())

        try:
            destination_stat = os.stat(
                MANIFEST_PATH.name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            destination_stat = None
        if destination_stat is not None and not stat.S_ISREG(destination_stat.st_mode):
            raise InspectionManifestError(
                "inspection manifest write target requires a regular repository-owned file"
            )

        os.replace(
            temporary_name,
            MANIFEST_PATH.name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        temporary_exists = False
        os.fsync(parent_fd)
        return parent / MANIFEST_PATH.name
    finally:
        if temporary_fd is not None:
            os.close(temporary_fd)
        if temporary_exists:
            try:
                os.unlink(temporary_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        os.close(parent_fd)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build or verify the repository-owned public inspection manifest."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    arguments = parser.parse_args()

    if arguments.write:
        destination = write_manifest(ROOT)
        print(f"wrote {destination.relative_to(ROOT)}")
    else:
        manifest = verify_manifest(ROOT)
        print(
            "verified "
            f"{MANIFEST_PATH.as_posix()} "
            f"{manifest['source_identity']['aggregate_sha256']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
