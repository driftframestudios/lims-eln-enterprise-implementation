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


def file_digest(path: Path) -> str:
    return f"sha256:{sha256(path.read_bytes()).hexdigest()}"


def load_json_files() -> list[Path]:
    paths = sorted(ROOT.rglob("*.json"))
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

    database = manifest.get("database", {})
    migration_manifest_path = ROOT / database.get("migration_manifest", "")
    migration_manifest = json.loads(
        migration_manifest_path.read_text(encoding="utf-8")
    )
    if migration_manifest.get("schema_version") != "1.0.0":
        raise AssertionError("database migration manifest requires schema release 1.0.0")
    if migration_manifest.get("database_engine") != "postgresql":
        raise AssertionError("database migrations require PostgreSQL")
    if (
        migration_manifest.get("transaction_policy")
        != "one_transaction_per_migration"
    ):
        raise AssertionError("database migrations require one transaction per migration")
    runner_binding = migration_manifest.get("runner", {})
    runner_path = ROOT / runner_binding.get("path", "")
    if runner_binding.get("path") != "scripts/apply_database_migrations.py":
        raise AssertionError("database migrations require the released runner path")
    if sha256(runner_path.read_bytes()).hexdigest() != runner_binding.get("sha256"):
        raise AssertionError("database migration runner differs from its binding")
    migration_entries = migration_manifest.get("migrations", [])
    migration_ids = [entry["id"] for entry in migration_entries]
    if migration_ids != sorted(set(migration_ids)) or not migration_ids:
        raise AssertionError("database migration ids require strict ordered uniqueness")
    released_paths = {entry["path"] for entry in migration_entries}
    discovered_paths = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "sql").glob("[0-9][0-9][0-9]_*.sql")
    }
    if released_paths != discovered_paths:
        raise AssertionError("database migration manifest requires every SQL migration")
    for entry in migration_entries:
        path = ROOT / entry["path"]
        if sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise AssertionError(
                f"database migration checksum differs for {entry['path']}"
            )
        if entry.get("transactional") is not True:
            raise AssertionError(
                f"database migration {entry['id']} requires transaction ownership"
            )
    migration_manifest_digest = file_digest(migration_manifest_path)
    if database.get("migration_manifest_digest") != migration_manifest_digest:
        raise AssertionError("release manifest requires the migration manifest digest")
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
    if release.get("database_migration_manifest_digest") != migration_manifest_digest:
        raise AssertionError("release role requires the database migration digest")
    if release["open_receipt_ledger_digest"] != ledger_digest:
        raise AssertionError("release role requires the open receipt ledger digest")
    if tuple(release["receipt_families"]) != CANONICAL_RECEIPT_FAMILIES:
        raise AssertionError("release role requires canonical receipt-family order")
    if (
        release["selected_future_closure_digest"]
        != CANONICAL_SELECTED_FUTURE_CLOSURE_DIGEST
    ):
        raise AssertionError(
            "release role requires the canonical selected-future closure"
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
        ("IMPLEMENTATION-DATABASE-MIGRATIONS-001", migration_manifest_digest),
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
    if binding_digest not in receipt["artifact_digests"]:
        raise AssertionError(
            "local verification receipt requires the bounded-caller binding digest"
        )
    if migration_manifest_digest not in receipt["artifact_digests"]:
        raise AssertionError(
            "local verification receipt requires the database migration digest"
        )
    if receipt["version_bindings"].get("database_migration_head") != database.get(
        "migration_head"
    ):
        raise AssertionError("local verification receipt requires the migration head")

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
    if (
        hosted_bindings.get("repository") != manifest["version"]
        or hosted_bindings.get("database_migration_head")
        != database.get("migration_head")
        or hosted_bindings.get("repository_commit")
        != "cfa9e55a5a422eafa57632991ce788fc5168bc57"
        or hosted_bindings.get("workflow_run")
        != (
            "https://github.com/driftframestudios/"
            "lims-eln-enterprise-implementation/actions/runs/30930674823"
        )
    ):
        raise AssertionError(
            "hosted PostgreSQL receipt requires its observed release coordinate"
        )
    if binding_digest not in hosted_receipt["artifact_digests"]:
        raise AssertionError(
            "hosted PostgreSQL receipt requires the bounded-caller binding digest"
        )
    if migration_manifest_digest not in hosted_receipt["artifact_digests"]:
        raise AssertionError(
            "hosted PostgreSQL receipt requires the database migration digest"
        )
    required_database_scenarios = {
        "SCN-DB-SECURITY-DEFINER-TEMP-SHADOW",
        "SCN-DB-OUTBOX-FENCED-CLAIM-RECLAIM-STALE-CONFIRM",
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
        if any(part in {".git", "__pycache__", ".terraform"} for part in path.parts):
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
        if any(part in {".git", "__pycache__"} for part in path.parts):
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
        if any(part in {"__pycache__", "receipts"} for part in path.parts):
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
