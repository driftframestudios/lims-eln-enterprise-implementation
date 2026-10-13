#!/usr/bin/env python3
"""Validate accepted contract and selected-future coordinates at the receiving edge."""

from __future__ import annotations

import argparse
from hashlib import sha256
from importlib import import_module, metadata
import json
from pathlib import Path
import subprocess
import tomllib
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
COORDINATE_PATH = Path("release/external-contract-coordinates.json")

PROGRAM_REPOSITORY = "driftframestudios/lims-eln-program-specification"
PROGRAM_DISTRIBUTION = "lims-eln-program-specification"
PROGRAM_IMPORT = "lims_eln_contracts"
PROGRAM_VERSION = "0.5.0"
PROGRAM_CONTRACT_VERSION = "1.0.0"
PROGRAM_COMMIT = "43a687464b3803a7bcb88d1dcdc4ea39009904de"
PROGRAM_SOURCE_URL = (
    "https://github.com/driftframestudios/lims-eln-program-specification.git"
)
PROGRAM_SOURCE_DIGEST = (
    "sha256:d0c407564024f68dd24ca3f6ddb8bea1d04283b06edb5eedbc146a525df51bf7"
)
PROGRAM_REQUIREMENT = (
    "lims-eln-program-specification @ git+https://github.com/"
    "driftframestudios/lims-eln-program-specification.git@"
    + PROGRAM_COMMIT
)
PROGRAM_CONFORMANCE_COMMAND = (
    "python3 scripts/validate_received_contracts.py --require-installed-program "
    "--program-source ../lims-eln-program-specification"
)
PROGRAM_OBSERVATIONS = {
    "installed distribution version is 0.5.0",
    "lims_eln_contracts.__version__ is 0.5.0",
    "lims_eln_contracts.CONTRACT_VERSION is 1.0.0",
    "the PEP 610 source URL, requested revision, and commit match the reviewed source",
    "the scoped package source digest matches the reviewed binding",
    "the released operation catalog loads",
    "the Golden Specimen scenario loads",
    "the implementation and simulation shaped observations load",
    "the canonical external administrative contract bundle and three examples load",
    "every released schema in SCHEMA_RESOURCE_NAMES loads as a JSON object",
}
PROGRAM_OBSERVED_VALUES = {
    "distribution_version": PROGRAM_VERSION,
    "import_version": PROGRAM_VERSION,
    "contract_version": PROGRAM_CONTRACT_VERSION,
    "direct_url": PROGRAM_SOURCE_URL,
    "direct_url_requested_revision": PROGRAM_COMMIT,
    "direct_url_commit": PROGRAM_COMMIT,
    "source_digest": PROGRAM_SOURCE_DIGEST,
    "operation_count": 3,
    "scenario_id": "SCN-GOLDEN-SPECIMEN-001",
    "observation_producers": ["implementation", "simulation"],
    "schema_count": 11,
    "administrative_resources": ["canonical_bundle", "adapter", "independent_multilabel_policy", "counterfactual"],
}

PROGRAM_SCHEMA_NAMES = (
    "administrative-study.v1.schema.json",
    "administrative-study-comparison.v1.schema.json",
    "bounded-call-receipt.v1.schema.json",
    "bounded-call-request.v1.schema.json",
    "external-administrative-contract-set.v1.schema.json",
    "administrative-adapter-contract.v1.schema.json",
    "golden-specimen-result-projection.v1.schema.json",
    "observation-envelope.v1.schema.json",
    "operation-catalog.v1.schema.json",
    "scenario.v1.schema.json",
    "specimen-command.v1.schema.json",
)
PROGRAM_ADMINISTRATIVE_LOADERS = (
    ("canonical_bundle", "load_external_administrative_contract_set"),
    ("adapter", "load_administrative_adapter_contract_example"),
    ("independent_multilabel_policy", "load_independent_multilabel_policy_example"),
    ("counterfactual", "load_administrative_counterfactual_example"),
)

GOVERNANCE_REPOSITORY = "driftframestudios/site-reading-governance"
GOVERNANCE_RELEASE = "2.2.0"
GOVERNANCE_SCHEMA_RELEASE = "2.2.0"
GOVERNANCE_TAG = "governance-v2.2.0"
GOVERNANCE_TAG_OBJECT = "6acdf4c7e7c200972ee3d7b257f5bc828bde753b"
GOVERNANCE_COMMIT = "c8d7150b8c4e6277bc504a7c69289cb5b949b0ee"
GOVERNANCE_TREE = "451c2e67fa15958ea537dc367fe196467c1e60e5"
GOVERNANCE_ARCHIVE_DIGEST = (
    "sha256:2da503b695252fde152f2f7765776e4c784b9afeec463dae592a7a6012126a58"
)

SELECTED_FUTURE_CLOSURE_ID = "CLOSURE-SIM-SUBSTANTIVE-2028-V1"
SELECTED_FUTURE_VERSION = "future-reality-2028-06-30-v1"
SELECTED_FUTURE_CANONICALIZATION = (
    "python-json-sort-keys-compact-ascii-sha256-v1"
)
SELECTED_FUTURE_CLOSURE_DIGEST = (
    "sha256:33bcc14da24309b7716728b3f0204008e8f7ebf58de75f9e40a5986b421f06b5"
)
SELECTED_FUTURE_SOURCES = (
    {
        "role": "simulated_final_state",
        "repository": "driftframestudios/lims-eln-simulated-final-state",
        "release": "forecast-2028-FR-v1",
        "tag_object": "73fc89690b6cc9df7a99ea495e580e7f4e2caedc",
        "source_commit": "37c3861b5411db8e772feedf41e4abf1fb7829bc",
        "source_tree": "595ae59f25f522732577c5f8e00709f023464a6d",
        "closure_artifact_path": "release/future-reality-2028-06-30-v1.json",
        "git_archive_sha256": (
            "sha256:c6a062a6efb6786c53dc9e7298a9dd881fcc2301d807db5cecf84663c98438e2"
        ),
    },
    {
        "role": "comparative_evidence",
        "repository": "driftframestudios/lims-eln-comparative-evidence",
        "release": "comparison-v0.3.1",
        "tag_object": "4c29f6ca410eb4400c55ad77fc34ada2960d1972",
        "source_commit": "b5c13689a32739d29437e209816bf0cd6a878976",
        "source_tree": "10a784b8a677ee6eb524d2860ff5ee7151d6050b",
        "closure_artifact_path": (
            "fixtures/simulated-closures/future-reality-2028-06-30-v1.json"
        ),
        "git_archive_sha256": (
            "sha256:92c2d57bd9e75c650365db4b481a22a6580b201926ba1c666fcf8cb8c9311a2e"
        ),
    },
)

COMPARISON_REPOSITORY = "driftframestudios/lims-eln-comparative-evidence"
COMPARISON_RELEASE = "comparison-v0.3.2"
COMPARISON_TAG_OBJECT = "ccc4b206d9071933516863ee0eb3f5b091fc76b0"
COMPARISON_RELEASE_COMMIT = "0289ff835c790693a769347e69da0abdcfaa47de"
COMPARISON_RELEASE_TREE = "60c85e4206e2d487dac83d521401816dec0f34ae"
COMPARISON_ARCHIVE_DIGEST = (
    "sha256:5c1697f98655ce1979fcc6f4a85b719e0c44afde8a3004037d19dd1416d0720e"
)
COMPARISON_OBSERVATION_COMMIT = "2cca88982444ebc8280f9eb2891d97bf25dbeb95"
COMPARISON_OBSERVATION_PATH = "receipts/promotion-observation-v0.3.2.json"
COMPARISON_OBSERVATION_FILE_DIGEST = (
    "sha256:acccb507f0675cdc079aa56bc12299bd4ce533344cb150e42dba1c991c024fd4"
)
COMPARISON_RECORD_COMMIT = "c854a6f58c587a0b099efa24d2b745b2bd7187df"
COMPARISON_DOCS_COMMIT = "6ccc087875b439eb70304771f534434acae3f01c"
COMPARISON_PROJECTION_MANIFEST_PATH = "projection-manifest.json"
COMPARISON_PROJECTION_MANIFEST_DIGEST = (
    "sha256:38d01a78be6804d04bc4f24c412777b8cb08fe2c65372e278480c106b4bcbeea"
)
COMPARISON_CANONICAL_ORIGIN = "https://cometspectrum.io/"
COMPARISON_REPORT_PATH = "reports/golden-specimen/comparison.json"
COMPARISON_REPORT_DIGEST = "sha256:a2f92ae4acb9fb7d835d0a9b126bb1932ae69b06b094303180dd9fea7217b77c"
COMPARISON_CLASSIFICATION_COUNTS = {
    "agreement": 10,
    "explainable_variation": 4,
    "material_divergence": 3,
}
COMPARISON_MATERIAL_PATHS = [
    "$.measurement.analyte",
    "$.measurement.value",
    "$.measurement.unit",
]

COMPARED_IMPLEMENTATION_RELEASE = {
    "tag": "v0.3.2",
    "tag_object": "c3db01079b88622f06e8714c8bcbdf0dc1803a10",
    "source_commit": "fe0bd2a08ac1697ce18ca583d9631faae7db7132",
    "source_tree": "eb8eadb27a9e07c6069a1946f115a0083d94af5c",
    "git_archive_sha256": (
        "sha256:0ea3db3099e3485f65d238fb2e194c6bfd9b9a90f6642431c4a96974ebcc3c16"
    ),
}


class ReceivedContractError(ValueError):
    """An accepted coordinate or receiving observation differs from its binding."""


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReceivedContractError(f"{label} requires one object")
    return value


def _require_exact_keys(
    value: Mapping[str, Any], expected: set[str], label: str
) -> None:
    if set(value) != expected:
        raise ReceivedContractError(
            f"{label} fields differ: expected {sorted(expected)}, "
            f"observed {sorted(value)}"
        )


def _require_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise ReceivedContractError(
            f"{label} differs: expected {expected!r}, observed {actual!r}"
        )


def load_coordinates(root: Path = ROOT) -> dict[str, Any]:
    path = root / COORDINATE_PATH
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReceivedContractError(
            "external contract coordinates require one UTF-8 JSON document"
        ) from error
    return validate_coordinate_document(document)


def validate_coordinate_document(document: Any) -> dict[str, Any]:
    coordinates = _require_mapping(document, "external contract coordinates")
    _require_exact_keys(
        coordinates,
        {
            "schema_version",
            "consumer",
            "coordinate_state",
            "program_contract",
            "governance",
            "selected_future",
            "comparison_return",
        },
        "external contract coordinates",
    )
    _require_equal(coordinates["schema_version"], "1.1.0", "coordinate schema")
    _require_equal(
        coordinates["consumer"],
        "driftframestudios/lims-eln-enterprise-implementation",
        "coordinate consumer",
    )
    _require_equal(
        coordinates["coordinate_state"],
        "accepted_and_consumer_observed",
        "coordinate state",
    )

    program = _require_mapping(coordinates["program_contract"], "program contract")
    _require_exact_keys(
        program,
        {
            "repository",
            "distribution_name",
            "import_name",
            "package_version",
            "contract_version",
            "source_commit",
            "source_identity",
            "requirement",
            "consumer_conformance",
        },
        "program contract",
    )
    for key, expected in {
        "repository": PROGRAM_REPOSITORY,
        "distribution_name": PROGRAM_DISTRIBUTION,
        "import_name": PROGRAM_IMPORT,
        "package_version": PROGRAM_VERSION,
        "contract_version": PROGRAM_CONTRACT_VERSION,
        "source_commit": PROGRAM_COMMIT,
        "requirement": PROGRAM_REQUIREMENT,
    }.items():
        _require_equal(program[key], expected, f"program {key}")

    source_identity = _require_mapping(
        program["source_identity"], "program source identity"
    )
    _require_exact_keys(
        source_identity,
        {"scope", "algorithm", "digest"},
        "program source identity",
    )
    _require_equal(
        source_identity["scope"],
        ["pyproject.toml", "src/lims_eln_contracts"],
        "program source scope",
    )
    _require_equal(
        source_identity["algorithm"],
        "path-length-bytes-sha256-v1",
        "program source digest algorithm",
    )
    _require_equal(
        source_identity["digest"], PROGRAM_SOURCE_DIGEST, "program source digest"
    )

    conformance = _require_mapping(
        program["consumer_conformance"], "program consumer conformance"
    )
    _require_exact_keys(
        conformance,
        {"state", "environment", "command", "observed_values", "observations"},
        "program consumer conformance",
    )
    _require_equal(conformance["state"], "observed", "consumer conformance state")
    _require_equal(
        conformance["environment"],
        "clean Python 3.12 environment",
        "consumer conformance environment",
    )
    _require_equal(
        conformance["command"],
        PROGRAM_CONFORMANCE_COMMAND,
        "consumer conformance command",
    )
    _require_equal(
        conformance["observed_values"],
        PROGRAM_OBSERVED_VALUES,
        "program consumer observed values",
    )
    observations = conformance["observations"]
    if (
        not isinstance(observations, list)
        or any(not isinstance(item, str) or not item for item in observations)
        or len(observations) != len(set(observations))
    ):
        raise ReceivedContractError(
            "program consumer observations require unique non-empty strings"
        )
    _require_equal(
        set(observations), PROGRAM_OBSERVATIONS, "program consumer observations"
    )

    governance = _require_mapping(coordinates["governance"], "governance")
    _require_exact_keys(
        governance,
        {
            "repository",
            "release",
            "schema_release",
            "annotated_tag",
            "tag_object",
            "source_commit",
            "source_tree",
            "git_archive_sha256",
        },
        "governance",
    )
    for key, expected in {
        "repository": GOVERNANCE_REPOSITORY,
        "release": GOVERNANCE_RELEASE,
        "schema_release": GOVERNANCE_SCHEMA_RELEASE,
        "annotated_tag": GOVERNANCE_TAG,
        "tag_object": GOVERNANCE_TAG_OBJECT,
        "source_commit": GOVERNANCE_COMMIT,
        "source_tree": GOVERNANCE_TREE,
        "git_archive_sha256": GOVERNANCE_ARCHIVE_DIGEST,
    }.items():
        _require_equal(governance[key], expected, f"governance {key}")

    selected_future = _require_mapping(
        coordinates["selected_future"], "selected future"
    )
    _require_exact_keys(
        selected_future,
        {
            "closure_id",
            "future_reality_version",
            "canonicalization",
            "canonical_closure_digest",
            "accepted_sources",
        },
        "selected future",
    )
    for key, expected in {
        "closure_id": SELECTED_FUTURE_CLOSURE_ID,
        "future_reality_version": SELECTED_FUTURE_VERSION,
        "canonicalization": SELECTED_FUTURE_CANONICALIZATION,
        "canonical_closure_digest": SELECTED_FUTURE_CLOSURE_DIGEST,
    }.items():
        _require_equal(selected_future[key], expected, f"selected future {key}")

    sources = selected_future["accepted_sources"]
    if not isinstance(sources, list):
        raise ReceivedContractError("selected-future sources require one ordered array")
    _require_equal(tuple(sources), SELECTED_FUTURE_SOURCES, "selected-future sources")

    comparison_return = _require_mapping(coordinates["comparison_return"], "comparison return")
    _require_exact_keys(
        comparison_return,
        {
            "relation",
            "repository",
            "evidence_mode",
            "assurance_stage",
            "production_authorization_effect",
            "compared_implementation_release",
            "comparison_release",
            "observation_carrier",
            "golden_specimen_report",
            "publication",
        },
        "comparison return",
    )
    for key, expected in {
        "relation": "compares_implementation_release_to_selected_future",
        "repository": COMPARISON_REPOSITORY,
        "evidence_mode": "simulated",
        "assurance_stage": "verified",
        "production_authorization_effect": "none",
    }.items():
        _require_equal(comparison_return[key], expected, f"comparison return {key}")

    implementation = _require_mapping(
        comparison_return["compared_implementation_release"],
        "compared implementation release",
    )
    _require_exact_keys(
        implementation,
        {"tag", "tag_object", "source_commit", "source_tree", "git_archive_sha256"},
        "compared implementation release",
    )
    _require_equal(
        implementation,
        COMPARED_IMPLEMENTATION_RELEASE,
        "compared implementation release",
    )

    comparison_release = _require_mapping(
        comparison_return["comparison_release"], "comparison release"
    )
    _require_exact_keys(
        comparison_release,
        {
            "release",
            "tag_object",
            "source_commit",
            "source_tree",
            "git_archive_sha256",
        },
        "comparison release",
    )
    _require_equal(
        comparison_release,
        {
            "release": COMPARISON_RELEASE,
            "tag_object": COMPARISON_TAG_OBJECT,
            "source_commit": COMPARISON_RELEASE_COMMIT,
            "source_tree": COMPARISON_RELEASE_TREE,
            "git_archive_sha256": COMPARISON_ARCHIVE_DIGEST,
        },
        "comparison release",
    )

    observation = _require_mapping(
        comparison_return["observation_carrier"], "comparison observation carrier"
    )
    _require_exact_keys(
        observation,
        {"source_commit", "receipt_path", "receipt_file_sha256"},
        "comparison observation carrier",
    )
    _require_equal(
        observation,
        {
            "source_commit": COMPARISON_OBSERVATION_COMMIT,
            "receipt_path": COMPARISON_OBSERVATION_PATH,
            "receipt_file_sha256": COMPARISON_OBSERVATION_FILE_DIGEST,
        },
        "comparison observation carrier",
    )

    report = _require_mapping(
        comparison_return["golden_specimen_report"], "Golden Specimen report return"
    )
    _require_exact_keys(
        report,
        {
            "report_path",
            "report_digest",
            "leaf_paths_compared",
            "classification_counts",
            "material_divergence_paths",
            "material_divergence_receiver",
        },
        "Golden Specimen report return",
    )
    _require_equal(report["report_path"], COMPARISON_REPORT_PATH, "comparison report path")
    _require_equal(report["report_digest"], COMPARISON_REPORT_DIGEST, "comparison report digest")
    _require_equal(report["leaf_paths_compared"], 17, "comparison leaf count")
    _require_equal(
        report["classification_counts"],
        COMPARISON_CLASSIFICATION_COUNTS,
        "comparison classification counts",
    )
    _require_equal(
        report["material_divergence_paths"],
        COMPARISON_MATERIAL_PATHS,
        "comparison material divergence paths",
    )
    _require_equal(
        report["material_divergence_receiver"],
        "accountable_scientific_mapping",
        "comparison material divergence receiver",
    )

    publication = _require_mapping(comparison_return["publication"], "comparison publication")
    _require_exact_keys(
        publication,
        {
            "record_carrier_commit",
            "source_revision",
            "docs_revision",
            "projection_manifest_path",
            "projection_manifest_sha256",
            "canonical_origin",
        },
        "comparison publication",
    )
    _require_equal(
        publication,
        {
            "record_carrier_commit": COMPARISON_RECORD_COMMIT,
            "source_revision": COMPARISON_OBSERVATION_COMMIT,
            "docs_revision": COMPARISON_DOCS_COMMIT,
            "projection_manifest_path": COMPARISON_PROJECTION_MANIFEST_PATH,
            "projection_manifest_sha256": COMPARISON_PROJECTION_MANIFEST_DIGEST,
            "canonical_origin": COMPARISON_CANONICAL_ORIGIN,
        },
        "comparison publication",
    )

    return coordinates


def validate_declared_program_requirement(
    root: Path, coordinates: Mapping[str, Any]
) -> None:
    """Bind the installable dependency declaration to the accepted coordinate."""
    try:
        project_document = tomllib.loads(
            (root / "pyproject.toml").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise ReceivedContractError(
            "Program dependency binding requires one UTF-8 pyproject.toml"
        ) from error
    project = _require_mapping(project_document.get("project"), "Python project")
    optional_dependencies = _require_mapping(
        project.get("optional-dependencies"), "Python optional dependencies"
    )
    program = _require_mapping(coordinates["program_contract"], "program contract")
    _require_equal(
        optional_dependencies.get("contracts"),
        [program["requirement"]],
        "declared Program contracts dependency",
    )


def _run_git(root: Path, *arguments: str, text: bool = True) -> str | bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            text=text,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReceivedContractError(
            f"received source cannot resolve git {' '.join(arguments)}"
        ) from error
    return completed.stdout.strip() if text else completed.stdout


def _strict_json_object_from_commit(
    root: Path,
    *,
    commit: str,
    relative_path: str,
    label: str,
) -> dict[str, Any]:
    """Read one duplicate-free, finite JSON object from an accepted Git commit."""

    raw = _run_git(root, "show", f"{commit}:{relative_path}", text=False)
    assert isinstance(raw, bytes)

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        document: dict[str, Any] = {}
        for key, value in pairs:
            if key in document:
                raise ValueError(f"duplicate key {key!r}")
            document[key] = value
        return document

    def reject_nonfinite(token: str) -> None:
        raise ValueError(f"non-finite number {token!r}")

    try:
        parsed = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ReceivedContractError(
            f"{label} requires one duplicate-free finite UTF-8 JSON document"
        ) from error
    return _require_mapping(parsed, label)


def _canonical_json_digest(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + sha256(payload).hexdigest()


def _comparison_report_digest(value: Mapping[str, Any]) -> str:
    """Reproduce Comparison's source-owned UTF-8 canonical JSON digest."""
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + sha256(payload).hexdigest()


def program_source_digest_from_git(root: Path, commit: str) -> str:
    """Reproduce the Program package digest from one local commit object."""
    resolved = _run_git(root, "rev-parse", f"{commit}^{{commit}}")
    if resolved != commit:
        raise ReceivedContractError(
            "Program source coordinate requires the exact commit object"
        )
    listing = _run_git(
        root,
        "ls-tree",
        "-r",
        "-z",
        commit,
        "--",
        "pyproject.toml",
        "src/lims_eln_contracts",
        text=False,
    )
    assert isinstance(listing, bytes)

    records: list[tuple[bytes, bytes]] = []
    observed_metadata = False
    observed_package_file = False
    for entry in listing.split(b"\0"):
        if not entry:
            continue
        try:
            identity, raw_path = entry.split(b"\t", 1)
            mode, object_type, object_id = identity.split(b" ", 2)
            relative_path = raw_path.decode("utf-8")
        except (UnicodeError, ValueError) as error:
            raise ReceivedContractError("Program package tree is malformed") from error
        if relative_path == "pyproject.toml":
            observed_metadata = True
        elif relative_path.startswith("src/lims_eln_contracts/"):
            parts = relative_path.removeprefix("src/lims_eln_contracts/").split("/")
            if (
                parts == ["README.md"]
                or "__pycache__" in parts
                or relative_path.endswith((".pyc", ".pyo"))
            ):
                continue
            observed_package_file = True
        else:
            continue
        if mode not in {b"100644", b"100755"} or object_type != b"blob":
            raise ReceivedContractError(
                "Program package digest scope requires regular files"
            )
        content = _run_git(root, "cat-file", "blob", object_id.decode("ascii"), text=False)
        assert isinstance(content, bytes)
        records.append((raw_path, content))
    if not observed_metadata or not observed_package_file:
        raise ReceivedContractError("Program package digest scope is incomplete")

    digest = sha256()
    for relative_path, content in sorted(records, key=lambda record: record[0]):
        digest.update(len(relative_path).to_bytes(8, "big"))
        digest.update(relative_path)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return "sha256:" + digest.hexdigest()


def validate_program_source(root: Path, coordinates: Mapping[str, Any]) -> None:
    program = _require_mapping(coordinates["program_contract"], "program contract")
    digest = program_source_digest_from_git(root, program["source_commit"])
    _require_equal(
        digest,
        program["source_identity"]["digest"],
        "received Program package source digest",
    )


def validate_governance_source(root: Path, coordinates: Mapping[str, Any]) -> None:
    governance = _require_mapping(coordinates["governance"], "governance")
    _require_equal(
        _run_git(root, "cat-file", "-t", governance["tag_object"]),
        "tag",
        "Governance release object type",
    )
    _require_equal(
        _run_git(root, "rev-parse", f"refs/tags/{governance['annotated_tag']}"),
        governance["tag_object"],
        "Governance annotated tag object",
    )
    _require_equal(
        _run_git(root, "rev-parse", f"{governance['annotated_tag']}^{{commit}}"),
        governance["source_commit"],
        "Governance accepted commit",
    )
    _require_equal(
        _run_git(root, "rev-parse", f"{governance['source_commit']}^{{tree}}"),
        governance["source_tree"],
        "Governance accepted tree",
    )
    archive = _run_git(
        root, "archive", "--format=tar", governance["source_commit"], text=False
    )
    assert isinstance(archive, bytes)
    _require_equal(
        "sha256:" + sha256(archive).hexdigest(),
        governance["git_archive_sha256"],
        "Governance git archive digest",
    )


def validate_selected_future_source(
    root: Path,
    coordinates: Mapping[str, Any],
    *,
    role: str,
) -> None:
    """Reproduce one accepted selected-future release subject."""
    selected_future = _require_mapping(
        coordinates["selected_future"], "selected future"
    )
    sources = selected_future["accepted_sources"]
    source = next((item for item in sources if item.get("role") == role), None)
    if source is None:
        raise ReceivedContractError(
            f"selected-future source role {role!r} requires an accepted coordinate"
        )
    _require_equal(
        _run_git(root, "cat-file", "-t", source["tag_object"]),
        "tag",
        f"{role} release object type",
    )
    _require_equal(
        _run_git(root, "rev-parse", f"refs/tags/{source['release']}"),
        source["tag_object"],
        f"{role} annotated tag object",
    )
    _require_equal(
        _run_git(root, "rev-parse", f"{source['release']}^{{commit}}"),
        source["source_commit"],
        f"{role} accepted commit",
    )
    _require_equal(
        _run_git(root, "rev-parse", f"{source['source_commit']}^{{tree}}"),
        source["source_tree"],
        f"{role} accepted tree",
    )
    archive = _run_git(
        root, "archive", "--format=tar", source["source_commit"], text=False
    )
    assert isinstance(archive, bytes)
    _require_equal(
        "sha256:" + sha256(archive).hexdigest(),
        source["git_archive_sha256"],
        f"{role} git archive digest",
    )

    bundle = _strict_json_object_from_commit(
        root,
        commit=source["source_commit"],
        relative_path=source["closure_artifact_path"],
        label=f"{role} closure bundle",
    )
    _require_equal(
        bundle.get("future_reality_version"),
        selected_future["future_reality_version"],
        f"{role} closure bundle future reality",
    )
    governance_closure = _require_mapping(
        bundle.get("governance_closure"), f"{role} governance closure"
    )
    _require_equal(
        governance_closure.get("closure_id"),
        selected_future["closure_id"],
        f"{role} closure bundle closure_id",
    )
    reproduced_digest = _canonical_json_digest(governance_closure)
    _require_equal(
        bundle.get("governance_closure_digest"),
        reproduced_digest,
        f"{role} closure bundle governance_closure_digest",
    )
    _require_equal(
        selected_future["canonical_closure_digest"],
        reproduced_digest,
        f"{role} selected-future canonical closure digest",
    )


def _require_ancestor(root: Path, ancestor: str, descendant: str, label: str) -> None:
    try:
        subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", ancestor, descendant],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReceivedContractError(f"{label} requires an ancestor relation") from error


def validate_comparison_return_source(root: Path, coordinates: Mapping[str, Any]) -> None:
    """Reproduce the accepted comparison return from local Git objects."""

    comparison_return = _require_mapping(coordinates["comparison_return"], "comparison return")
    release = _require_mapping(comparison_return["comparison_release"], "comparison release")
    observation = _require_mapping(
        comparison_return["observation_carrier"], "comparison observation carrier"
    )
    report_coordinate = _require_mapping(
        comparison_return["golden_specimen_report"], "Golden Specimen report return"
    )
    publication = _require_mapping(comparison_return["publication"], "comparison publication")

    _require_equal(
        _run_git(root, "cat-file", "-t", release["tag_object"]),
        "tag",
        "comparison return release object type",
    )
    _require_equal(
        _run_git(root, "rev-parse", f"refs/tags/{release['release']}"),
        release["tag_object"],
        "comparison return annotated tag object",
    )
    _require_equal(
        _run_git(root, "rev-parse", f"{release['release']}^{{commit}}"),
        release["source_commit"],
        "comparison return release commit",
    )
    _require_equal(
        _run_git(root, "rev-parse", f"{release['source_commit']}^{{tree}}"),
        release["source_tree"],
        "comparison return release tree",
    )
    archive = _run_git(root, "archive", "--format=tar", release["source_commit"], text=False)
    assert isinstance(archive, bytes)
    _require_equal(
        "sha256:" + sha256(archive).hexdigest(),
        release["git_archive_sha256"],
        "comparison return archive digest",
    )

    _require_ancestor(
        root,
        release["source_commit"],
        observation["source_commit"],
        "comparison observation carrier",
    )
    _require_ancestor(
        root,
        observation["source_commit"],
        publication["record_carrier_commit"],
        "comparison record carrier",
    )

    receipt_bytes = _run_git(
        root,
        "show",
        f"{observation['source_commit']}:{observation['receipt_path']}",
        text=False,
    )
    assert isinstance(receipt_bytes, bytes)
    _require_equal(
        "sha256:" + sha256(receipt_bytes).hexdigest(),
        observation["receipt_file_sha256"],
        "comparison observation receipt file digest",
    )
    receipt = _strict_json_object_from_commit(
        root,
        commit=observation["source_commit"],
        relative_path=observation["receipt_path"],
        label="comparison observation receipt",
    )
    _require_equal(
        receipt.get("repository"),
        comparison_return["repository"],
        "comparison observation repository",
    )
    _require_equal(
        receipt.get("target_release"),
        release["release"],
        "comparison observation target release",
    )
    _require_equal(
        receipt.get("promotion_state"),
        "release_observed",
        "comparison observation state",
    )
    receipt_release = _require_mapping(
        receipt.get("release_coordinate"), "comparison observation release coordinate"
    )
    for receipt_key, source_key in {
        "tag": "release",
        "tag_object_oid": "tag_object",
        "commit_oid": "source_commit",
        "tree_oid": "source_tree",
        "archive_digest": "git_archive_sha256",
    }.items():
        _require_equal(
            receipt_release.get(receipt_key),
            release[source_key],
            f"comparison observation {receipt_key}",
        )

    lock = _strict_json_object_from_commit(
        root,
        commit=release["source_commit"],
        relative_path="constellation.lock.json",
        label="comparison release constellation lock",
    )
    implementation = _require_mapping(lock.get("implementation"), "comparison implementation lock")
    compared = comparison_return["compared_implementation_release"]
    for lock_key, source_key in {
        "release": "tag",
        "tag_object_oid": "tag_object",
        "commit": "source_commit",
        "archive_digest": "git_archive_sha256",
    }.items():
        _require_equal(
            implementation.get(lock_key),
            compared[source_key],
            f"comparison implementation {lock_key}",
        )
    _require_equal(
        implementation.get("digest"),
        "git-tree-sha1:" + compared["source_tree"],
        "comparison implementation tree",
    )

    record_role = _strict_json_object_from_commit(
        root,
        commit=publication["record_carrier_commit"],
        relative_path="release/repository-role.json",
        label="comparison record carrier",
    )
    _require_equal(record_role.get("repository_release"), "0.3.2", "comparison record release")
    verification = _require_mapping(
        record_role.get("golden_specimen_verification"),
        "comparison record Golden Specimen verification",
    )
    for key in ("report_digest", "classification_counts"):
        _require_equal(
            verification.get(key),
            report_coordinate[key],
            f"comparison record {key}",
        )
    record_publication = _require_mapping(
        record_role.get("publication_coordinates"), "comparison record publication"
    )
    for record_key, source_key in {
        "source_revision": "source_revision",
        "docs_revision": "docs_revision",
        "projection_manifest_sha256": "projection_manifest_sha256",
        "canonical_origin": "canonical_origin",
    }.items():
        _require_equal(
            record_publication.get(record_key),
            publication[source_key],
            f"comparison record publication {record_key}",
        )

    manifest_bytes = _run_git(
        root,
        "show",
        f"{publication['docs_revision']}:{publication['projection_manifest_path']}",
        text=False,
    )
    assert isinstance(manifest_bytes, bytes)
    _require_equal(
        "sha256:" + sha256(manifest_bytes).hexdigest(),
        publication["projection_manifest_sha256"],
        "comparison projection manifest digest",
    )
    projection_manifest = _strict_json_object_from_commit(
        root,
        commit=publication["docs_revision"],
        relative_path=publication["projection_manifest_path"],
        label="comparison projection manifest",
    )
    _require_equal(
        projection_manifest.get("sourceRevision"),
        publication["source_revision"],
        "comparison projection source revision",
    )
    _require_equal(
        projection_manifest.get("goldenSpecimenReportDigest"),
        report_coordinate["report_digest"],
        "comparison projection Golden Specimen digest",
    )
    _require_equal(
        projection_manifest.get("canonicalOrigin"),
        publication["canonical_origin"],
        "comparison projection canonical origin",
    )

    report = _strict_json_object_from_commit(
        root,
        commit=publication["docs_revision"],
        relative_path=report_coordinate["report_path"],
        label="comparison Golden Specimen report",
    )
    unsigned_report = dict(report)
    declared_report_digest = unsigned_report.pop("report_digest", None)
    _require_equal(
        declared_report_digest,
        report_coordinate["report_digest"],
        "comparison Golden Specimen report digest",
    )
    _require_equal(
        _comparison_report_digest(unsigned_report),
        report_coordinate["report_digest"],
        "comparison Golden Specimen reproduced digest",
    )
    summary = _require_mapping(report.get("summary"), "comparison report summary")
    _require_equal(
        summary.get("leaf_paths_compared"),
        report_coordinate["leaf_paths_compared"],
        "comparison report leaf count",
    )
    _require_equal(
        summary.get("classification_counts"),
        report_coordinate["classification_counts"],
        "comparison report classification counts",
    )
    material_paths = [
        item.get("path")
        for item in report.get("comparisons", [])
        if isinstance(item, dict) and item.get("classification") == "material_divergence"
    ]
    _require_equal(
        material_paths,
        report_coordinate["material_divergence_paths"],
        "comparison report material divergence paths",
    )


def validate_installed_program(coordinates: Mapping[str, Any]) -> None:
    """Exercise the installed-package observations required by Program."""
    program = _require_mapping(coordinates["program_contract"], "program contract")
    try:
        distribution = metadata.distribution(program["distribution_name"])
        contracts = import_module(program["import_name"])
    except (metadata.PackageNotFoundError, ModuleNotFoundError) as error:
        raise ReceivedContractError(
            "Program consumer conformance requires the reviewed distribution"
        ) from error

    _require_equal(
        distribution.version,
        program["package_version"],
        "installed Program distribution version",
    )
    _require_equal(
        getattr(contracts, "__version__", None),
        program["package_version"],
        "installed Program import version",
    )
    _require_equal(
        getattr(contracts, "CONTRACT_VERSION", None),
        program["contract_version"],
        "installed Program contract version",
    )

    distribution_files = distribution.files
    module_file = getattr(contracts, "__file__", None)
    if distribution_files is None or not isinstance(module_file, str):
        raise ReceivedContractError(
            "installed Program import requires distribution-owned module files"
        )
    owned_files = {
        Path(distribution.locate_file(relative_path)).resolve()
        for relative_path in distribution_files
    }
    if Path(module_file).resolve() not in owned_files:
        raise ReceivedContractError(
            "installed Program import requires the reviewed distribution owner"
        )

    direct_url_text = distribution.read_text("direct_url.json")
    if direct_url_text is None:
        raise ReceivedContractError(
            "installed Program distribution requires its PEP 610 direct_url.json"
        )
    try:
        direct_url = json.loads(direct_url_text)
    except json.JSONDecodeError as error:
        raise ReceivedContractError(
            "installed Program PEP 610 record requires valid JSON"
        ) from error
    direct_url = _require_mapping(direct_url, "Program PEP 610 record")
    _require_equal(
        direct_url.get("url"),
        PROGRAM_SOURCE_URL,
        "installed Program source URL",
    )
    vcs_info = _require_mapping(direct_url.get("vcs_info"), "Program PEP 610 vcs_info")
    _require_equal(vcs_info.get("vcs"), "git", "Program PEP 610 VCS")
    _require_equal(
        vcs_info.get("requested_revision"),
        program["source_commit"],
        "installed Program requested revision",
    )
    _require_equal(
        vcs_info.get("commit_id"),
        program["source_commit"],
        "installed Program commit",
    )

    observed_values = program["consumer_conformance"]["observed_values"]
    catalog = contracts.load_operation_catalog()
    _require_equal(
        len(catalog.operations),
        observed_values["operation_count"],
        "Program operation count",
    )
    scenario = contracts.load_golden_specimen_scenario()
    _require_equal(
        scenario.scenario_id,
        observed_values["scenario_id"],
        "Program Golden Specimen scenario",
    )
    for producer in observed_values["observation_producers"]:
        observation = contracts.load_golden_specimen_observation_example(producer)
        _require_equal(
            observation.scenario_id,
            scenario.scenario_id,
            f"Program {producer} observation scenario",
        )
    _require_equal(
        len(contracts.SCHEMA_RESOURCE_NAMES),
        observed_values["schema_count"],
        "Program schema inventory count",
    )
    _require_equal(
        tuple(contracts.SCHEMA_RESOURCE_NAMES),
        PROGRAM_SCHEMA_NAMES,
        "Program schema inventory names",
    )
    loaded_resources = []
    for resource_name, loader_name in PROGRAM_ADMINISTRATIVE_LOADERS:
        loader = getattr(contracts, loader_name, None)
        if not callable(loader):
            raise ReceivedContractError(
                f"Program administrative resource {resource_name} requires {loader_name}"
            )
        try:
            resource = loader()
        except (OSError, ValueError) as error:
            raise ReceivedContractError(
                f"Program administrative resource {resource_name} requires readable, valid content"
            ) from error
        if resource is None:
            raise ReceivedContractError(
                f"Program administrative resource {resource_name} requires populated content"
            )
        loaded_resources.append(resource_name)
    _require_equal(
        loaded_resources,
        observed_values["administrative_resources"],
        "Program administrative resource inventory",
    )
    for schema_name in contracts.SCHEMA_RESOURCE_NAMES:
        schema = contracts.load_generated_schema(schema_name)
        if not isinstance(schema, dict):
            raise ReceivedContractError(
                f"Program schema {schema_name} requires one JSON object"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--program-source",
        type=Path,
        help="local Program repository containing the accepted commit object",
    )
    parser.add_argument(
        "--governance-source",
        type=Path,
        help="local Governance repository containing the accepted annotated tag",
    )
    parser.add_argument(
        "--simulation-source",
        type=Path,
        help="local Simulation repository containing the accepted annotated tag",
    )
    parser.add_argument(
        "--comparison-source",
        type=Path,
        help="local Comparative repository containing the accepted annotated tag",
    )
    parser.add_argument(
        "--require-installed-program",
        action="store_true",
        help="exercise the publisher-required installed-distribution observations",
    )
    arguments = parser.parse_args()

    coordinates = load_coordinates()
    validate_declared_program_requirement(ROOT, coordinates)
    if arguments.require_installed_program and arguments.program_source is None:
        parser.error("--require-installed-program also requires --program-source")
    if arguments.program_source is not None:
        validate_program_source(arguments.program_source, coordinates)
    if arguments.governance_source is not None:
        validate_governance_source(arguments.governance_source, coordinates)
    if arguments.simulation_source is not None:
        validate_selected_future_source(
            arguments.simulation_source,
            coordinates,
            role="simulated_final_state",
        )
    if arguments.comparison_source is not None:
        validate_selected_future_source(
            arguments.comparison_source,
            coordinates,
            role="comparative_evidence",
        )
        validate_comparison_return_source(arguments.comparison_source, coordinates)
    if arguments.require_installed_program:
        validate_installed_program(coordinates)

    observed = ["coordinate document", "declared Program dependency"]
    if arguments.program_source is not None:
        observed.append("Program source digest")
    if arguments.governance_source is not None:
        observed.append("Governance release identity")
    if arguments.simulation_source is not None:
        observed.append("Simulation release identity")
    if arguments.comparison_source is not None:
        observed.extend(
            [
                "Comparative selected-future identity",
                "Comparison 0.3.2 return and publication record",
            ]
        )
    if arguments.require_installed_program:
        observed.append("installed Program consumer behavior")
    print("Received contracts valid: " + ", ".join(observed) + ".")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
