#!/usr/bin/env python3
"""Run dependency-free package, type-surface, schema, and hygiene checks."""

from __future__ import annotations

from datetime import datetime
import importlib
import inspect
import json
from pathlib import Path
import pkgutil
import py_compile
import sys
import tempfile
import tomllib
from typing import get_type_hints


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True


def validate_package() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package = importlib.import_module("lims_eln_implementation")
    if project["project"]["version"] != package.__version__:
        raise AssertionError("package metadata and runtime version require one value")
    with tempfile.TemporaryDirectory(prefix="lims-eln-bytecode-") as target:
        for index, path in enumerate(sorted(SRC.rglob("*.py"))):
            py_compile.compile(
                str(path),
                cfile=str(Path(target) / f"{index}.pyc"),
                doraise=True,
            )

    package_path = Path(package.__file__).parent
    for module_info in pkgutil.iter_modules([str(package_path)]):
        module = importlib.import_module(
            f"lims_eln_implementation.{module_info.name}"
        )
        for name, value in vars(module).items():
            if (
                name.startswith("_")
                or getattr(value, "__module__", None) != module.__name__
            ):
                continue
            if inspect.isfunction(value) or inspect.isclass(value):
                get_type_hints(value)


def validate_bound_documents() -> None:
    from lims_eln_implementation.model import Command
    from lims_eln_implementation.receipts import (
        AssuranceStage,
        EvidenceMode,
        EvidenceReceipt,
    )
    from lims_eln_implementation.runtime_configuration import RuntimeSettingCatalog

    command_value = json.loads(
        (ROOT / "fixtures/synthetic/specimen-command.v1.json").read_text(
            encoding="utf-8"
        )
    )
    Command(
        command_id=command_value["command_id"],
        tenant_id=command_value["tenant_id"],
        specimen_id=command_value["specimen_id"],
        actor_id=command_value["actor_id"],
        action=command_value["action"],
        expected_version=command_value["expected_version"],
        occurred_at=datetime.fromisoformat(command_value["occurred_at"]),
        payload=command_value["payload"],
        reason_code=command_value.get("reason_code"),
    )

    catalog_value = json.loads(
        (ROOT / "fixtures/synthetic/runtime-setting-catalog.v1.json").read_text(
            encoding="utf-8"
        )
    )
    RuntimeSettingCatalog.from_mapping(catalog_value)

    receipt_value = json.loads(
        (ROOT / "receipts/local-verification.example.json").read_text(
            encoding="utf-8"
        )
    )
    if receipt_value["schema_version"] != "1.1.0":
        raise AssertionError("local receipt requires execution receipt schema 1.1.0")
    EvidenceReceipt(
        receipt_id=receipt_value["receipt_id"],
        claim_id=receipt_value["claim_id"],
        intended_use_id=receipt_value["intended_use_id"],
        release_claim_id=receipt_value["release_claim_id"],
        evidence_mode=EvidenceMode(receipt_value["evidence_mode"]),
        assurance_stage=AssuranceStage(receipt_value["assurance_stage"]),
        environment=receipt_value["environment"],
        version_bindings=receipt_value["version_bindings"],
        scenario_ids=tuple(receipt_value["scenario_ids"]),
        artifact_digests=tuple(receipt_value["artifact_digests"]),
        observed_at=datetime.fromisoformat(receipt_value["observed_at"]),
        performer_id=receipt_value["performer_id"],
        reviewer_id=receipt_value["reviewer_id"],
        limitations=tuple(receipt_value["limitations"]),
    )


def validate_text_hygiene() -> None:
    findings: list[str] = []
    paths = (
        *SRC.rglob("*.py"),
        *(ROOT / "tests").rglob("*.py"),
        *(ROOT / "scripts").rglob("*.py"),
    )
    for path in sorted(paths):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if line.rstrip() != line:
                findings.append(
                    f"{path.relative_to(ROOT)}:{line_number}: trailing space"
                )
            if "\t" in line:
                findings.append(
                    f"{path.relative_to(ROOT)}:{line_number}: tab indentation"
                )
    if findings:
        raise AssertionError("\n".join(findings))


def main() -> int:
    validate_package()
    validate_bound_documents()
    validate_text_hygiene()
    from scripts.validate_repository import validate_credential_hygiene

    validate_credential_hygiene()
    print(
        json.dumps(
            {
                "status": "passed",
                "checks": [
                    "package-import-and-bytecode",
                    "runtime-type-hints",
                    "bound-schema-documents",
                    "text-hygiene",
                    "credential-patterns",
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
