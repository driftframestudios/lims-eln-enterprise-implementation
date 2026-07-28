from __future__ import annotations

from datetime import datetime, timezone

from lims_eln_implementation.model import Command


NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


def command(
    command_id: str,
    action: str,
    version: int,
    *,
    payload: dict[str, object] | None = None,
    reason: str | None = None,
) -> Command:
    return Command(
        command_id=command_id,
        tenant_id="SYN-TENANT-A",
        specimen_id="SYN-SPECIMEN-0001",
        actor_id="SYN-ACTOR-01",
        action=action,
        expected_version=version,
        occurred_at=NOW,
        payload=payload or {},
        reason_code=reason,
    )

