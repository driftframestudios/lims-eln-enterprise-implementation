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
    if manifest["version"] != "0.2.0":
        raise AssertionError("manifest requires repository release 0.2.0")
    if manifest["repository_role"] != "actual_implementation":
        raise AssertionError("manifest repository role requires actual_implementation")
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
    provenance = json.loads((ROOT / "provenance.json").read_text(encoding="utf-8"))
    seed = provenance["seed"]
    if seed["pull_request"] != 3:
        raise AssertionError("provenance requires source pull request 3")
    if seed["merge_commit"] != "613f524821a25389748a9cd98d1bb0d303de87cf":
        raise AssertionError("provenance requires the reviewed merge commit")
    machine = json.loads((ROOT / "MACHINE-NODE.json").read_text(encoding="utf-8"))
    if machine["schema_version"] != "2.0.0" or not machine["campaigns"]:
        raise AssertionError("Machine Node requires schema v2 and campaign markings")
    if machine["version"] != manifest["version"]:
        raise AssertionError("Machine Node and manifest require one repository release")
    receipt = json.loads(
        (ROOT / "receipts" / "local-verification.example.json").read_text(
            encoding="utf-8"
        )
    )
    if receipt["version_bindings"]["repository"] != manifest["version"]:
        raise AssertionError("local verification receipt requires the repository release")


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
        "repository_role": "actual_implementation",
        "json_files_validated": len(json_paths),
        "tests_run": result.testsRun,
        "source_digest": source_digest(),
        "fixture_policy": "synthetic_only",
        "credential_hygiene": "passed",
        "runtime_configuration": "parameter_store_and_secrets_manager",
        "evidence_mode": "observed",
        "assurance_stage": "verified",
        "open_receipts": [
            "configured_vendor_environments",
            "representative_migration_and_restore",
            "production_security_and_observability",
            "accountable_scientific_quality_regulatory_acceptance",
        ],
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
