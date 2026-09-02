#!/usr/bin/env python3
"""Validate contracts, synthetic posture, language, compilation, and tests."""

from __future__ import annotations

import ast
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
import unittest

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

PUBLISHED_SUFFIXES = {
    ".py",
    ".md",
    ".sql",
    ".json",
    ".yml",
    ".yaml",
    ".tf",
    ".toml",
    ".html",
    ".css",
    ".js",
}
HOUSE_SYNTAX = ("::" + "the_author::", "::" + "fragment")
HOUSE_DELIMITER = ";" + ";"
FRAGILE_COMMENT = re.compile(
    r"^\s*(?:#|//|--)\s*(?:DO NOT|DON'T|DONT|NEVER|AVOID)\b",
    re.IGNORECASE | re.MULTILINE,
)
CREDENTIAL_PATTERNS = {
    "AWS access key identifier": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "AWS secret access key assignment": re.compile(
        r"(?i)\baws_secret_access_key\b\s*[:=]\s*[\"']?[A-Za-z0-9/+=]{40}\b"
    ),
    "private key material": re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    ),
    "GitHub access token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b"),
    "Slack access token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "Stripe live key": re.compile(r"\b[sr]k_live_[0-9A-Za-z]{16,}\b"),
    "JSON Web Token": re.compile(
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
    ),
}
CANONICAL_RECEIPT_FAMILIES = (
    "configured_vendor_environments",
    "representative_migration_restore_rehearsals",
    "production_security_observability",
    "accountable_scientific_quality_regulatory_acceptance",
)
CANONICAL_SELECTED_FUTURE_CLOSURE_DIGEST = (
    "sha256:33bcc14da24309b7716728b3f0204008e8f7ebf58de75f9e40a5986b421f06b5"
)
REPOSITORY_RELEASE = "0.3.2"
CURRENT_PROMOTION_RECEIPT_ID = "RCP-IMPLEMENTATION-PROMOTION-004"
CURRENT_PROMOTION_CANDIDATE_PATH = Path("receipts/promotion-candidate.json")
CURRENT_PROMOTION_CANDIDATE_SCHEMA_PATH = Path(
    "contracts/promotion-candidate.v1.schema.json"
)
CURRENT_RELEASE_TAG = "v0.3.2"
PRIOR_PROMOTION_RECEIPT_ID = "RCP-IMPLEMENTATION-PROMOTION-003"
PRIOR_PROMOTION_RECEIPT_PATH = Path("receipts/promotion-receipt.json")
PRIOR_RELEASE_TAG = "v0.3.1"
REVIEWED_CANDIDATE_COMMIT = "a4982734fbfa7f8dbe81d41bbc8435ed66a96d46"
PRIOR_RELEASE_COMMIT = "44a4b8e67ff2e6af232b12daf3692bee8e8f3a3a"
PRIOR_RELEASE_TREE = "cc1bb335c0cdd1a37d1b6554480b3afdb9c9f360"
PRIOR_TAG_OBJECT = "8b1013ff6a116b64e5d31c2870b574f641ee88f6"
PRIOR_ARCHIVE_DIGEST = (
    "sha256:00da1be41bdf23a21124d600f3788464bfd8f590c819f6a9c74b98671edb2174"
)
REVIEWED_INSPECTION_MANIFEST_DIGEST = (
    "sha256:1e41212a2ca0cfe679ffc799bb08d1854300d57354364831b82390ab0133a12f"
)
EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".terraform",
    ".venv",
    "__pycache__",
    "build",
    "dist",
}


def is_generated_or_external(path: Path) -> bool:
    return any(
        part in EXCLUDED_DIRECTORY_NAMES or part.endswith(".egg-info")
        for part in path.parts
    )


def file_digest(path: Path) -> str:
    return f"sha256:{sha256(path.read_bytes()).hexdigest()}"


def load_json_files() -> list[Path]:
    paths = sorted(
        path for path in ROOT.rglob("*.json") if not is_generated_or_external(path)
    )
    for path in paths:
        with path.open(encoding="utf-8") as stream:
            json.load(stream)
    return paths


def validate_contracts() -> None:
    contract_paths = sorted((ROOT / "contracts").glob("*.schema.json"))
    if len(contract_paths) < 3:
        raise AssertionError("repository requires at least three versioned JSON contracts")
    for path in contract_paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise AssertionError(f"{path} requires JSON Schema 2020-12")
        if not document.get("$id") or not document.get("title"):
            raise AssertionError(f"{path} requires stable identity and title")


def validate_promotion_candidate_schema(
    candidate: dict,
    *,
    schema_path: Path | None = None,
) -> None:
    """Execute the candidate's declared JSON Schema against its exact document."""

    path = schema_path or (ROOT / CURRENT_PROMOTION_CANDIDATE_SCHEMA_PATH)
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
    except (OSError, UnicodeError, json.JSONDecodeError, SchemaError) as error:
        raise AssertionError(
            "promotion candidate schema requires valid JSON Schema 2020-12"
        ) from error

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(
        validator.iter_errors(candidate),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "$"
        raise AssertionError(
            "promotion candidate schema validation differs at "
            f"{location}: {first.message}"
        )


def validate_promotion_lifecycle(
    *,
    promotion: dict,
    candidate: dict,
    machine: dict,
    first_receipt: dict,
    horizon: dict,
    release: dict,
    inspection_manifest: dict,
) -> None:
    validate_promotion_candidate_schema(candidate)
    """Keep the prior signed subject distinct from the current patch candidate."""
    expected_keys = {
        "$schema",
        "schema_version",
        "promotion_receipt_id",
        "repository",
        "target_release",
        "promotion_state",
        "evidence_mode",
        "assurance_stage",
        "candidate_coordinate",
        "release_coordinate",
        "required_evidence",
        "limitations",
        "accountable_role",
        "metadata",
    }
    if set(promotion) != expected_keys:
        raise AssertionError("promotion receipt requires the released closed shape")
    if (
        promotion["$schema"] != "../contracts/promotion-receipt.v1.schema.json"
        or promotion["schema_version"] != "1.0.0"
        or promotion["promotion_receipt_id"] != PRIOR_PROMOTION_RECEIPT_ID
        or promotion["repository"]
        != "driftframestudios/lims-eln-enterprise-implementation"
        or promotion["target_release"] != PRIOR_RELEASE_TAG
        or promotion["promotion_state"] != "release_observed"
        or promotion["evidence_mode"] != "observed"
        or promotion["assurance_stage"] != "verified"
    ):
        raise AssertionError("prior promotion receipt requires the observed v0.3.1 identity")

    expected_candidate = {
        "release": "candidate-implementation-v0.3.1",
        "commit_oid": REVIEWED_CANDIDATE_COMMIT,
        "tree_oid": PRIOR_RELEASE_TREE,
        "public_inspection_manifest_digest": REVIEWED_INSPECTION_MANIFEST_DIGEST,
    }
    if promotion["candidate_coordinate"] != expected_candidate:
        raise AssertionError("promotion receipt requires the reviewed candidate coordinate")

    expected_release_coordinate = {
        "git_object_format": "sha1",
        "tag": PRIOR_RELEASE_TAG,
        "tag_object_oid": PRIOR_TAG_OBJECT,
        "commit_oid": PRIOR_RELEASE_COMMIT,
        "tree_oid": PRIOR_RELEASE_TREE,
        "archive_format": "git-tar",
        "archive_digest": PRIOR_ARCHIVE_DIGEST,
        "promoted_at": "2026-09-02T02:40:50Z",
        "pull_request": 23,
        "hosted_checks": [
            {
                "name": "Repository validation",
                "run_id": "33582958659",
                "conclusion": "success",
            },
            {
                "name": "branch-shape",
                "run_id": "33582958981",
                "conclusion": "success",
            },
        ],
        "local_proof_receipt": (
            "evidence://local/release-candidate/a498273/repository-validation"
        ),
        "ruleset_receipt": "governed://github/rulesets/19919124",
        "codeowner_resolution": (
            "evidence://collaboration/pull-23/human-codeowner-approval"
        ),
        "merge_signature_verification": "valid",
        "tag_signature_verification": "valid",
    }
    if promotion["release_coordinate"] != expected_release_coordinate:
        raise AssertionError("promotion receipt requires the observed tag coordinate")
    required_evidence = promotion["required_evidence"]
    limitations = promotion["limitations"]
    if (
        not isinstance(required_evidence, list)
        or len(required_evidence) < 4
        or any(
            not isinstance(item, str) or len(item) < 20
            for item in required_evidence
        )
        or len(set(required_evidence)) != len(required_evidence)
        or not isinstance(limitations, list)
        or not limitations
        or any(not isinstance(item, str) or len(item) < 20 for item in limitations)
        or len(set(limitations)) != len(limitations)
        or promotion["accountable_role"] != "Implementation release stewardship"
        or promotion["metadata"]
        != {
            "schema_version": "1.0.0",
            "created_at": "2026-09-02T02:42:44Z",
            "updated_at": "2026-09-02T02:42:44Z",
            "owner": {
                "actor_id": "OWNER-IMPLEMENTATION-PROMOTION-003",
                "display_name": "Implementation release stewardship role",
                "role": "Promotion receipt owner",
            },
        }
    ):
        raise AssertionError("promotion receipt requires material evidence and limitations")

    candidate_keys = {
        "$schema",
        "schema_version",
        "promotion_receipt_id",
        "repository",
        "target_release",
        "promotion_state",
        "evidence_mode",
        "assurance_stage",
        "candidate_coordinate",
        "prior_release_coordinate",
        "required_evidence",
        "remaining_promotion_evidence",
        "limitations",
        "accountable_role",
        "metadata",
    }
    if set(candidate) != candidate_keys:
        raise AssertionError("promotion candidate requires the released candidate shape")
    if (
        candidate["$schema"] != "../contracts/promotion-candidate.v1.schema.json"
        or candidate["schema_version"] != "1.0.0"
        or candidate["promotion_receipt_id"] != CURRENT_PROMOTION_RECEIPT_ID
        or candidate["repository"]
        != "driftframestudios/lims-eln-enterprise-implementation"
        or candidate["target_release"] != CURRENT_RELEASE_TAG
        or candidate["promotion_state"] != "release_candidate"
        or candidate["evidence_mode"] != "observed"
        or candidate["assurance_stage"] != "verified"
        or candidate["accountable_role"] != "Implementation release stewardship"
    ):
        raise AssertionError("promotion candidate requires the verified v0.3.2 identity")

    expected_prior_release = {
        "promotion_receipt": PRIOR_PROMOTION_RECEIPT_PATH.as_posix(),
        "tag": PRIOR_RELEASE_TAG,
        "tag_object_oid": PRIOR_TAG_OBJECT,
        "commit_oid": PRIOR_RELEASE_COMMIT,
        "tree_oid": PRIOR_RELEASE_TREE,
        "archive_digest": PRIOR_ARCHIVE_DIGEST,
    }
    if candidate["prior_release_coordinate"] != expected_prior_release:
        raise AssertionError("promotion candidate requires the prior signed release")
    candidate_coordinate = candidate["candidate_coordinate"]
    if candidate_coordinate != {
        "release": "candidate-implementation-v0.3.2",
        "repository_release": REPOSITORY_RELEASE,
        "public_inspection_manifest": "release/public-inspection-manifest.json",
        "public_inspection_manifest_digest": release[
            "public_inspection_manifest_digest"
        ],
        "external_coordinate_manifest": "release/external-contract-coordinates.json",
        "external_coordinate_manifest_digest": release[
            "external_contract_coordinate_digest"
        ],
        "selected_future_closure_digest": CANONICAL_SELECTED_FUTURE_CLOSURE_DIGEST,
    }:
        raise AssertionError("promotion candidate requires its exact candidate coordinates")
    for field in ("required_evidence", "remaining_promotion_evidence", "limitations"):
        statements = candidate[field]
        if (
            not isinstance(statements, list)
            or not statements
            or any(not isinstance(item, str) or len(item) < 20 for item in statements)
            or len(statements) != len(set(statements))
        ):
            raise AssertionError(
                f"promotion candidate requires material {field.replace('_', ' ')}"
            )
    if candidate["metadata"] != {
        "schema_version": "1.0.0",
        "created_at": "2026-09-02T10:28:31Z",
        "updated_at": "2026-09-02T10:28:31Z",
        "owner": {
            "actor_id": "OWNER-IMPLEMENTATION-PROMOTION-004",
            "display_name": "Implementation release stewardship role",
            "role": "Promotion candidate owner",
        },
    }:
        raise AssertionError("promotion candidate requires its bounded ownership metadata")

    expected_candidate_provenance = {
        "release": "candidate-implementation-v0.3.2",
        "commit": "0" * 40,
        "digest": "sha256:" + "0" * 64,
    }
    if (
        machine.get("lifecycle_state") != "settling"
        or machine.get("current_provenance") != expected_candidate_provenance
    ):
        raise AssertionError("candidate Machine Node requires pending v0.3.2 provenance")
    if machine.get("open_receipts") != first_receipt.get("open_receipts"):
        raise AssertionError("Machine Node and first receipt require one open-receipt set")
    if (
        PRIOR_PROMOTION_RECEIPT_ID in machine.get("open_receipts", [])
        or CURRENT_PROMOTION_RECEIPT_ID not in machine.get("open_receipts", [])
    ):
        raise AssertionError(
            "candidate orientation requires the prior receipt closed and current receipt open"
        )

    candidate_time = "2026-09-02T10:28:31Z"
    if (
        first_receipt.get("as_of") != candidate_time
        or first_receipt.get("metadata", {}).get("updated_at") != candidate_time
        or machine.get("metadata", {}).get("updated_at") != candidate_time
        or horizon.get("as_of") != candidate_time
        or horizon.get("metadata", {}).get("updated_at") != candidate_time
    ):
        raise AssertionError("candidate orientation requires one reconciliation time")

    horizon_items = {
        item["item_id"]: item for item in horizon.get("work_items", [])
    }
    if (
        horizon.get("current_item_ids")
        != ["HORIZON-IMPLEMENTATION-CLOSURE-ALIGNMENT"]
        or horizon_items.get("HORIZON-IMPLEMENTATION-SETTLING", {}).get("state")
        != "complete"
        or horizon_items.get("HORIZON-IMPLEMENTATION-CLOSURE-ALIGNMENT", {}).get(
            "state"
        )
        != "settling"
        or horizon_items.get("HORIZON-SELECTED-FUTURE-COMPARISON", {}).get("state")
        != "waiting"
    ):
        raise AssertionError(
            "Coordination Horizon requires the closure-coordinate patch handoff"
        )

    if (
        inspection_manifest.get("release_state") != "repository_owned_candidate"
        or inspection_manifest.get("prior_release_subject")
        != expected_prior_release
    ):
        raise AssertionError("candidate inspection requires the prior release subject")

    promotion_coordinates = release.get("promotion_coordinates", {})
    if (
        release.get("release_state") != "release_candidate"
        or promotion_coordinates.get("status") != "pending_release_promotion"
        or promotion_coordinates.get("open_receipt_id")
        != CURRENT_PROMOTION_RECEIPT_ID
        or promotion_coordinates.get("candidate_receipt")
        != CURRENT_PROMOTION_CANDIDATE_PATH.as_posix()
        or promotion_coordinates.get("target_release") != CURRENT_RELEASE_TAG
        or promotion_coordinates.get("prior_release")
        != expected_prior_release
    ):
        raise AssertionError("release role requires the pending v0.3.2 promotion coordinate")


def validate_manifests() -> None:
    from scripts.check_automation_contract import validate_automation_contract
    from scripts.build_public_inspection_manifest import (
        MANIFEST_PATH as PUBLIC_INSPECTION_MANIFEST_PATH,
        verify_manifest as verify_public_inspection_manifest,
    )
    from scripts.validate_received_contracts import (
        COORDINATE_PATH as EXTERNAL_COORDINATE_PATH,
        load_coordinates,
        validate_declared_program_requirement,
    )

    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    if manifest["version"] != REPOSITORY_RELEASE:
        raise AssertionError("manifest requires repository release 0.3.2")
    if manifest["repository_role"] != "enterprise_implementation":
        raise AssertionError(
            "manifest repository role requires enterprise_implementation"
        )
    if manifest["evidence_role"] != "actual_implementation":
        raise AssertionError("manifest evidence role requires actual_implementation")
    if manifest["fixture_policy"] != "synthetic_only":
        raise AssertionError("fixture policy requires synthetic_only")
    if manifest["contract_versions"].get("runtime_setting_catalog") != "1.0.0":
        raise AssertionError("manifest requires runtime setting catalog v1")
    runtime = manifest.get("runtime_configuration", {})
    if runtime.get("secret_source") != "aws_secrets_manager":
        raise AssertionError("runtime secret source requires AWS Secrets Manager")
    if runtime.get("configuration_source") != "aws_systems_manager_parameter_store":
        raise AssertionError(
            "runtime configuration source requires Systems Manager Parameter Store"
        )
    control_plane = manifest.get("control_plane", {})
    if control_plane.get("governance_schema_release") != "2.1.0":
        raise AssertionError("control plane requires governance schema release 2.1.0")
    if control_plane.get("control_plane_profile") != "0.3.0":
        raise AssertionError("control plane requires profile 0.3.0")

    public_inspection = manifest.get("public_inspection", {})
    if public_inspection.get("manifest") != PUBLIC_INSPECTION_MANIFEST_PATH.as_posix():
        raise AssertionError(
            "release manifest requires the public inspection manifest path"
        )
    inspection_manifest = verify_public_inspection_manifest(ROOT)
    inspection_manifest_path = ROOT / PUBLIC_INSPECTION_MANIFEST_PATH
    inspection_manifest_digest = file_digest(inspection_manifest_path)
    if (
        public_inspection.get("manifest_digest") != inspection_manifest_digest
        or public_inspection.get("authority") != "repository_owned_candidate_bytes"
        or public_inspection.get("cross_repository_coordinate_state")
        != "accepted_and_consumer_observed"
        or inspection_manifest.get("repository_release") != manifest["version"]
    ):
        raise AssertionError(
            "release manifest requires the exact repository-owned inspection candidate"
        )

    coordinates = load_coordinates(ROOT)
    validate_declared_program_requirement(ROOT, coordinates)
    coordinate_path = ROOT / EXTERNAL_COORDINATE_PATH
    coordinate_digest = file_digest(coordinate_path)
    if manifest.get("external_contracts") != {
        "coordinate_manifest": EXTERNAL_COORDINATE_PATH.as_posix(),
        "coordinate_manifest_digest": coordinate_digest,
        "coordinate_state": "accepted_and_consumer_observed",
    }:
        raise AssertionError(
            "release manifest requires the accepted external contract coordinates"
        )
    if (
        coordinates["governance"]["schema_release"]
        != control_plane["governance_schema_release"]
    ):
        raise AssertionError(
            "external Governance coordinate requires the selected schema release"
        )

    database = manifest.get("database", {})
    migration_release_path = ROOT / database.get("migration_release", "")
    migration_release = json.loads(
        migration_release_path.read_text(encoding="utf-8")
    )
    if migration_release.get("schema_version") != "1.0.0":
        raise AssertionError("Flyway release requires schema release 1.0.0")
    if migration_release.get("engine") != "postgresql":
        raise AssertionError("Flyway release requires PostgreSQL")
    if (
        migration_release.get("migration_product") != "Flyway Community"
        or migration_release.get("flyway_version") != "13.0.0"
    ):
        raise AssertionError("database migrations require Flyway Community 13.0.0")
    if re.fullmatch(
        r"flyway/flyway:13\.0\.0-alpine@sha256:[a-f0-9]{64}",
        str(migration_release.get("container_image", "")),
    ) is None:
        raise AssertionError("Flyway container requires its released immutable digest")
    if migration_release.get("credentials") != "runtime_environment_only":
        raise AssertionError("Flyway credentials require runtime-only resolution")
    if migration_release.get("baseline_policy") != "explicit_attested_baseline_only":
        raise AssertionError("Flyway release requires explicit baseline attestation")
    if (
        migration_release.get("authenticated_login") != "laboratory_migrator"
        or migration_release.get("migration_role") != "laboratory_owner"
        or migration_release.get("role_assumption")
        != "database_scoped_startup_role_after_connect_verified_noinherit_membership"
    ):
        raise AssertionError("Flyway release requires its bounded authority chain")
    callback = migration_release.get("connection_callback", {})
    callback_path = ROOT / callback.get("path", "")
    if (
        callback.get("path") != "sql/afterConnect.sql"
        or callback.get("sha256") != sha256(callback_path.read_bytes()).hexdigest()
    ):
        raise AssertionError("Flyway release requires its connection callback digest")
    callback_sql = callback_path.read_text(encoding="utf-8").lower()
    if (
        "session_user <> 'laboratory_migrator'" not in callback_sql
        or "current_user <> 'laboratory_owner'" not in callback_sql
        or "current_setting('role', true) <> 'laboratory_owner'" not in callback_sql
        or "pg_catalog.pg_db_role_setting" not in callback_sql
        or "configuration.value = 'role=laboratory_owner'" not in callback_sql
        or "granted_role.rolname = 'laboratory_outbox_authority'" not in callback_sql
        or "member_role.rolname = 'laboratory_owner'" not in callback_sql
    ):
        raise AssertionError("Flyway callback requires the released login and owner role")
    provisioning = migration_release.get("cluster_role_provisioning", {})
    provisioning_path = ROOT / provisioning.get("path", "")
    if (
        provisioning.get("path") != "database/provision_cluster_roles.sql"
        or provisioning.get("execution")
        != "separate_privileged_deployment_step"
        or provisioning.get("sha256")
        != sha256(provisioning_path.read_bytes()).hexdigest()
    ):
        raise AssertionError(
            "Flyway release requires its cluster-role prerequisite digest"
        )
    inventory_reference = migration_release.get("artifact_inventory", {})
    inventory_path = ROOT / inventory_reference.get("path", "")
    if (
        inventory_reference.get("path")
        != "database/flyway-artifact-inventory.json"
        or inventory_reference.get("sha256")
        != sha256(inventory_path.read_bytes()).hexdigest()
    ):
        raise AssertionError("Flyway release requires its artifact inventory digest")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    expected_artifact_paths = [
        "flyway.conf",
        "sql/afterConnect.sql",
        "database/provision_cluster_roles.sql",
        "sql/V001__laboratory_core.sql",
        "sql/V002__principal_data_boundaries.sql",
        "sql/V003__trusted_routines_and_outbox_cas.sql",
        "sql/V004__outbox_attempt_evidence_and_recovery.sql",
        "sql/V005__golden_specimen_workbench.sql",
    ]
    if (
        inventory.get("schema_version") != "1.0.0"
        or inventory.get("canonicalization")
        != "ordered-path-nul-sha256-lf-v1"
        or [artifact.get("path") for artifact in inventory.get("artifacts", [])]
        != expected_artifact_paths
    ):
        raise AssertionError("Flyway inventory requires the complete ordered artifact set")
    for artifact in inventory["artifacts"]:
        if artifact.get("sha256") != sha256(
            (ROOT / artifact["path"]).read_bytes()
        ).hexdigest():
            raise AssertionError(
                f"Flyway artifact digest differs for {artifact['path']}"
            )
    inventory_payload = "".join(
        f"{artifact['path']}\0{artifact['sha256']}\n"
        for artifact in inventory["artifacts"]
    ).encode("utf-8")
    inventory_aggregate = "sha256:" + sha256(inventory_payload).hexdigest()
    if (
        inventory.get("aggregate_sha256") != inventory_aggregate
        or inventory_reference.get("aggregate_sha256") != inventory_aggregate
    ):
        raise AssertionError("Flyway inventory requires its aggregate binding")

    flyway_config_path = ROOT / database.get("migration_configuration", "")
    flyway_config = dict(
        line.split("=", 1)
        for line in flyway_config_path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )
    required_flyway_controls = {
        "flyway.locations": "filesystem:sql",
        "flyway.validateMigrationNaming": "true",
        "flyway.validateOnMigrate": "true",
        "flyway.outOfOrder": "false",
        "flyway.cleanDisabled": "true",
        "flyway.baselineOnMigrate": "false",
        "flyway.group": "false",
        "flyway.mixed": "false",
    }
    for setting, expected in required_flyway_controls.items():
        if flyway_config.get(setting) != expected:
            raise AssertionError(f"Flyway setting {setting} requires {expected}")
    if "flyway.initSql" in flyway_config:
        raise AssertionError("Flyway 13 connection state requires the callback surface")

    compose = (ROOT / "infra" / "docker-compose.yml").read_text(encoding="utf-8")
    migrator_service = compose.split("\n  database-migrator:", 1)[1]
    migrator_service = migrator_service.split("\n  database-role-bootstrap:", 1)[0]
    if (
        "FLYWAY_USER: laboratory_migrator" not in migrator_service
        or "postgres_migrator_password" not in migrator_service
        or "- postgres_password\n" in migrator_service
    ):
        raise AssertionError("Flyway service requires its bounded runtime identity")
    compose_images = re.findall(r"^\s+image:\s+(\S+)$", compose, re.MULTILINE)
    if len(compose_images) < 6 or any(
        re.search(r"@sha256:[a-f0-9]{64}$", image) is None
        for image in compose_images
    ):
        raise AssertionError("Compose support images require immutable digests")

    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    if not {
        "infra/secrets/*",
        "infra/secrets/*.txt",
        "!infra/secrets/.gitignore",
    }.issubset(gitignore):
        raise AssertionError("repository exclusions require the local secret boundary")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    if not {
        ".git",
        ".env",
        ".env.*",
        ".venv",
        "**/__pycache__",
        "infra/secrets",
        "receipts/local",
    }.issubset(dockerignore):
        raise AssertionError("container context requires the released exclusion boundary")

    migrations = sorted((ROOT / "sql").glob("V[0-9][0-9][0-9]__*.sql"))
    migration_ids = [path.name[1:4] for path in migrations]
    if migration_ids != ["001", "002", "003", "004", "005"]:
        raise AssertionError("Flyway migrations require the released ordered sequence")
    for migration in migrations:
        sql = migration.read_text(encoding="utf-8")
        if re.search(
            r"^\s*(?:begin|commit|rollback)\s*;",
            sql,
            flags=re.IGNORECASE | re.MULTILINE,
        ):
            raise AssertionError(
                f"Flyway retains transaction ownership for {migration.name}"
            )
        if re.search(r"\bcreate\s+index\s+concurrently\b", sql, re.IGNORECASE):
            raise AssertionError(
                f"Flyway migration {migration.name} requires transactional SQL"
            )
    migration_release_digest = file_digest(migration_release_path)
    if database.get("migration_release_digest") != migration_release_digest:
        raise AssertionError("release manifest requires the Flyway release digest")
    if migration_release.get("migration_head") != migration_ids[-1]:
        raise AssertionError("Flyway release requires the current migration head")
    if database.get("migration_head") != migration_ids[-1]:
        raise AssertionError("release manifest requires the current migration head")
    if database.get("tenant_authority") != (
        "signed_short_lived_database_verified_context"
    ):
        raise AssertionError("database requires the released tenant authority")

    provenance = json.loads((ROOT / "provenance.json").read_text(encoding="utf-8"))
    seed = provenance["seed"]
    if seed["pull_request"] != 3:
        raise AssertionError("provenance requires source pull request 3")
    if seed["merge_commit"] != "613f524821a25389748a9cd98d1bb0d303de87cf":
        raise AssertionError("provenance requires the reviewed merge commit")

    machine = json.loads((ROOT / "machine-node.json").read_text(encoding="utf-8"))
    first_receipt = json.loads(
        (ROOT / "first-receipt.json").read_text(encoding="utf-8")
    )
    horizon = json.loads(
        (ROOT / "COORDINATION-HORIZON.json").read_text(encoding="utf-8")
    )
    promotion = json.loads(
        (ROOT / PRIOR_PROMOTION_RECEIPT_PATH).read_text(encoding="utf-8")
    )
    candidate = json.loads(
        (ROOT / CURRENT_PROMOTION_CANDIDATE_PATH).read_text(encoding="utf-8")
    )
    if machine["schema_release"] != "2.1.0" or not machine["campaigns"]:
        raise AssertionError(
            "canonical Machine Node requires governance schema v2 and campaigns"
        )
    if any(
        campaign.get("marking_schema_version") != machine["schema_release"]
        for campaign in machine["campaigns"]
    ):
        raise AssertionError(
            "canonical Machine Node campaigns require one governance schema release"
        )
    if machine["repository_role"] != manifest["repository_role"]:
        raise AssertionError(
            "canonical Machine Node and manifest require one repository role"
        )
    if first_receipt["machine_node_id"] != machine["machine_node_id"]:
        raise AssertionError("first receipt requires the canonical Machine Node")
    if machine["coordination_horizon_id"] != horizon["horizon_id"]:
        raise AssertionError("Machine Node requires the released Coordination Horizon")
    if first_receipt["coordination_horizon_id"] != horizon["horizon_id"]:
        raise AssertionError("first receipt requires the released Coordination Horizon")
    if (
        machine.get("metadata", {}).get("schema_version") != "2.1.0"
        or first_receipt.get("metadata", {}).get("schema_version") != "2.1.0"
        or horizon.get("metadata", {}).get("schema_version") != "2.1.0"
    ):
        raise AssertionError(
            "orientation metadata requires governance schema release 2.1.0"
        )

    historical_machine = json.loads(
        (
            ROOT / "release" / "seed-lineage-machine-node-v0.2.json"
        ).read_text(encoding="utf-8")
    )
    if historical_machine.get("version") != "0.2.0":
        raise AssertionError(
            "historical Machine Node remains release 0.2.0 seed lineage"
        )
    if machine.get("seed_lineage", {}).get("release") != "implementation-v0.2.0":
        raise AssertionError(
            "canonical Machine Node requires explicit release 0.2.0 seed lineage"
        )

    binding_path = ROOT / manifest["bounded_caller"]["binding_manifest"]
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    if binding["binding_version"] != manifest["version"]:
        raise AssertionError("bounded-caller binding requires the repository release")
    if (
        binding["governance_schema_release"]
        != control_plane["governance_schema_release"]
    ):
        raise AssertionError(
            "bounded-caller binding requires the selected governance schema release"
        )
    source_artifacts = binding["source_artifacts"]
    source_paths = [artifact["path"] for artifact in source_artifacts]
    if len(source_paths) != len(set(source_paths)):
        raise AssertionError("bounded-caller source bindings require unique paths")
    required_workbench_paths = {
        "src/lims_eln_implementation/application.py",
        "src/lims_eln_implementation/workbench/api.py",
        "src/lims_eln_implementation/workbench/postgres.py",
        "src/lims_eln_implementation/workbench/service.py",
        "src/lims_eln_implementation/workbench/shared_contracts.py",
    }
    if not required_workbench_paths.issubset(source_paths):
        raise AssertionError(
            "bounded-caller source bindings require the durable workbench slice"
        )
    for artifact in source_artifacts:
        path = ROOT / artifact["path"]
        if sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
            raise AssertionError(
                f"bounded-caller source binding differs for {artifact['path']}"
            )
    binding_digest = file_digest(binding_path)
    if manifest["bounded_caller"]["binding_digest"] != binding_digest:
        raise AssertionError("manifest requires the bounded-caller binding digest")

    ledger_path = ROOT / "receipts" / "open-receipt-ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if ledger["schema_version"] != "2.0.0":
        raise AssertionError("open receipt ledger requires schema release 2.0.0")
    if (
        ledger["selected_future_closure"]["digest"]
        != CANONICAL_SELECTED_FUTURE_CLOSURE_DIGEST
    ):
        raise AssertionError(
            "open receipt ledger requires the canonical selected-future closure"
        )
    families = {
        item["receipt_family"]
        for item in ledger["receipts"]
        if item["receipt_family"] in CANONICAL_RECEIPT_FAMILIES
    }
    if families != set(CANONICAL_RECEIPT_FAMILIES):
        raise AssertionError("open receipt ledger requires four canonical families")
    ledger_digest = file_digest(ledger_path)

    release = json.loads(
        (ROOT / "release" / "repository-role.json").read_text(encoding="utf-8")
    )
    if release["repository_release"] != manifest["version"]:
        raise AssertionError("release role manifest requires repository release 0.3.2")
    if release["repository_role"] != manifest["repository_role"]:
        raise AssertionError("release role manifest requires enterprise_implementation")
    if release["bounded_caller_binding_digest"] != binding_digest:
        raise AssertionError("release role requires the bounded-caller binding digest")
    if release.get("database_flyway_release_digest") != migration_release_digest:
        raise AssertionError("release role requires the Flyway release digest")
    if release["open_receipt_ledger_digest"] != ledger_digest:
        raise AssertionError("release role requires the open receipt ledger digest")
    if (
        release.get("public_inspection_manifest_digest")
        != inspection_manifest_digest
    ):
        raise AssertionError(
            "release role requires the public inspection manifest digest"
        )
    if release.get("external_contract_coordinate_digest") != coordinate_digest:
        raise AssertionError(
            "release role requires the external contract coordinate digest"
        )
    if release.get("contract_bindings", {}).get("governance_release") != "2.1.0":
        raise AssertionError("release role requires Governance release 2.1.0")
    if (
        release.get("contract_bindings", {}).get("program_contract_package")
        != "0.3.1"
    ):
        raise AssertionError("release role requires Program contract package 0.3.1")
    if tuple(release["receipt_families"]) != CANONICAL_RECEIPT_FAMILIES:
        raise AssertionError("release role requires canonical receipt-family order")
    if (
        release["selected_future_closure_digest"]
        != CANONICAL_SELECTED_FUTURE_CLOSURE_DIGEST
    ):
        raise AssertionError(
            "release role requires the canonical selected-future closure"
        )
    validate_promotion_lifecycle(
        promotion=promotion,
        candidate=candidate,
        machine=machine,
        first_receipt=first_receipt,
        horizon=horizon,
        release=release,
        inspection_manifest=inspection_manifest,
    )
    candidate_digest = file_digest(ROOT / CURRENT_PROMOTION_CANDIDATE_PATH)
    if release["promotion_coordinates"].get("candidate_receipt_digest") != candidate_digest:
        raise AssertionError("release role requires the exact promotion candidate digest")
    promotion_controls = release.get("promotion_controls", {})
    if (
        promotion_controls.get("current_state")
        != "human_review_and_history_protection_with_candidate_ready"
        or promotion_controls.get("hosted_required_check_contexts") != []
        or promotion_controls.get("protected_branches") != ["main"]
        or promotion_controls.get("allowed_merge_methods")
        != ["merge", "squash", "rebase"]
    ):
        raise AssertionError(
            "release controls require review, history protection, and hosted source readiness"
        )
    if promotion_controls.get("human_review") != {
        "required_approvals": 1,
        "code_owner_review": True,
        "dismiss_stale_reviews_on_push": True,
        "extra_approval_for_unattributed_changes": True,
        "last_push_approval": True,
        "review_thread_resolution": True,
    }:
        raise AssertionError(
            "current release controls require human and code-owner review"
        )
    if promotion_controls.get("history_protection") != {
        "branch_deletion_guard": True,
        "non_fast_forward_guard": True,
        "required_signature_rule": False,
    }:
        raise AssertionError(
            "current release controls require deletion and non-fast-forward guards "
            "with an explicit signature-rule state"
        )
    if promotion_controls.get("signature_observation") != {
        "github_verified_merge_commits": True,
        "ruleset_admission": "pull_request_review_without_required_signatures",
    }:
        raise AssertionError(
            "current release controls require the observed merge-signature posture"
        )
    if promotion_controls.get("hosted_check_activation") != {
        "state": "candidate_ready_settings_pending",
        "requires_stable_context": True,
        "requires_funded_execution_path": True,
    }:
        raise AssertionError(
            "hosted-check source requires a stable, funded settings receiver"
        )
    if release.get("automation_controls") != {
        "pull_request_workflow": ".github/workflows/pull-request.yml",
        "pull_request_targets": ["develop", "main"],
        "pull_request_runner": "ubuntu-24.04",
        "pull_request_python": "3.12",
        "pull_request_timeout_minutes": 10,
        "pull_request_permissions": {"contents": "read"},
        "pull_request_concurrency_cancellation": True,
        "manual_full_proof_workflow": ".github/workflows/ci.yml",
        "dependabot_configuration": ".github/dependabot.yml",
        "dependabot_target": "develop",
        "dependabot_interval": "monthly",
        "dependabot_open_pull_requests_per_ecosystem": 2,
        "dependabot_grouped_update_types": ["minor", "patch"],
        "monthly_budget_minutes": {"minimum": 100, "maximum": 300},
        "settings_state": "candidate_ready_contexts_observed_activation_pending",
    }:
        raise AssertionError(
            "release automation controls require the bounded hosted source contract"
        )
    validate_automation_contract(
        ROOT,
        declared_controls=release["automation_controls"],
    )

    contracts = {
        item["contract_id"]: item["digest"] for item in machine["contracts"]
    }
    receipt_contracts = {
        item["contract_id"]: item["digest"]
        for item in first_receipt["contract_state"]
    }
    for contract_id, expected in (
        ("IMPLEMENTATION-BOUNDED-CALLER-001", binding_digest),
        ("IMPLEMENTATION-DATABASE-MIGRATIONS-001", migration_release_digest),
        ("IMPLEMENTATION-OPEN-RECEIPTS-001", ledger_digest),
    ):
        if contracts.get(contract_id) != expected:
            raise AssertionError(f"Machine Node requires {contract_id} digest")
        if receipt_contracts.get(contract_id) != expected:
            raise AssertionError(f"first receipt requires {contract_id} digest")
    for surface_name, surface in (
        ("Machine Node", contracts),
        ("first receipt", receipt_contracts),
    ):
        if (
            surface.get("SIMULATED-SUBSTANTIVE-CLOSURE-2028-V1")
            != CANONICAL_SELECTED_FUTURE_CLOSURE_DIGEST
        ):
            raise AssertionError(
                f"{surface_name} requires the canonical selected-future closure"
            )

    receipt = json.loads(
        (ROOT / "receipts" / "local-verification.example.json").read_text(
            encoding="utf-8"
        )
    )
    if release["release_state"] == "release_candidate":
        if receipt["version_bindings"]["repository"] != "0.3.1":
            raise AssertionError(
                "candidate orientation requires the accepted 0.3.1 local receipt"
            )
    elif receipt["version_bindings"]["repository"] != manifest["version"]:
        raise AssertionError("local verification receipt requires the repository release")
    inventory_digest = file_digest(inventory_path)
    local_head = receipt["version_bindings"].get("database_migration_head")
    if local_head == "004":
        if receipt["version_bindings"].get("governance_schema") != "2.0.1":
            raise AssertionError(
                "historical local verification example requires Governance 2.0.1"
            )
        historical_local_digests = {
            "sha256:e6590446725c47231817bc43a478851e739617f1870bf3a5d7c1e36e3e5bc87e",
            "sha256:3010d543594ef98e5873e2753cd7531e5a94e0922698d4ad04ae55a811a1691c",
            "sha256:9105cc92e7e0d2c166e179411bfe5d2a2bd1f35150fd640ae157ac9ef5cbad07",
        }
        if not historical_local_digests.issubset(receipt["artifact_digests"]):
            raise AssertionError(
                "historical local verification example requires its observed bindings"
            )
        if not any(
            "predecessor migration head 004" in limitation
            for limitation in receipt["limitations"]
        ):
            raise AssertionError(
                "historical local verification example requires its successor boundary"
            )
    else:
        if (
            receipt["version_bindings"].get("governance_schema")
            != control_plane["governance_schema_release"]
        ):
            raise AssertionError(
                "current local verification receipt requires the selected governance schema"
            )
        if local_head != database.get("migration_head"):
            raise AssertionError("local verification receipt requires the migration head")
        if not {
            binding_digest,
            migration_release_digest,
            inventory_digest,
        }.issubset(receipt["artifact_digests"]):
            raise AssertionError(
                "current local verification receipt requires released artifact digests"
            )

    hosted_receipt = json.loads(
        (ROOT / "receipts" / "hosted-postgresql-proof.json").read_text(
            encoding="utf-8"
        )
    )
    if set(hosted_receipt) != set(receipt):
        raise AssertionError("hosted PostgreSQL receipt requires the released receipt shape")
    if (
        hosted_receipt.get("evidence_mode") != "observed"
        or hosted_receipt.get("assurance_stage") != "verified"
        or hosted_receipt.get("environment")
        != "github-hosted-synthetic-postgresql"
    ):
        raise AssertionError(
            "hosted PostgreSQL receipt requires observed synthetic verification"
        )
    hosted_bindings = hosted_receipt.get("version_bindings", {})
    candidate_stage = release["release_state"] == "release_candidate"
    if candidate_stage:
        if hosted_bindings.get("repository") != "0.3.1":
            raise AssertionError(
                "candidate orientation requires the accepted 0.3.1 hosted receipt"
            )
    elif hosted_bindings.get("repository") != manifest["version"]:
        raise AssertionError(
            "hosted PostgreSQL receipt requires its observed repository release"
        )
    observed_commit = str(hosted_bindings.get("repository_commit", ""))
    observed_run = str(hosted_bindings.get("workflow_run", ""))
    historical_commit = "ef3320686842a2c7f1ab98c12479c3ed7c5709f5"
    historical_run = (
        "https://github.com/driftframestudios/"
        "lims-eln-enterprise-implementation/actions/runs/30933020047"
    )
    candidate_scenarios = {
        "SCN-DB-FLYWAY-MIGRATOR-AUTHORITY",
        "SCN-DB-FLYWAY-ARTIFACT-INVENTORY",
        "SCN-DB-MIGRATION-CLEAN-UPGRADE-CONVERGENCE",
        "SCN-DB-MEASUREMENT-COMPLETE-LINEAGE",
        "SCN-DB-CUSTODY-COMPLETE-EVENT-BINDING",
        "SCN-DB-WORKBENCH-RESTART-RELOAD",
        "SCN-DB-WORKBENCH-REPLAY-COLLISION-ISOLATION",
        "SCN-DB-WORKBENCH-ROLLBACK-RETRY",
        "SCN-DB-WORKBENCH-INSTRUMENT-RECOVERY",
        "SCN-DB-WORKBENCH-DECIMAL-SOURCE-SHAPE",
        "SCN-DB-WORKBENCH-CANONICAL-DIGEST",
    }
    if candidate_stage:
        accepted_prior_run = (
            "https://github.com/driftframestudios/"
            "lims-eln-enterprise-implementation/actions/runs/33581976426"
        )
        accepted_prior_digests = {
            "sha256:8ebb58455b8db070c8f13b871401bcea9bb630af57a94605e61105f5d89ff1ea",
            migration_release_digest,
            inventory_digest,
        }
        if (
            observed_commit != "205401a530e984e031bb2c52a1654c6b5f82bc6d"
            or observed_run != accepted_prior_run
            or hosted_bindings.get("database_migration_head") != "005"
            or not accepted_prior_digests.issubset(
                hosted_receipt["artifact_digests"]
            )
            or hosted_bindings.get("flyway") != migration_release["flyway_version"]
            or hosted_bindings.get("flyway_image")
            != migration_release["container_image"]
            or hosted_bindings.get("migration_authenticated_login")
            != migration_release["authenticated_login"]
            or hosted_bindings.get("migration_role")
            != migration_release["migration_role"]
            or not candidate_scenarios.issubset(hosted_receipt["scenario_ids"])
        ):
            raise AssertionError(
                "candidate orientation requires the accepted 0.3.1 hosted bindings"
            )
    elif observed_commit == historical_commit:
        historical_digests = {
            "sha256:2097329ecaf796b0927571fbbce8ee809c039a2488ddf1aab7d5c7ece80244bd",
            "sha256:9e9cd9a640473166f51e209077284d982bcb224ad2e95dd02900727e54646d81",
        }
        if (
            observed_run != historical_run
            or hosted_bindings.get("database_migration_head") != "004"
            or not historical_digests.issubset(hosted_receipt["artifact_digests"])
        ):
            raise AssertionError(
                "historical hosted PostgreSQL receipt requires its observed bindings"
            )
        if not any(
            "superseded by the Flyway transition" in limitation
            for limitation in hosted_receipt["limitations"]
        ):
            raise AssertionError(
                "historical hosted PostgreSQL receipt requires its successor boundary"
            )
    else:
        expected_run_pattern = (
            r"^https://github\.com/driftframestudios/"
            r"lims-eln-enterprise-implementation/actions/runs/[0-9]+$"
        )
        current_digests = {
            binding_digest,
            migration_release_digest,
            inventory_digest,
        }
        if (
            re.fullmatch(r"[a-f0-9]{40}", observed_commit) is None
            or re.fullmatch(expected_run_pattern, observed_run) is None
            or hosted_bindings.get("database_migration_head")
            != database.get("migration_head")
            or not current_digests.issubset(hosted_receipt["artifact_digests"])
            or hosted_bindings.get("flyway") != migration_release["flyway_version"]
            or hosted_bindings.get("flyway_image")
            != migration_release["container_image"]
            or hosted_bindings.get("migration_authenticated_login")
            != migration_release["authenticated_login"]
            or hosted_bindings.get("migration_role")
            != migration_release["migration_role"]
        ):
            raise AssertionError(
                "current hosted PostgreSQL receipt requires Flyway release bindings"
            )
        if not candidate_scenarios.issubset(hosted_receipt["scenario_ids"]):
            raise AssertionError(
                "current hosted PostgreSQL receipt requires successor scenarios"
            )
    required_database_scenarios = {
        "SCN-DB-MIGRATION-003-TO-004-UPGRADE-REPLAY",
        "SCN-DB-SECURITY-DEFINER-TEMP-SHADOW",
        "SCN-DB-OUTBOX-FENCED-CLAIM-RECLAIM-STALE-CONFIRM",
        "SCN-DB-OUTBOX-LEASE-DURATION-INTEGER-BOUND",
        "SCN-DB-OUTBOX-TRANSITION-AUTHORITY",
        "SCN-DB-OUTBOX-ATTEMPT-ACK-RECOVERY-EVIDENCE",
        "SCN-DB-OUTBOX-TRANSPORT-RECEIPT-UNIQUENESS",
    }
    if not required_database_scenarios.issubset(hosted_receipt["scenario_ids"]):
        raise AssertionError(
            "hosted PostgreSQL receipt requires the privileged-routine and "
            "fenced-worker scenarios"
        )


def validate_synthetic_fixtures() -> None:
    fixture_paths = sorted((ROOT / "fixtures" / "synthetic").glob("*.json"))
    if len(fixture_paths) < 3:
        raise AssertionError("repository requires representative synthetic fixtures")
    joined = "\n".join(path.read_text(encoding="utf-8") for path in fixture_paths)
    for token in ("SYN-TENANT", "SYN-SPECIMEN"):
        if token not in joined:
            raise AssertionError(f"synthetic fixtures require {token} identities")
    protected_pattern = re.compile(
        r'"(?:patient_name|patient_id|subject_name|email|phone|address|date_of_birth)"\s*:'
    )
    if protected_pattern.search(joined):
        raise AssertionError(
            "fixtures use invented operational identifiers; protected identity fields "
            "belong in a dedicated redaction exercise"
        )


def validate_runtime_setting_catalog() -> None:
    from lims_eln_implementation.runtime_configuration import (
        RuntimeSettingCatalog,
        SettingClassification,
    )

    path = ROOT / "fixtures" / "synthetic" / "runtime-setting-catalog.v1.json"
    catalog = RuntimeSettingCatalog.from_mapping(
        json.loads(path.read_text(encoding="utf-8"))
    )
    classifications = {spec.classification for spec in catalog.settings.values()}
    if classifications != {
        SettingClassification.CONFIGURATION,
        SettingClassification.SECRET,
    }:
        raise AssertionError(
            "runtime catalog requires configuration and secret classifications"
        )
    document = json.loads(path.read_text(encoding="utf-8"))
    for setting in document["settings"]:
        if "value" in setting or "secret_string" in setting:
            raise AssertionError("runtime catalog entries remain value-free")


def validate_aws_runtime_pattern() -> None:
    runtime_path = ROOT / "infra" / "terraform" / "runtime_configuration.tf"
    runtime = runtime_path.read_text(encoding="utf-8")
    required_fragments = (
        'resource "aws_ssm_parameter" "runtime_configuration"',
        'resource "aws_secretsmanager_secret" "runtime"',
        'resource "aws_kms_key" "runtime_secrets"',
        'data "aws_iam_policy_document" "runtime_configuration_read"',
        '"ssm:GetParameter"',
        '"secretsmanager:GetSecretValue"',
        '"kms:Decrypt"',
        'variable = "kms:ViaService"',
        'variable = "kms:EncryptionContext:SecretARN"',
        'output "runtime_setting_catalog"',
    )
    missing = [fragment for fragment in required_fragments if fragment not in runtime]
    if missing:
        raise AssertionError(f"AWS runtime pattern requires {missing}")
    forbidden_fragments = (
        'resource "aws_secretsmanager_secret_version"',
        '"ssm:GetParametersByPath"',
        '"ssm:GetParameterHistory"',
        '"secretsmanager:ListSecrets"',
        '"secretsmanager:*"',
        '"kms:*"',
        'resources = ["*"]',
    )
    present = [fragment for fragment in forbidden_fragments if fragment in runtime]
    if present:
        raise AssertionError(f"AWS runtime policy exceeds the reference boundary: {present}")
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for protected_path in (
        ".env",
        "*.pem",
        ".terraform/",
        "*.tfstate",
        "*.tfvars",
    ):
        if protected_path not in ignore:
            raise AssertionError(f".gitignore requires {protected_path}")


def validate_credential_hygiene() -> None:
    findings: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        if is_generated_or_external(path):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in CREDENTIAL_PATTERNS.items():
            if pattern.search(content):
                findings.append(f"{path.relative_to(ROOT)} contains {label}")
    if findings:
        raise AssertionError("\n".join(findings))


def validate_authored_language() -> None:
    findings: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix not in PUBLISHED_SUFFIXES:
            continue
        if is_generated_or_external(path):
            continue
        content = path.read_text(encoding="utf-8")
        for token in HOUSE_SYNTAX:
            if token in content:
                findings.append(f"{path.relative_to(ROOT)} contains house token {token!r}")
        if path.suffix == ".md" and HOUSE_DELIMITER in content:
            findings.append(
                f"{path.relative_to(ROOT)} contains the house delimiter token"
            )
        if FRAGILE_COMMENT.search(content):
            findings.append(
                f"{path.relative_to(ROOT)} contains a prohibition-shaped code comment"
            )
    if findings:
        raise AssertionError("\n".join(findings))


def source_digest() -> str:
    digest = sha256()
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix not in PUBLISHED_SUFFIXES:
            continue
        if is_generated_or_external(path) or "receipts" in path.parts:
            continue
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def validate_python_syntax() -> None:
    for path in sorted((*SRC.rglob("*.py"), *(ROOT / "tests").rglob("*.py"))):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def run_tests() -> unittest.result.TestResult:
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise AssertionError("test suite requires a passing result")
    return result


def main() -> int:
    json_paths = load_json_files()
    validate_contracts()
    validate_manifests()
    validate_synthetic_fixtures()
    validate_runtime_setting_catalog()
    validate_aws_runtime_pattern()
    validate_credential_hygiene()
    validate_authored_language()
    validate_python_syntax()
    result = run_tests()
    report = {
        "status": "passed",
        "repository_role": "enterprise_implementation",
        "json_files_validated": len(json_paths),
        "tests_run": result.testsRun,
        "source_digest": source_digest(),
        "fixture_policy": "synthetic_only",
        "credential_hygiene": "passed",
        "runtime_configuration": "parameter_store_and_secrets_manager",
        "evidence_mode": "observed",
        "assurance_stage": "verified",
        "open_receipts": list(CANONICAL_RECEIPT_FAMILIES),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
