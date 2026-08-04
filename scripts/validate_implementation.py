"""Run small package and fixture checks before standard tool validation."""

from __future__ import annotations

import importlib
import json
import pkgutil
import sys
import tomllib
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


def main() -> int:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package = importlib.import_module("lims_eln_implementation")
    if project["project"]["version"] != package.__version__:
        raise AssertionError("package metadata and runtime version require one value")

    package_path = Path(package.__file__).parent
    for module_info in pkgutil.iter_modules([str(package_path)]):
        importlib.import_module(f"lims_eln_implementation.{module_info.name}")

    for path in sorted(ROOT.rglob("*.json")):
        if any(part.startswith(".") for part in path.relative_to(ROOT).parts):
            continue
        json.loads(path.read_text(encoding="utf-8"))

    from lims_eln_implementation.model import Command
    from lims_eln_implementation.runtime_configuration import RuntimeSettingCatalog

    command_value = json.loads(
        (ROOT / "fixtures/synthetic/specimen-command.v1.json").read_text(encoding="utf-8")
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
    catalog = json.loads(
        (ROOT / "fixtures/synthetic/runtime-setting-catalog.v1.json").read_text(encoding="utf-8")
    )
    RuntimeSettingCatalog.from_mapping(catalog)
    print("implementation validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
