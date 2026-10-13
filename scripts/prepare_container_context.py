#!/usr/bin/env python3
"""Stage exact-source wheels and allowlisted Docker contexts outside the repository."""
from __future__ import annotations

import argparse
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]


class ContextError(ValueError):
    """Context admission requires exact source and allowlisted artifacts."""


def command(arguments: list[str], *, cwd: Path, log) -> bytes:
    completed = subprocess.run(
        arguments, cwd=cwd, stdout=subprocess.PIPE, stderr=log, timeout=300,
        check=False,
    )
    if completed.returncode:
        raise ContextError("context preparation stopped; protected build diagnostics retain detail")
    return completed.stdout


def archive(repository: Path, revision: str, destination: Path, log) -> None:
    content = command(["git", "archive", "--format=tar", revision], cwd=repository, log=log)
    destination.mkdir(mode=0o700)
    with tarfile.open(fileobj=io.BytesIO(content)) as source:
        source.extractall(destination, filter="data")


def requirements_admitted(content: str) -> bool:
    """Admit hashed registry requirements; credentials and dependency locators stay host-side."""
    rows = [row.strip().removesuffix("\\").rstrip() for row in content.splitlines() if row.strip()]
    return bool(rows) and all(
        re.fullmatch(r"--hash=sha256:[0-9a-f]{64}", row)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*==[A-Za-z0-9_.+!-]+(?:\s*;[\w\s.'\"<>=!*()-]+)?", row)
        for row in rows
    )


def member_digests(root: Path) -> dict[str, str]:
    """Linear in admitted bytes; member count is bounded by the two built packages."""
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ContextError("context members require owned regular files")
        if path.is_file() and path.name != "build-inputs.json":
            result[path.relative_to(root).as_posix()] = sha256(path.read_bytes()).hexdigest()
    return result


def stage_wheels(source: Path, target: Path, expected: set[str]) -> None:
    """Project declared wheels; builder housekeeping remains in the build workspace."""
    candidates = {path.name: path for path in source.glob("*.whl")}
    if set(candidates) != expected or any(
        path.is_symlink() or not path.is_file() for path in candidates.values()
    ):
        raise ContextError("context requires the two declared regular package wheels")
    target.mkdir(parents=True)
    for name in sorted(expected):
        shutil.copyfile(candidates[name], target / name)


def prepare(target: Path, program: Path, *, root: Path = ROOT) -> dict[str, object]:
    target = target.absolute()
    if target.exists() or target.is_symlink() or target.resolve().is_relative_to(root.resolve()):
        raise ContextError("choose a new external context directory; retain prior contexts for reuse")
    with tempfile.TemporaryDirectory(prefix=".lims-context-", dir=target.parent) as temporary:
        scratch = Path(temporary)
        with tempfile.NamedTemporaryFile(
            prefix=".lims-build-", suffix=".log", dir=target.parent, delete=False
        ) as log:
            head = command(["git", "rev-parse", "HEAD"], cwd=root, log=log).decode().strip()
            enterprise = scratch / "enterprise"
            archive(root, head, enterprise, log)
            metadata = tomllib.loads((enterprise / "pyproject.toml").read_text())
            dependency = metadata["project"]["optional-dependencies"]["contracts"][0]
            match = re.fullmatch(
                r"lims-eln-program-specification @ git\+https://github.com/"
                r"driftframestudios/lims-eln-program-specification.git@([0-9a-f]{40})",
                dependency,
            )
            if match is None:
                raise ContextError("Program coordinate requires the reviewed exact-commit contract")
            program_head = match[1]
            program_source = scratch / "program"
            archive(program, program_head, program_source, log)
            context = scratch / "context"
            application = context / "application"
            built_wheels = scratch / "built-wheels"
            built_wheels.mkdir()
            for source in (enterprise, program_source):
                command(
                    ["uv", "build", "--wheel", "--python", "3.12", "--out-dir", str(built_wheels), str(source)],
                    cwd=scratch, log=log,
                )
            requirements = command([
                "uv", "export", "--locked", "--extra", "contracts", "--extra", "postgres",
                "--no-dev", "--no-default-groups", "--no-emit-project",
                "--no-emit-package", "lims-eln-program-specification", "--no-header", "--no-annotate",
            ], cwd=enterprise, log=log).decode("utf-8")
            if not requirements_admitted(requirements):
                raise ContextError("image dependencies require hash-locked registry requirements")
            expected_wheels = {
                "lims_eln_enterprise_implementation-0.3.2-py3-none-any.whl",
                "lims_eln_program_specification-0.5.0-py3-none-any.whl",
            }
            stage_wheels(built_wheels, application / "wheels", expected_wheels)
            (application / "requirements.txt").write_text(requirements)
            shutil.copyfile(enterprise / "infra/application.Dockerfile", application / "Dockerfile")
            migrator = context / "migrator"
            (migrator / "infra").mkdir(parents=True)
            for relative in (
                "flyway.conf", "infra/migrator.Dockerfile",
                "infra/run-flyway-with-secret.sh", "infra/secret-files.sh",
            ):
                shutil.copy2(enterprise / relative, migrator / relative)
            shutil.copytree(enterprise / "sql", migrator / "sql")
            receipt = {
                "format": "local-container-inputs.v1",
                "enterprise_commit": head, "program_commit": program_head,
                "lock_sha256": sha256((enterprise / "uv.lock").read_bytes()).hexdigest(),
                "members": member_digests(context),
            }
            payload = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
            (application / "build-inputs.json").write_text(payload)
            (context / "build-inputs.json").write_text(payload)
            os.rename(context, target)
            Path(log.name).unlink()
            return {key: value for key, value in receipt.items() if key != "members"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path)
    parser.add_argument("--program-source", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = prepare(args.target, args.program_source)
    except (ContextError, OSError, subprocess.TimeoutExpired):
        print("Context preparation stopped; prior contexts remain available. Check prerequisites and exact sources.")
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
