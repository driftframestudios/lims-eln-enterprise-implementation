#!/usr/bin/env python3
"""Build and import-check a dependency-free source package archive."""

from __future__ import annotations

import argparse
from base64 import urlsafe_b64encode
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tomllib
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def build(target: Path) -> dict[str, object]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    if target.suffix != ".whl":
        raise ValueError("package archive target requires a .whl suffix")
    target.parent.mkdir(parents=True, exist_ok=True)
    members: dict[str, bytes] = {}
    distribution = project["name"].replace("-", "_")
    dist_info = f"{distribution}-{project['version']}.dist-info"
    for path in sorted(SRC.rglob("*.py")):
        members[path.relative_to(SRC).as_posix()] = path.read_bytes()
    members[f"{dist_info}/METADATA"] = "\n".join(
        (
            "Metadata-Version: 2.3",
            f"Name: {project['name']}",
            f"Version: {project['version']}",
            f"Requires-Python: {project['requires-python']}",
            "",
        )
    ).encode("utf-8")
    members[f"{dist_info}/WHEEL"] = "\n".join(
        (
            "Wheel-Version: 1.0",
            "Generator: lims-eln dependency-free package proof",
            "Root-Is-Purelib: true",
            "Tag: py3-none-any",
            "",
        )
    ).encode("utf-8")
    record_path = f"{dist_info}/RECORD"
    record_rows = []
    for name, content in sorted(members.items()):
        digest = urlsafe_b64encode(sha256(content).digest()).decode("ascii").rstrip("=")
        record_rows.append(f"{name},sha256={digest},{len(content)}")
    record_rows.append(f"{record_path},,")
    members[record_path] = ("\n".join(record_rows) + "\n").encode("utf-8")

    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in sorted(members.items()):
            archive.writestr(name, content)

    probe = (
        "import sys;"
        f"sys.path.insert(0, {str(target)!r});"
        "import lims_eln_implementation as package;"
        f"assert package.__version__ == {project['version']!r}"
    )
    subprocess.run(
        [sys.executable, "-I", "-c", probe],
        check=True,
        timeout=20,
    )
    return {
        "status": "passed",
        "archive": str(target),
        "version": project["version"],
        "members": len(members),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(build(arguments.target), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
