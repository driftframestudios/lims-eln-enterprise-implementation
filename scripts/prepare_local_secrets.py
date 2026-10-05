#!/usr/bin/env python3
"""Prepare retained local credentials outside repository and image contexts."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import secrets
import stat

ROOT = Path(__file__).resolve().parents[1]
NAMES = (
    "postgres_password", "postgres_app_password", "postgres_outbox_password",
    "postgres_recovery_password", "postgres_evidence_password",
    "postgres_migrator_password", "postgres_tenant_hmac_key", "minio_password",
)


class PreparationError(ValueError):
    """Preparation stopped with existing credential material retained."""


def _validate(directory: int, name: str) -> None:
    descriptor = os.open(
        name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
    )
    with os.fdopen(descriptor, "rb") as source:
        info = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.getuid() or info.st_nlink != 1
        ):
            raise PreparationError("secret files require owner-only regular-file storage")
        content = source.read(66)
    if len(content) != 65 or content[-1:] != b"\n" or any(
        byte not in b"0123456789abcdef" for byte in content[:64]
    ):
        raise PreparationError("prepared credentials require 64 lowercase hex digits and LF")


def prepare(path: Path, *, repository: Path = ROOT) -> dict[str, object]:
    """O(k) bounded files; serialize cooperative writers and publish each file atomically."""
    path = path.absolute()
    if path.is_symlink() or path.resolve().is_relative_to(repository.resolve()):
        raise PreparationError("select an external operator-owned state directory")
    path.mkdir(mode=0o700, parents=False, exist_ok=True)
    directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(directory)
        if stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.getuid():
            raise PreparationError("state directory requires owner-only mode 0700")
        lock = os.open(
            ".prepare.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600, dir_fd=directory,
        )
        with os.fdopen(lock, "rb+") as guard:
            lock_info = os.fstat(guard.fileno())
            if not stat.S_ISREG(lock_info.st_mode) or stat.S_IMODE(lock_info.st_mode) != 0o600:
                raise PreparationError("preparation lock requires an owner-only regular file")
            fcntl.flock(guard, fcntl.LOCK_EX)
            missing = []
            for stem in NAMES:
                name = stem + ".txt"
                try:
                    _validate(directory, name)
                except FileNotFoundError:
                    missing.append(name)
            created = 0
            for name in missing:
                temporary = ".pending-" + secrets.token_hex(12)
                descriptor = os.open(
                    temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                    0o600, dir_fd=directory,
                )
                try:
                    with os.fdopen(descriptor, "wb") as target:
                        target.write((secrets.token_hex(32) + "\n").encode("ascii"))
                        target.flush()
                        os.fsync(target.fileno())
                    os.link(
                        temporary, name, src_dir_fd=directory, dst_dir_fd=directory,
                        follow_symlinks=False,
                    )
                    created += 1
                finally:
                    os.unlink(temporary, dir_fd=directory)
                    os.fsync(directory)
            return {"status": "prepared", "created": created, "retained": len(NAMES) - created}
    except (OSError, ValueError) as error:
        if isinstance(error, PreparationError):
            raise
        raise PreparationError("preparation stopped; preserve state and inspect local permissions") from None
    finally:
        os.close(directory)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        result = prepare(args.directory)
    except (OSError, PreparationError):
        print("Preparation stopped; retain existing files and use the container recovery guide.")
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
