"""Bounded local observation export with exclusive atomic publication."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import signal
import stat
import sys

from .shared_contracts import SharedContractUnavailable, validate_observation_bytes

MAX_OBSERVATION_BYTES = 2 * 1024 * 1024


class ExportError(ValueError):
    """Export stopped with the accepted destination retained."""


class ExportHeld(ExportError):
    """A completed writer or operator reconciliation can release this hold."""


def _existing_matches(directory: int, name: str, payload: bytes) -> bool:
    """Read one bounded regular artifact through the already-owned directory."""
    try:
        descriptor = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
    except FileNotFoundError:
        return False
    with os.fdopen(descriptor, "rb") as source:
        info = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.getuid()
            or info.st_size > MAX_OBSERVATION_BYTES
        ):
            raise ExportError("existing artifact requires owner-only regular-file storage")
        if info.st_nlink != 1:
            raise ExportHeld("artifact link cleanup is pending; retry after the prior writer completes")
        existing = source.read(MAX_OBSERVATION_BYTES + 1)
    if existing != payload:
        raise ExportError("destination already holds a different accepted artifact")
    return True


def _publish(payload: bytes, destination: Path) -> str:
    """O(n) byte work/space; one directory fd owns all publication paths."""
    if destination.name in {"", ".", ".."}:
        raise ExportError("select a named artifact in the protected output directory")
    directory = os.open(
        destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    )
    temporary = ".pending-export-" + secrets.token_hex(12)
    created = False
    try:
        info = os.fstat(directory)
        if stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.getuid():
            raise ExportError("output directory requires owner-only mode 0700")
        if _existing_matches(directory, destination.name, payload):
            os.fsync(directory)
            return "reused"
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600, dir_fd=directory,
        )
        created = True
        with os.fdopen(descriptor, "wb") as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        try:
            os.link(
                temporary, destination.name, src_dir_fd=directory,
                dst_dir_fd=directory, follow_symlinks=False,
            )
        except FileExistsError:
            # Another cooperative exporter may have published the same bytes.
            if _existing_matches(directory, destination.name, payload):
                return "reused"
            raise ExportError("destination changed during publication") from None
        return "published"
    finally:
        try:
            if created:
                os.unlink(temporary, dir_fd=directory)
                os.fsync(directory)
        finally:
            os.close(directory)


def export_observation(
    payload: bytes, destination: Path, *, tenant_id: str, run_id: str
) -> dict[str, str]:
    """Admit the typed envelope, then preserve its exact received bytes.

    Byte admission, digest, and file work are linear in the capped payload.
    The shared contract owns JSON parsing and model-validation costs.
    """
    if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_OBSERVATION_BYTES:
        raise ExportError("observation requires between 1 byte and 2 MiB")
    try:
        validate_observation_bytes(payload, tenant_id=tenant_id, run_id=run_id)
    except (ValueError, UnicodeError, RecursionError, SharedContractUnavailable):
        raise ExportError("observation requires the installed contract and matching identities") from None
    try:
        status = _publish(payload, destination)
    except OSError:
        raise ExportError(
            "publication stopped; retain accepted artifacts and inspect protected storage"
        ) from None
    return {"status": status, "sha256": sha256(payload).hexdigest()}


def _terminate(signum: int, frame: object) -> None:
    raise KeyboardInterrupt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    previous = signal.signal(signal.SIGTERM, _terminate)
    try:
        payload = sys.stdin.buffer.read(MAX_OBSERVATION_BYTES + 1)
        result = export_observation(
            payload, arguments.output, tenant_id=arguments.tenant, run_id=arguments.run
        )
    except KeyboardInterrupt:
        print("Export interrupted; retain accepted artifacts and reconcile pending files.", file=sys.stderr)
        return 130
    except ExportHeld:
        print("Export held; complete prior-writer cleanup, then retry the same artifact.", file=sys.stderr)
        return 75
    except (ExportError, OSError):
        print("Export stopped; retain accepted artifacts and use the export recovery guide.", file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
