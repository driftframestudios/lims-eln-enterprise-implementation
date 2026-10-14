#!/usr/bin/env python3
"""Receive a Program lifecycle record through the separately pinned source profile.

Program owns semantic admission. This receiver selects its trusted package and
schema coordinate and returns documentary evidence without operating a database.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
from importlib import import_module, metadata
from importlib.util import find_spec
import json
import os
from pathlib import Path
import stat
import sys


ROOT = Path(__file__).resolve().parents[1]
PROGRAM_VERSION = "0.7.0"
PROGRAM_COMMIT = "ea0140036a3392557eed78124cdf9e3831bff999"
PROGRAM_SOURCE_DIGEST = "sha256:de724ba26579094771e61571fa67efdf6faf1e20e328a3672ff05c761100b47d"
PROGRAM_URL = "https://github.com/driftframestudios/lims-eln-program-specification.git"
SOURCE_REF = "ref:program-database-lifecycle"
SCHEMA_ID = "urn:driftframe:lims-eln:database-lifecycle-profile:1.0.0"
SCHEMA_SHA256 = "baf035a23aee30c09f410ec157268a42559a4dde824772ead080ece0f56478ca"
CAPABILITY_SHA256 = "c4b5859d2b543b26970fb3b5b577b11e5f50415be7484c891257f4d2d0d83808"
MAX_INPUT_BYTES = 131072


class LifecycleReceiptError(ValueError):
    """A value-free finding that identifies the receiving decision."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def verify_schema_binding() -> None:
    """Check the selected source record and exact local contract bytes."""
    try:
        binding = json.loads((ROOT / "contracts/database-lifecycle-profile.source.json").read_text())
    except (TypeError, ValueError):
        raise LifecycleReceiptError("source_binding") from None
    expected = {
        "source_repository": "driftframestudios/lims-eln-program-specification",
        "source_commit": PROGRAM_COMMIT,
        "source_path": "schemas/database-lifecycle-profile.v1.schema.json",
        "schema_sha256": "sha256:" + SCHEMA_SHA256,
        "contract_id": SCHEMA_ID,
        "source_ref": SOURCE_REF,
        "package_version": PROGRAM_VERSION,
        "source_identity": {"algorithm": "path-length-bytes-sha256-v1", "digest": PROGRAM_SOURCE_DIGEST},
        "receiving_profile": "requirements-lifecycle.txt",
    }
    if binding != expected:
        raise LifecycleReceiptError("source_binding")
    for path, digest in (
        ("contracts/database-lifecycle-profile.v1.schema.json", SCHEMA_SHA256),
        ("contracts/workbench-capabilities.v1.schema.json", CAPABILITY_SHA256),
    ):
        if sha256((ROOT / path).read_bytes()).hexdigest() != digest:
            raise LifecycleReceiptError("stale_schema")


def verify_program_source(root: Path) -> None:
    """Reproduce the scoped package digest from the exact selected Git object."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts.validate_received_contracts import (
        ReceivedContractError, program_source_digest_from_git,
    )
    try:
        observed = program_source_digest_from_git(root, PROGRAM_COMMIT)
    except (ReceivedContractError, OSError, ValueError):
        raise LifecycleReceiptError("dependency_source") from None
    if observed != PROGRAM_SOURCE_DIGEST:
        raise LifecycleReceiptError("dependency_source")


def _owned_module(distribution, name: str, relative_path: str):
    """Resolve imports to the selected installed distribution before using them."""
    try:
        expected = Path(distribution.locate_file(relative_path)).resolve(strict=True)
        selected = find_spec(name)
        if selected is None or selected.origin is None or Path(selected.origin).resolve(strict=True) != expected:
            raise LifecycleReceiptError("dependency_provenance")
        module = import_module(name)
        if Path(module.__file__).resolve(strict=True) != expected:
            raise LifecycleReceiptError("dependency_provenance")
    except (OSError, TypeError, AttributeError, ValueError):
        raise LifecycleReceiptError("dependency_provenance") from None
    return module


def _verified_api():
    verify_schema_binding()
    try:
        distribution = metadata.distribution("lims-eln-program-specification")
    except metadata.PackageNotFoundError:
        raise LifecycleReceiptError("dependency_unavailable") from None
    if distribution.version != PROGRAM_VERSION:
        raise LifecycleReceiptError("dependency_version")
    if not distribution.read_text("WHEEL"):
        raise LifecycleReceiptError("dependency_provenance")
    try:
        provenance = json.loads(distribution.read_text("direct_url.json") or "{}")
    except (TypeError, ValueError):
        raise LifecycleReceiptError("dependency_provenance") from None
    if (
        not isinstance(provenance, dict)
        or provenance.get("url") != PROGRAM_URL
        or provenance.get("vcs_info") != {
            "vcs": "git", "requested_revision": PROGRAM_COMMIT, "commit_id": PROGRAM_COMMIT,
        }
        or "dir_info" in provenance
    ):
        raise LifecycleReceiptError("dependency_provenance")
    package = _owned_module(distribution, "lims_eln_contracts", "lims_eln_contracts/__init__.py")
    if package.__version__ != PROGRAM_VERSION:
        raise LifecycleReceiptError("dependency_version")
    # An incomplete or broken installation remains a failing receiving check.
    api = _owned_module(
        distribution, "lims_eln_contracts.database_lifecycle", "lims_eln_contracts/database_lifecycle.py",
    )
    if (
        sha256(api.SCHEMA_BYTES).hexdigest() != SCHEMA_SHA256
        or sha256(api.CAPABILITY_SCHEMA_BYTES).hexdigest() != CAPABILITY_SHA256
    ):
        raise LifecycleReceiptError("stale_schema")
    return api


def receive_profile(payload: bytes, *, capability_payload: bytes | None = None):
    """Admit a bounded record against receiver-selected source and schema trust."""
    api = _verified_api()
    source = api.LifecycleSource(SOURCE_REF, PROGRAM_COMMIT, "sha256:" + SCHEMA_SHA256)
    try:
        return api.admit_lifecycle_profile(
            payload, expected_source=source, capability_payload=capability_payload,
        )
    except api.LifecycleAdmissionError as error:
        raise LifecycleReceiptError(error.code) from None


def _read_input(path: Path) -> bytes:
    """Read one finite regular input; retain its path and contents locally."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise LifecycleReceiptError("input_unavailable")
        return stream.read(MAX_INPUT_BYTES + 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", nargs="?", type=Path)
    parser.add_argument("--capabilities", type=Path)
    parser.add_argument("--verify-installation", action="store_true")
    parser.add_argument("--program-source", type=Path)
    arguments = parser.parse_args(argv)
    if arguments.profile is None and not arguments.verify_installation:
        parser.error("select a profile or --verify-installation")
    if arguments.capabilities is not None and arguments.profile is None:
        parser.error("select the lifecycle profile that names these capability bytes")
    try:
        if arguments.verify_installation:
            _verified_api()
        if arguments.program_source is not None:
            verify_program_source(arguments.program_source)
        if arguments.profile is not None:
            result = receive_profile(
                _read_input(arguments.profile),
                capability_payload=_read_input(arguments.capabilities) if arguments.capabilities else None,
            )
            print(json.dumps({
                "result": "documentary_profile_admitted",
                "resource_state": result.resource_state,
                "unresolved_resources": len(result.unresolved_resource_refs),
                "executed_operations_recorded": result.executed_operations,
                "requested_operations": result.requested_operations,
                "database_actions_performed": 0,
            }, sort_keys=True))
        else:
            print("lifecycle_installation_and_source_verified" if arguments.program_source
                  else "lifecycle_installation_verified")
    except OSError:
        print("input_unavailable")
        return 1
    except LifecycleReceiptError as error:
        print(error.code)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
