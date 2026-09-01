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
    "sha256:c402e7a72d9066424d5b83c8fda51ca2fad43c025d017a5f5535126239c96ffb"
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


def validate_manifests() -> None:
    from scripts.build_public_inspection_manifest import (
        MANIFEST_PATH as PUBLIC_INSPECTION_MANIFEST_PATH,
        verify_manifest as verify_public_inspection_manifest,
    )

    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    if manifest["version"] != "0.3.1":
        raise AssertionError("manifest requires repository release 0.3.1")
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
    if control_plane.get("governance_schema_release") != "2.0.1":
        raise AssertionError("control plane requires governance schema release 2.0.1")
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
        != "awaiting_accepted_revisions"
        or inspection_manifest.get("repository_release") != manifest["version"]
    ):
        raise AssertionError(
            "release manifest requires the exact repository-owned inspection candidate"
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
    if machine["schema_release"] != "2.0.1" or not machine["campaigns"]:
        raise AssertionError(
            "canonical Machine Node requires governance schema v2 and campaigns"
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
    for artifact in binding["source_artifacts"]:
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
        raise AssertionError("release role manifest requires repository release 0.3.1")
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
    if tuple(release["receipt_families"]) != CANONICAL_RECEIPT_FAMILIES:
        raise AssertionError("release role requires canonical receipt-family order")
    if (
        release["selected_future_closure_digest"]
        != CANONICAL_SELECTED_FUTURE_CLOSURE_DIGEST
    ):
        raise AssertionError(
            "release role requires the canonical selected-future closure"
        )
    promotion_controls = release.get("promotion_controls", {})
    if (
        promotion_controls.get("current_state")
        != "human_review_and_history_protection_with_empty_hosted_checks"
        or promotion_controls.get("hosted_required_check_contexts") != []
        or promotion_controls.get("protected_branches") != ["main", "develop"]
        or promotion_controls.get("allowed_merge_methods")
        != ["merge", "squash", "rebase"]
    ):
        raise AssertionError(
            "current release controls require the empty hosted-check resting state"
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
        "main_release_signatures": True,
    }:
        raise AssertionError(
            "current release controls require deletion, history, and signature guards"
        )
    if promotion_controls.get("future_hosted_check_activation") != {
        "state": "separate_reviewed_change",
        "requires_stable_context": True,
        "requires_funded_execution_path": True,
    }:
        raise AssertionError(
            "future hosted checks require a separate funded activation change"
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
    if receipt["version_bindings"]["repository"] != manifest["version"]:
        raise AssertionError("local verification receipt requires the repository release")
    if (
        receipt["version_bindings"]["governance_schema"]
        != control_plane["governance_schema_release"]
    ):
        raise AssertionError(
            "local verification receipt requires the selected governance schema"
        )
    inventory_digest = file_digest(inventory_path)
    local_head = receipt["version_bindings"].get("database_migration_head")
    if local_head == "004":
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
    if hosted_bindings.get("repository") != manifest["version"]:
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
    if observed_commit == historical_commit:
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
        current_scenarios = {
            "SCN-DB-FLYWAY-MIGRATOR-AUTHORITY",
            "SCN-DB-FLYWAY-ARTIFACT-INVENTORY",
            "SCN-DB-MIGRATION-CLEAN-UPGRADE-CONVERGENCE",
            "SCN-DB-MEASUREMENT-COMPLETE-LINEAGE",
            "SCN-DB-CUSTODY-COMPLETE-EVENT-BINDING",
        }
        if not current_scenarios.issubset(hosted_receipt["scenario_ids"]):
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
