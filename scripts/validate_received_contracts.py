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
PROGRAM_VERSION = "0.3.1"
PROGRAM_CONTRACT_VERSION = "1.0.0"
PROGRAM_COMMIT = "4d06eeb7f96910311fbcb7f51547c978b6a07290"
PROGRAM_SOURCE_URL = (
    "https://github.com/driftframestudios/lims-eln-program-specification.git"
)
PROGRAM_SOURCE_DIGEST = (
    "sha256:e4d7ef6aa1036b69395e9de3ab0064297dc80e5f697ab60de699a355e45f7674"
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
    "installed distribution version is 0.3.1",
    "lims_eln_contracts.__version__ is 0.3.1",
    "lims_eln_contracts.CONTRACT_VERSION is 1.0.0",
    "the PEP 610 source URL, requested revision, and commit match the reviewed source",
    "the scoped package source digest matches the reviewed binding",
    "the released operation catalog loads",
    "the Golden Specimen scenario loads",
    "the implementation and simulation shaped observations load",
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
    "schema_count": 7,
}

GOVERNANCE_REPOSITORY = "driftframestudios/site-reading-governance"
GOVERNANCE_RELEASE = "2.1.0"
GOVERNANCE_SCHEMA_RELEASE = "2.1.0"
GOVERNANCE_TAG = "governance-v2.1.0"
GOVERNANCE_TAG_OBJECT = "1c77396e44b71719ccab138fecd02e525089e39d"
GOVERNANCE_COMMIT = "8469c2a6b2c7f4445523cee262b961ffe3d2523b"
GOVERNANCE_TREE = "aed5d57120e15ceabe77d7bba700a43097200b19"
GOVERNANCE_ARCHIVE_DIGEST = (
    "sha256:469ae49fca7d5ad6e1766080b3c39d76c46a840366b217f3839b9d34f2e77d32"
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
        },
        "external contract coordinates",
    )
    _require_equal(coordinates["schema_version"], "1.0.0", "coordinate schema")
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
            if "__pycache__" in parts or relative_path.endswith((".pyc", ".pyo")):
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


def validate_installed_program(coordinates: Mapping[str, Any]) -> None:
    """Exercise the nine observations required by the Program publisher."""
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
        observed.append("Comparative release identity")
    if arguments.require_installed_program:
        observed.append("installed Program consumer behavior")
    print("Received contracts valid: " + ", ".join(observed) + ".")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
