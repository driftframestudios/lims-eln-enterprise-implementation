#!/usr/bin/env python3
"""Build or verify the repository-owned 0.3.1 inspection inventory."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path("release/public-inspection-manifest.json")
CANONICALIZATION = "ordered-path-nul-sha256-lf-v1"

ARTIFACT_GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "runtime_source",
        "FastAPI, domain, adapter, and package source that defines executable behavior.",
        (
            "pyproject.toml",
            "src/lims_eln_implementation/**/*.py",
            "src/lims_eln_implementation/workbench/static/*",
            "src/lims_eln_implementation/workbench/templates/*",
        ),
    ),
    (
        "database_evolution",
        "Flyway V001 through V005, its bounded identity, and deployment-shape database support.",
        (
            "flyway.conf",
            "database/*.json",
            "database/*.sql",
            "sql/*.sql",
            "infra/docker-compose.yml",
            "infra/migrator.Dockerfile",
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
            ".github/workflows/ci.yml",
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
            ".github/dependabot.manual.yml",
            ".github/pull_request_template.md",
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
    groups: list[dict[str, Any]] = []
    all_artifacts: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    for name, responsibility, patterns in ARTIFACT_GROUPS:
        artifacts: list[dict[str, Any]] = []
        for relative_path in _group_paths(root, patterns):
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
        "repository_release": "0.3.1",
        "release_state": "repository_owned_candidate",
        "canonicalization": CANONICALIZATION,
        "source_identity": {
            "kind": "content_addressed_artifact_inventory",
            "aggregate_sha256": _aggregate(all_artifacts),
        },
        "coordinate_boundaries": [
            {
                "role": "program_contract",
                "declared_compatibility": ">=0.3.1,<0.4",
                "coordinate_state": "awaiting_accepted_revision",
            },
            {
                "role": "governance_schema",
                "declared_release": "2.0.1",
                "coordinate_state": "awaiting_accepted_revision",
            },
        ],
        "evidence_boundary": {
            "repository_owned_candidate": (
                "The inventory establishes the exact local bytes available for review."
            ),
            "configured_environment": (
                "Environment receipts retain their named system, time, performer, reviewer, "
                "artifact bindings, assurance stage, and limitations."
            ),
            "promotion": (
                "The release steward adds accepted Git and dependency coordinates after "
                "their receiving reviews settle."
            ),
        },
        "manifest_carriers": [
            "manifest.json",
            "release/repository-role.json",
        ],
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

    return "inspection manifest metadata differs from the repository-owned candidate"


def verify_manifest(root: Path = ROOT) -> dict[str, Any]:
    manifest_path = root / MANIFEST_PATH
    try:
        actual = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as error:
        raise InspectionManifestError(
            "inspection manifest requires a readable JSON document"
        ) from error
    expected = build_manifest(root)
    if actual != expected:
        raise InspectionManifestError(_difference(expected, actual))
    return actual


def _serialize(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build or verify the repository-owned public inspection manifest."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    arguments = parser.parse_args()

    if arguments.write:
        destination = ROOT / MANIFEST_PATH
        destination.write_text(_serialize(build_manifest(ROOT)), encoding="utf-8")
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
