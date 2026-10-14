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

PUBLIC_POSSIBLE_SKILL_METADATA = {
    ".agents/skills/configured-environment-evidence-binding/SKILL.md": {
        "name": "configured-environment-evidence-binding",
        "source_band": "public_possible",
        "skill_version": "0.1.0",
        "origin": "repository_native",
    },
    ".agents/skills/contextual-jargon-scan/SKILL.md": {
        "name": "contextual-jargon-scan",
        "source_band": "public_possible",
        "skill_version": "0.1.0",
        "upstream_repository": "driftframestudios/human-ai-systems-exemplars",
        "upstream_path": ".agents/skills/contextual-jargon-scan/SKILL.md",
        "upstream_revision": "0c023343e46cd9b1333a63c2d509787352fbad14",
        "upstream_blob_sha1": "3c3a94db99152385253e0281c8afa8fea8208ac5",
        "upstream_sha256": (
            "da383f99eaff364d7e17c3bff93d8da618ec95894a45ff78a9620d8d7fc81523"
        ),
        "adaptation_relation": "repository_local_derivative",
    },
    ".agents/skills/proportionate-recovery-routing/SKILL.md": {
        "name": "proportionate-recovery-routing",
        "source_band": "public_possible",
        "skill_version": "0.1.0",
        "upstream_repository": "driftframestudios/lims-eln-program-specification",
        "upstream_path": ".agents/skills/proportionate-recovery-routing/SKILL.md",
        "upstream_revision": "05357fbed16a5b5aca80c239e4c7535f67d5654b",
        "upstream_blob_sha1": "2756ae9630c5016b13eb9b7158718d0b03e1d3cc",
        "upstream_sha256": (
            "a3e4a7b558793a54558c945034a5199631103cdd69435e3f3720b062b8b9cb9d"
        ),
        "adaptation_relation": "repository_local_derivative",
    },
    ".agents/skills/repository-reentry/SKILL.md": {
        "name": "repository-reentry",
        "source_band": "public_possible",
        "skill_version": "0.1.0",
        "upstream_repository": "driftframestudios/human-ai-systems-exemplars",
        "upstream_path": ".agents/skills/repository-reentry/SKILL.md",
        "upstream_revision": "0c023343e46cd9b1333a63c2d509787352fbad14",
        "upstream_blob_sha1": "ac2c3732826c515b236598af10e0a204dbe14ace",
        "upstream_sha256": (
            "c60bb1bac3a993c78d94b1d05aaa7a97761b99275fc9acdc8285acba6f688f02"
        ),
        "adaptation_relation": "repository_local_derivative",
    },
    ".agents/skills/source-authority-mapping/SKILL.md": {
        "name": "source-authority-mapping",
        "source_band": "public_possible",
        "skill_version": "0.1.0",
        "upstream_repository": "driftframestudios/human-ai-systems-exemplars",
        "upstream_path": ".agents/skills/source-authority-mapping/SKILL.md",
        "upstream_revision": "0c023343e46cd9b1333a63c2d509787352fbad14",
        "upstream_blob_sha1": "112830e9b70540b0bc9a8535ab77c7a04c1a5926",
        "upstream_sha256": (
            "1420eaee7f6d58805c29eaff23644d4982fdf1f12d2f6ce3cc39c65791939aff"
        ),
        "adaptation_relation": "repository_local_derivative",
    },
}
_SKILL_REQUIRED_SECTIONS = (
    "## Contract",
    "## Rules",
    "## Operating sequence",
    "## Completion",
)
_GIT_OID = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")

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
CURRENT_PROMOTION_OBSERVATION_PATH = Path(
    "receipts/promotion-observation-v0.3.2.json"
)
CURRENT_PROMOTION_OBSERVATION_SCHEMA_PATH = Path(
    "contracts/promotion-observation.v1.schema.json"
)
CURRENT_RELEASE_TAG = "v0.3.2"
PRIOR_PROMOTION_RECEIPT_ID = "RCP-IMPLEMENTATION-PROMOTION-003"
PRIOR_PROMOTION_RECEIPT_PATH = Path("receipts/promotion-receipt.json")
PRIOR_RELEASE_TAG = "v0.3.1"
PRIOR_REVIEWED_CANDIDATE_COMMIT = "a4982734fbfa7f8dbe81d41bbc8435ed66a96d46"
PRIOR_RELEASE_COMMIT = "44a4b8e67ff2e6af232b12daf3692bee8e8f3a3a"
PRIOR_RELEASE_TREE = "cc1bb335c0cdd1a37d1b6554480b3afdb9c9f360"
PRIOR_TAG_OBJECT = "8b1013ff6a116b64e5d31c2870b574f641ee88f6"
PRIOR_ARCHIVE_DIGEST = (
    "sha256:00da1be41bdf23a21124d600f3788464bfd8f590c819f6a9c74b98671edb2174"
)
REVIEWED_INSPECTION_MANIFEST_DIGEST = (
    "sha256:1e41212a2ca0cfe679ffc799bb08d1854300d57354364831b82390ab0133a12f"
)
CURRENT_REVIEWED_CANDIDATE_COMMIT = "ce612ae3e4fcf6ff478f5d801343e8b28b4f847d"
CURRENT_RELEASE_COMMIT = "fe0bd2a08ac1697ce18ca583d9631faae7db7132"
CURRENT_RELEASE_TREE = "eb8eadb27a9e07c6069a1946f115a0083d94af5c"
CURRENT_TAG_OBJECT = "c3db01079b88622f06e8714c8bcbdf0dc1803a10"
CURRENT_ARCHIVE_DIGEST = (
    "sha256:0ea3db3099e3485f65d238fb2e194c6bfd9b9a90f6642431c4a96974ebcc3c16"
)
CURRENT_CANDIDATE_RECEIPT_DIGEST = (
    "sha256:c78f16df5832f6c7b39ea1b0d9a61316b26d90cd1552fd8b2c39043436a94340"
)
CURRENT_CANDIDATE_INSPECTION_MANIFEST_DIGEST = (
    "sha256:73a062069301c694df26196a7384184d7229089885d97279cb989244ca7435c8"
)
CURRENT_EXTERNAL_COORDINATE_DIGEST = (
    "sha256:ad699b5d7cb6c24e0d86b2dfbae5d3104d03fec8ee08cdd04c33f444376bcde1"
)
CURRENT_OBSERVATION_TIME = "2026-09-02T11:23:40Z"
CURRENT_RECONCILIATION_TIME = "2026-10-02T22:14:32Z"
ACCEPTED_PRIOR_HOSTED_COMMIT = "205401a530e984e031bb2c52a1654c6b5f82bc6d"
HISTORICAL_PRIOR_HOSTED_COMMIT = "ef3320686842a2c7f1ab98c12479c3ed7c5709f5"
PREDECESSOR_DATABASE_HOSTED_COMMIT = "e15f0a37520b651cf83e856c3b9d67ab9f42cd9b"
CURRENT_DATABASE_HOSTED_COMMIT = "2d12b111edb86f1f16f02338933a827b767a687f"
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


def parse_skill_source(path: Path) -> tuple[dict[str, str], str]:
    """Return simple scalar front matter and the complete skill source."""

    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    if not lines or lines[0] != "---":
        raise ValueError(f"{path} requires YAML front matter")
    try:
        closing = lines.index("---", 1)
    except ValueError as error:
        raise ValueError(f"{path} has unclosed YAML front matter") from error
    metadata: dict[str, str] = {}
    for line in lines[1:closing]:
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"{path} has unsupported front-matter line {line!r}")
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"')
    return metadata, content


def validate_collaboration_workbench(root: Path = ROOT) -> list[str]:
    """Validate the exact repository-local skill workbench and its orientation."""

    findings: list[str] = []
    skills_root = root / ".agents" / "skills"
    actual_paths = {
        str(path.relative_to(root)) for path in skills_root.glob("*/SKILL.md")
    }
    expected_paths = set(PUBLIC_POSSIBLE_SKILL_METADATA)
    if actual_paths != expected_paths:
        findings.append(
            "public-possible skill inventory differs: expected "
            f"{sorted(expected_paths)!r}; received {sorted(actual_paths)!r}"
        )
    catalog_path = skills_root / "README.md"
    if not catalog_path.is_file():
        findings.append(".agents/skills/README.md is required for skill discovery")
    else:
        catalog = catalog_path.read_text(encoding="utf-8")
        for relative_path in expected_paths:
            skill_name = Path(relative_path).parent.name
            expected_route = f"({skill_name}/SKILL.md)"
            if expected_route not in catalog:
                findings.append(
                    ".agents/skills/README.md must link the skill route "
                    f"{expected_route}"
                )
    for relative_path, expected in PUBLIC_POSSIBLE_SKILL_METADATA.items():
        path = root / relative_path
        if not path.is_file():
            continue
        try:
            metadata, content = parse_skill_source(path)
        except ValueError as error:
            findings.append(str(error))
            continue
        observed = {key: metadata.get(key) for key in expected}
        if observed != expected:
            findings.append(
                f"{relative_path} metadata differs: expected {expected!r}; "
                f"received {observed!r}"
            )
        if path.parent.name != metadata.get("name"):
            findings.append(f"{relative_path} directory and skill name must match")
        if not metadata.get("description", "").strip():
            findings.append(f"{relative_path} requires a discovery description")
        if metadata.get("adaptation_relation") == "repository_local_derivative":
            if not _GIT_OID.fullmatch(metadata.get("upstream_revision", "")):
                findings.append(f"{relative_path} requires a full upstream revision")
            if not _GIT_OID.fullmatch(metadata.get("upstream_blob_sha1", "")):
                findings.append(f"{relative_path} requires an upstream blob identity")
            if not _SHA256.fullmatch(metadata.get("upstream_sha256", "")):
                findings.append(f"{relative_path} requires an upstream SHA-256 identity")
        for heading in _SKILL_REQUIRED_SECTIONS:
            if heading not in content:
                findings.append(f"{relative_path} requires {heading}")
        if "notion.so" in content or "app.notion.com" in content:
            findings.append(
                f"{relative_path} must remain usable through repository-local "
                "guidance; private workspace locator found"
            )
    for orientation_name in ("README.md", "AGENTS.md"):
        orientation_path = root / orientation_name
        if not orientation_path.is_file():
            findings.append(f"{orientation_name} is required for workbench routing")
            continue
        orientation = orientation_path.read_text(encoding="utf-8")
        if ".agents/skills/README.md" not in orientation:
            findings.append(
                f"{orientation_name} must link .agents/skills/README.md"
            )
        for relative_path in expected_paths:
            if relative_path not in orientation:
                findings.append(
                    f"{orientation_name} must link the exact skill path {relative_path}"
                )

    return findings


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

    from jsonschema import Draft202012Validator, FormatChecker
    from jsonschema.exceptions import SchemaError

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


def validate_promotion_observation_schema(
    observation: dict,
    *,
    schema_path: Path | None = None,
) -> None:
    """Execute the observation's declared JSON Schema against its exact document."""

    from jsonschema import Draft202012Validator, FormatChecker
    from jsonschema.exceptions import SchemaError

    path = schema_path or (ROOT / CURRENT_PROMOTION_OBSERVATION_SCHEMA_PATH)
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
    except (OSError, UnicodeError, json.JSONDecodeError, SchemaError) as error:
        raise AssertionError(
            "promotion observation schema requires valid JSON Schema 2020-12"
        ) from error

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(
        validator.iter_errors(observation),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "$"
        raise AssertionError(
            "promotion observation schema validation differs at "
            f"{location}: {first.message}"
        )


def classify_hosted_postgresql_receipt_binding(
    hosted_bindings: dict,
) -> str:
    """Identify an exact hosted receipt already observed in repository history."""

    repository_version = hosted_bindings.get("repository")
    observed_commit = str(hosted_bindings.get("repository_commit", ""))
    if repository_version == "0.3.2":
        if observed_commit == CURRENT_DATABASE_HOSTED_COMMIT:
            return "observed_v005_artifacts"
        raise AssertionError(
            "current 0.3.2 hosted receipt requires its exact observed commit"
        )
    if repository_version == "0.3.1":
        if observed_commit == PREDECESSOR_DATABASE_HOSTED_COMMIT:
            return "observed_predecessor"
        if observed_commit == ACCEPTED_PRIOR_HOSTED_COMMIT:
            return "accepted_prior"
        if observed_commit == HISTORICAL_PRIOR_HOSTED_COMMIT:
            return "historical_prior"
        raise AssertionError(
            "retained 0.3.1 hosted receipt requires an exact observed commit"
        )
    raise AssertionError(
        "hosted PostgreSQL receipt requires an exact retained observation; "
        "a later release receives its own accepted hosted commit coordinate"
    )


def validate_hosted_postgresql_coordinate_state(
    *,
    binding_kind: str,
    coordinate_state: str,
) -> None:
    """Keep the active database state aligned with its receipt generation."""

    expected_states = {
        "observed_v005_artifacts": "v005_observed_successor_candidate",
        "observed_predecessor": "predecessor_observed_successor_candidate",
    }
    if expected_states.get(binding_kind) != coordinate_state:
        raise AssertionError(
            "hosted PostgreSQL coordinate state requires its matching receipt binding"
        )


def validate_current_hosted_postgresql_receipt_contract(
    hosted_receipt: dict,
) -> None:
    """Bind the complete current hosted receipt identity and evidence set."""

    expected_identity = {
        "schema_version": "1.1.0",
        "receipt_id": "RECEIPT-HOSTED-POSTGRESQL-001",
        "claim_id": "CLAIM-HOSTED-SYNTHETIC-DATABASE-BOUNDARIES",
        "intended_use_id": "INTENDED-USE-SYNTHETIC-REFERENCE",
        "release_claim_id": "RELEASE-CLAIM-IMPLEMENTATION-0.3.2",
        "evidence_mode": "observed",
        "assurance_stage": "verified",
        "environment": "github-hosted-synthetic-postgresql",
        "observed_at": "2026-10-02T22:14:32Z",
        "performer_id": "GITHUB-ACTIONS-HOSTED-RUNNER",
        "reviewer_id": "SYN-INDEPENDENT-DATABASE-CONVERGENCE-SUITE",
    }
    expected_scenarios = (
        "SCN-DB-MIGRATION-CHECKSUM-REPLAY",
        "SCN-DB-MIGRATION-003-TO-004-UPGRADE-REPLAY",
        "SCN-DB-MIGRATION-004-PROVENANCE-GATE",
        "SCN-DB-SIGNED-TENANT-BOUNDARY",
        "SCN-DB-TENANT-CONTEXT-TAMPER-EXPIRY",
        "SCN-DB-CUSTODY-CAS-AND-ATOMIC-OUTBOX",
        "SCN-DB-SECURITY-DEFINER-TEMP-SHADOW",
        "SCN-DB-OUTBOX-CONTENT-IMMUTABILITY",
        "SCN-DB-OUTBOX-FENCED-CLAIM-RECLAIM-STALE-CONFIRM",
        "SCN-DB-OUTBOX-LEASE-DURATION-INTEGER-BOUND",
        "SCN-DB-OUTBOX-MESSAGE-IDENTITY-LIVENESS",
        "SCN-DB-OUTBOX-TRANSITION-AUTHORITY",
        "SCN-DB-OUTBOX-ATTEMPT-ACK-RECOVERY-EVIDENCE",
        "SCN-DB-OUTBOX-TRANSPORT-RECEIPT-UNIQUENESS",
        "SCN-DB-SCIENTIFIC-QUANTITY-EXACTNESS",
        "SCN-DB-VERIFICATION-KEY-CONFIDENTIALITY",
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
    )
    expected_artifact_digests = (
        "sha256:2e993316b59334071e5234cbb3d2c463a96f67e84550202a2df3f49d3c27a283",
        "sha256:c5ac44d9797df3f328cc4a8bd64f176317398abff564e2cb8f62fb33c123dc2f",
        "sha256:8bbada0ceaa11f264d2d6ad4c893abd8b4313482da387401fd9b0f1d0106666a",
    )
    expected_limitations = (
        "This receipt establishes the synthetic hosted PostgreSQL 17 migration, "
        "durable workbench, and upgrade-replay paths for the named commit; "
        "production authorization remains with accountable environment owners.",
        "The independently signed v0.3.2 release subject retains its existing "
        "promotion observation; this receipt binds only the named post-release "
        "development commit.",
        "PostgreSQL 18.6 compatibility was observed locally and remains outside "
        "this hosted coordinate.",
        "Representative populated migration and restore rehearsal retains its "
        "independent successor receipt.",
        "Production security and observability evidence retains its independent "
        "successor receipt.",
        "Accountable Scientific, Quality, and Regulatory acceptance retains its "
        "independent successor receipt.",
    )
    if (
        any(
            hosted_receipt.get(key) != value
            for key, value in expected_identity.items()
        )
        or tuple(hosted_receipt.get("scenario_ids", ())) != expected_scenarios
        or tuple(hosted_receipt.get("artifact_digests", ()))
        != expected_artifact_digests
        or tuple(hosted_receipt.get("limitations", ())) != expected_limitations
    ):
        raise AssertionError(
            "current hosted PostgreSQL receipt requires its exact identity and "
            "complete evidence set"
        )


def validate_promotion_lifecycle(
    *,
    promotion: dict,
    candidate: dict,
    observation: dict,
    machine: dict,
    first_receipt: dict,
    horizon: dict,
    release: dict,
    inspection_manifest: dict,
) -> None:
    """Keep both historical carriers distinct from the observed patch release."""

    validate_promotion_candidate_schema(candidate)
    validate_promotion_observation_schema(observation)
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
        "commit_oid": PRIOR_REVIEWED_CANDIDATE_COMMIT,
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
        "public_inspection_manifest_digest": (
            CURRENT_CANDIDATE_INSPECTION_MANIFEST_DIGEST
        ),
        "external_coordinate_manifest": "release/external-contract-coordinates.json",
        "external_coordinate_manifest_digest": CURRENT_EXTERNAL_COORDINATE_DIGEST,
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

    observation_keys = {
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
    if set(observation) != observation_keys:
        raise AssertionError("promotion observation requires the released closed shape")
    if (
        observation["$schema"]
        != "../contracts/promotion-observation.v1.schema.json"
        or observation["schema_version"] != "1.0.0"
        or observation["promotion_receipt_id"] != CURRENT_PROMOTION_RECEIPT_ID
        or observation["repository"]
        != "driftframestudios/lims-eln-enterprise-implementation"
        or observation["target_release"] != CURRENT_RELEASE_TAG
        or observation["promotion_state"] != "release_observed"
        or observation["evidence_mode"] != "observed"
        or observation["assurance_stage"] != "verified"
        or observation["accountable_role"]
        != "Implementation release stewardship"
    ):
        raise AssertionError("promotion observation requires the verified v0.3.2 identity")
    if observation["candidate_coordinate"] != {
        "release": "candidate-implementation-v0.3.2",
        "commit_oid": CURRENT_REVIEWED_CANDIDATE_COMMIT,
        "tree_oid": CURRENT_RELEASE_TREE,
        "candidate_receipt": CURRENT_PROMOTION_CANDIDATE_PATH.as_posix(),
        "candidate_receipt_digest": CURRENT_CANDIDATE_RECEIPT_DIGEST,
        "public_inspection_manifest_digest": (
            CURRENT_CANDIDATE_INSPECTION_MANIFEST_DIGEST
        ),
    }:
        raise AssertionError("promotion observation requires the reviewed candidate")
    expected_current_release = {
        "git_object_format": "sha1",
        "tag": CURRENT_RELEASE_TAG,
        "tag_object_oid": CURRENT_TAG_OBJECT,
        "commit_oid": CURRENT_RELEASE_COMMIT,
        "tree_oid": CURRENT_RELEASE_TREE,
        "archive_format": "git-tar",
        "archive_digest": CURRENT_ARCHIVE_DIGEST,
        "promoted_at": "2026-09-02T11:21:02Z",
        "pull_request": 27,
        "hosted_checks": [
            {
                "name": "Repository validation",
                "run_id": "33623991109",
                "job_id": "100227324662",
                "conclusion": "success",
            }
        ],
        "review_observation": {
            "merge_admission": "configured_ordinary_bypass",
            "independent_review": "deputized_independent_review_completed",
            "github_review_record": "no_formal_review_submitted",
        },
        "merge_signature_verification": "valid",
        "tag_signature_verification": "valid",
    }
    if observation["release_coordinate"] != expected_current_release:
        raise AssertionError("promotion observation requires the exact v0.3.2 subject")
    for field in ("required_evidence", "limitations"):
        statements = observation[field]
        if (
            not isinstance(statements, list)
            or not statements
            or any(not isinstance(item, str) or len(item) < 20 for item in statements)
            or len(statements) != len(set(statements))
        ):
            raise AssertionError(
                f"promotion observation requires material {field.replace('_', ' ')}"
            )
    if observation["metadata"] != {
        "schema_version": "1.0.0",
        "created_at": CURRENT_OBSERVATION_TIME,
        "updated_at": CURRENT_OBSERVATION_TIME,
        "owner": {
            "actor_id": "OWNER-IMPLEMENTATION-PROMOTION-004",
            "display_name": "Implementation release stewardship role",
            "role": "Promotion observation owner",
        },
    }:
        raise AssertionError("promotion observation requires its bounded ownership metadata")

    expected_release_provenance = {
        "release": "implementation-v0.3.2",
        "commit": CURRENT_RELEASE_COMMIT,
        "digest": CURRENT_ARCHIVE_DIGEST,
    }
    expected_development_observation = {
        "scope": "database_artifacts",
        "coordinate_state": "v005_observed_successor_candidate",
        "flyway_version": "13.8.1",
        "receipt": "receipts/hosted-postgresql-proof.json",
    }
    if (
        machine.get("lifecycle_state") != "post_release_development"
        or machine.get("current_provenance") != expected_release_provenance
        or machine.get("current_development_observation")
        != expected_development_observation
    ):
        raise AssertionError(
            "Machine Node requires the v0.3.2 release subject and current "
            "development observation"
        )
    if machine.get("open_receipts") != first_receipt.get("open_receipts"):
        raise AssertionError("Machine Node and first receipt require one open-receipt set")
    if (
        PRIOR_PROMOTION_RECEIPT_ID in machine.get("open_receipts", [])
        or CURRENT_PROMOTION_RECEIPT_ID in machine.get("open_receipts", [])
    ):
        raise AssertionError(
            "observed orientation requires both promotion receipts closed"
        )

    if machine.get("metadata", {}).get("updated_at") != CURRENT_OBSERVATION_TIME:
        raise AssertionError(
            "Machine Node timestamp requires the immutable release observation time"
        )

    if (
        first_receipt.get("as_of") != CURRENT_RECONCILIATION_TIME
        or first_receipt.get("metadata", {}).get("updated_at")
        != CURRENT_RECONCILIATION_TIME
        or horizon.get("as_of") != CURRENT_RECONCILIATION_TIME
        or horizon.get("metadata", {}).get("updated_at")
        != CURRENT_RECONCILIATION_TIME
    ):
        raise AssertionError("living orientation requires one reconciliation time")

    horizon_items = {
        item["item_id"]: item for item in horizon.get("work_items", [])
    }
    if (
        horizon.get("current_item_ids")
        != ["HORIZON-OBSERVED-SUCCESSORS"]
        or horizon_items.get("HORIZON-IMPLEMENTATION-SETTLING", {}).get("state")
        != "complete"
        or horizon_items.get("HORIZON-IMPLEMENTATION-CLOSURE-ALIGNMENT", {}).get(
            "state"
        )
        != "complete"
        or horizon_items.get("HORIZON-SELECTED-FUTURE-COMPARISON", {}).get("state")
        != "complete"
        or horizon_items.get("HORIZON-OBSERVED-SUCCESSORS", {}).get("state")
        != "waiting"
    ):
        raise AssertionError(
            "Coordination Horizon requires the completed comparison and waiting "
            "observed-successor route"
        )
    if (
        "post-release development carrier"
        not in first_receipt.get("current_horizon_summary", "")
        or "post-release development carrier"
        not in horizon.get("reentry_capsule", {}).get("current_state", "")
    ):
        raise AssertionError(
            "orientation requires the release subject and development carrier split"
        )

    if (
        inspection_manifest.get("release_state")
        != "post_release_development_carrier"
        or inspection_manifest.get("release_subject") != expected_current_release
        or inspection_manifest.get("prior_release_subject")
        != expected_prior_release
    ):
        raise AssertionError("release inspection requires current and prior subjects")

    promotion_coordinates = release.get("promotion_coordinates", {})
    if (
        release.get("release_state") != "post_release_development"
        or promotion_coordinates.get("status") != "release_observed"
        or promotion_coordinates.get("settled_receipt_id")
        != CURRENT_PROMOTION_RECEIPT_ID
        or promotion_coordinates.get("observation_receipt")
        != CURRENT_PROMOTION_OBSERVATION_PATH.as_posix()
        or promotion_coordinates.get("candidate_receipt")
        != CURRENT_PROMOTION_CANDIDATE_PATH.as_posix()
        or promotion_coordinates.get("target_release") != CURRENT_RELEASE_TAG
        or promotion_coordinates.get("release_subject")
        != expected_current_release
        or promotion_coordinates.get("prior_release")
        != expected_prior_release
    ):
        raise AssertionError("release role requires the observed v0.3.2 coordinate")


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
    if control_plane.get("governance_schema_release") != "2.2.0":
        raise AssertionError("control plane requires governance schema release 2.2.0")
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
        or public_inspection.get("authority") != "repository_owned_inspection_bytes"
        or public_inspection.get("cross_repository_coordinate_state")
        != "accepted_and_consumer_observed"
        or inspection_manifest.get("repository_release") != manifest["version"]
    ):
        raise AssertionError(
            "release manifest requires the exact repository-owned inspection carrier"
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
    flyway_version = str(migration_release.get("flyway_version", ""))
    if (
        migration_release.get("migration_product") != "Flyway Community"
        or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", flyway_version) is None
    ):
        raise AssertionError(
            "database migrations require one exact Flyway Community release"
        )
    container_image = str(migration_release.get("container_image", ""))
    if re.fullmatch(
        rf"flyway/flyway:{re.escape(flyway_version)}-alpine@sha256:[a-f0-9]{{64}}",
        container_image,
    ) is None:
        raise AssertionError("Flyway container requires its released immutable digest")
    if (
        database.get("migration_product") != migration_release["migration_product"]
        or database.get("migration_product_version") != flyway_version
    ):
        raise AssertionError(
            "release manifest requires the selected Flyway product coordinate"
        )
    dockerfile = (ROOT / "infra" / "migrator.Dockerfile").read_text(
        encoding="utf-8"
    )
    if dockerfile.splitlines()[0] != f"FROM {container_image}":
        raise AssertionError(
            "migrator image requires the selected Flyway release coordinate"
        )
    manual_workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    workflow_flyway_images = re.findall(
        r"(?m)^\s*FLYWAY_IMAGE:\s*(\S+)\s*$", manual_workflow
    )
    if workflow_flyway_images != [container_image, container_image]:
        raise AssertionError(
            "configured PostgreSQL proofs require the selected Flyway image"
        )
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
        "sql/V006__bounded_invocation_release.sql",
        "sql/V007__pending_outbox_specimen_index.sql",
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
    if migration_ids != ["001", "002", "003", "004", "005", "006", "007"]:
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
    observation = json.loads(
        (ROOT / CURRENT_PROMOTION_OBSERVATION_PATH).read_text(encoding="utf-8")
    )
    if machine["schema_release"] != "2.2.0" or not machine["campaigns"]:
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
        machine.get("metadata", {}).get("schema_version") != "2.2.0"
        or first_receipt.get("metadata", {}).get("schema_version") != "2.2.0"
        or horizon.get("metadata", {}).get("schema_version") != "2.2.0"
    ):
        raise AssertionError(
            "orientation metadata requires governance schema release 2.2.0"
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
    database_hosted_evidence = release.get("database_hosted_evidence", {})
    if (
        set(database_hosted_evidence)
        != {"receipt_path", "coordinate_state", "promotion_signal"}
        or database_hosted_evidence.get("receipt_path")
        != "receipts/hosted-postgresql-proof.json"
        or database_hosted_evidence.get("coordinate_state")
        != "v005_observed_successor_candidate"
        or database_hosted_evidence.get("promotion_signal")
        != "implementation-validation"
    ):
        raise AssertionError(
            "release role requires the hosted database evidence coordinate"
        )
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
    if release.get("contract_bindings", {}).get("governance_release") != "2.2.0":
        raise AssertionError("release role requires Governance release 2.2.0")
    if (
        release.get("contract_bindings", {}).get("program_contract_package")
        != "0.6.1"
    ):
        raise AssertionError("release role requires Program contract package 0.6.1")
    if tuple(release["receipt_families"]) != CANONICAL_RECEIPT_FAMILIES:
        raise AssertionError("release role requires canonical receipt-family order")
    if (
        release["selected_future_closure_digest"]
        != CANONICAL_SELECTED_FUTURE_CLOSURE_DIGEST
    ):
        raise AssertionError(
            "release role requires the canonical selected-future closure"
        )
    comparison_return = coordinates["comparison_return"]
    comparison_release = comparison_return["comparison_release"]
    comparison_observation = comparison_return["observation_carrier"]
    comparison_report = comparison_return["golden_specimen_report"]
    comparison_publication = comparison_return["publication"]
    if release.get("comparison_return") != {
        "coordinate_state": "accepted_return",
        "release": comparison_release["release"],
        "release_commit": comparison_release["source_commit"],
        "observation_carrier_commit": comparison_observation["source_commit"],
        "report_digest": comparison_report["report_digest"],
        "leaf_paths_compared": comparison_report["leaf_paths_compared"],
        "classification_counts": comparison_report["classification_counts"],
        "material_divergence_receiver": comparison_report[
            "material_divergence_receiver"
        ],
        "docs_revision": comparison_publication["docs_revision"],
        "projection_manifest_sha256": comparison_publication[
            "projection_manifest_sha256"
        ],
    }:
        raise AssertionError(
            "release role requires the accepted Comparison 0.3.2 return"
        )
    validate_promotion_lifecycle(
        promotion=promotion,
        candidate=candidate,
        observation=observation,
        machine=machine,
        first_receipt=first_receipt,
        horizon=horizon,
        release=release,
        inspection_manifest=inspection_manifest,
    )
    candidate_digest = file_digest(ROOT / CURRENT_PROMOTION_CANDIDATE_PATH)
    observation_digest = file_digest(ROOT / CURRENT_PROMOTION_OBSERVATION_PATH)
    if (
        candidate_digest != CURRENT_CANDIDATE_RECEIPT_DIGEST
        or release["promotion_coordinates"].get("candidate_receipt_digest")
        != candidate_digest
        or release["promotion_coordinates"].get("observation_receipt_digest")
        != observation_digest
    ):
        raise AssertionError(
            "release role requires the exact candidate and observation receipt digests"
        )
    promotion_controls = release.get("promotion_controls", {})
    if (
        promotion_controls.get("current_state")
        != "standing_review_and_history_protection_with_observed_release_admission"
        or promotion_controls.get("hosted_required_check_contexts") != []
        or promotion_controls.get("protected_branches") != ["main"]
        or promotion_controls.get("allowed_merge_methods")
        != ["merge", "squash", "rebase"]
    ):
        raise AssertionError(
            "release controls require the observed review route and history protection"
        )
    if promotion_controls.get("review_observation") != {
        "merge_admission": "configured_ordinary_bypass",
        "independent_review": "deputized_independent_review_completed",
        "github_review_record": "no_formal_review_submitted",
    }:
        raise AssertionError(
            "current release controls require the factual review observation"
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
            "standing release controls require the configured human-review posture"
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
        "github_verified_release_tags": True,
        "configured_signature_rule": "not_required",
    }:
        raise AssertionError(
            "current release controls require the observed merge-signature posture"
        )
    if promotion_controls.get("hosted_check_activation") != {
        "state": "repository_validation_observed",
        "required_check_contexts": [],
        "run_id": "33623991109",
        "job_id": "100227324662",
        "conclusion": "success",
    }:
        raise AssertionError(
            "hosted-check observation requires the successful repository validation job"
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
        "settings_state": "repository_validation_observed_required_contexts_empty",
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
    if receipt["version_bindings"]["repository"] != "0.3.1":
        raise AssertionError(
            "historical local verification receipt requires its observed 0.3.1 release"
        )
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
    binding_kind = classify_hosted_postgresql_receipt_binding(hosted_bindings)
    validate_hosted_postgresql_coordinate_state(
        binding_kind=binding_kind,
        coordinate_state=str(database_hosted_evidence.get("coordinate_state", "")),
    )
    flyway_generation_scenarios = {
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
    if binding_kind == "observed_predecessor":
        predecessor_bindings = {
            "repository": "0.3.1",
            "repository_commit": PREDECESSOR_DATABASE_HOSTED_COMMIT,
            "workflow_run": (
                "https://github.com/driftframestudios/"
                "lims-eln-enterprise-implementation/actions/runs/33590735647"
            ),
            "python": "3.12.14",
            "postgresql": "17.10-alpine",
            "database_migration_head": "005",
            "tenant_authority": "signed_short_lived_database_verified_context",
            "flyway": "13.4.0",
            "flyway_image": (
                "flyway/flyway:13.4.0-alpine@"
                "sha256:66c0278f4398dd46b84d4108919a015b6ca03657a3d44ff2b349ad0602ace956"
            ),
            "migration_authenticated_login": "laboratory_migrator",
            "migration_role": "laboratory_owner",
        }
        predecessor_digests = {
            "sha256:8ebb58455b8db070c8f13b871401bcea9bb630af57a94605e61105f5d89ff1ea",
            "sha256:e5c6daadf3f88df9a83195c7f977dd702c081c796e24e55d67704cfb965cf160",
            "sha256:8bbada0ceaa11f264d2d6ad4c893abd8b4313482da387401fd9b0f1d0106666a",
        }
        successor_pending_limitation = (
            "This receipt establishes the preceding Flyway 13.4.0 hosted "
            "coordinate. The Flyway 13.8.1 successor becomes the current hosted "
            "coordinate when its named implementation-validation run, commit, "
            "and artifact bindings are recorded."
        )
        if (
            hosted_bindings != predecessor_bindings
            or set(hosted_receipt["artifact_digests"]) != predecessor_digests
            or hosted_receipt.get("observed_at") != "2026-09-02T04:27:12Z"
            or not flyway_generation_scenarios.issubset(
                hosted_receipt["scenario_ids"]
            )
            or successor_pending_limitation not in hosted_receipt["limitations"]
        ):
            raise AssertionError(
                "predecessor hosted PostgreSQL receipt requires its exact Flyway 13.4 bindings"
            )
    elif binding_kind == "observed_v005_artifacts":
        validate_current_hosted_postgresql_receipt_contract(hosted_receipt)
        current_bindings = {
            "repository": "0.3.2",
            "repository_commit": CURRENT_DATABASE_HOSTED_COMMIT,
            "workflow_run": (
                "https://github.com/driftframestudios/"
                "lims-eln-enterprise-implementation/actions/runs/37071257377"
            ),
            "python": "3.12.14",
            "postgresql": "17.10-alpine",
            "database_migration_head": "005",
            "tenant_authority": "signed_short_lived_database_verified_context",
            "flyway": "13.8.1",
            "flyway_image": (
                "flyway/flyway:13.8.1-alpine@"
                "sha256:ca3c8eddac25811f84c9767c56a0610ce23cd4e61f59bb05778a78db42347b39"
            ),
            "migration_authenticated_login": "laboratory_migrator",
            "migration_role": "laboratory_owner",
        }
        if (
            hosted_bindings != current_bindings
            or migration_release["flyway_version"] != "13.8.1"
            or migration_release["container_image"]
            != current_bindings["flyway_image"]
        ):
            raise AssertionError(
                "retained hosted PostgreSQL receipt requires the exact observed "
                "Flyway 13.8.1 source, run, and artifact bindings"
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
    collaboration_findings = validate_collaboration_workbench()
    if collaboration_findings:
        raise AssertionError("\n".join(collaboration_findings))
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
        "collaboration_skills": len(PUBLIC_POSSIBLE_SKILL_METADATA),
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
