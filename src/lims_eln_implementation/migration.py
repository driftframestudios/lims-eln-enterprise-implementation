"""Resumable migration, semantic parity, rollback, restore, and data-exit evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Iterable, Mapping

from .model import canonical_digest, require_aware_utc


@dataclass(frozen=True, slots=True)
class MigrationRecord:
    tenant_id: str
    canonical_identity: str
    revision: int
    payload: Mapping[str, object]
    artifact_sha256: str | None = None

    @property
    def semantic_digest(self) -> str:
        return canonical_digest(
            {
                "tenant_id": self.tenant_id,
                "canonical_identity": self.canonical_identity,
                "revision": self.revision,
                "payload": dict(self.payload),
                "artifact_sha256": self.artifact_sha256,
            }
        )


class MigrationDisposition(StrEnum):
    LOADED = "loaded"
    REPLAYED = "replayed"
    COLLISION = "collision"


@dataclass(frozen=True, slots=True)
class MigrationResult:
    disposition: MigrationDisposition
    identity: str
    semantic_digest: str
    recovery: str


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    source_count: int
    target_count: int
    matching_count: int
    missing_identities: tuple[str, ...]
    divergent_identities: tuple[str, ...]
    extra_identities: tuple[str, ...]

    @property
    def ready_for_cutover(self) -> bool:
        return (
            self.source_count == self.target_count == self.matching_count
            and not self.missing_identities
            and not self.divergent_identities
            and not self.extra_identities
        )


@dataclass(frozen=True, slots=True)
class RestoreReceipt:
    rehearsal_id: str
    source_digest: str
    restored_digest: str
    source_count: int
    restored_count: int
    artifact_match_count: int
    observed_rto_seconds: float
    observed_rpo_seconds: float
    operator_id: str
    witness_id: str
    completed_at: datetime

    @property
    def parity_holds(self) -> bool:
        return (
            self.source_digest == self.restored_digest
            and self.source_count == self.restored_count == self.artifact_match_count
            and self.operator_id != self.witness_id
        )


class MigrationEngine:
    def __init__(self) -> None:
        self.target: dict[tuple[str, str], MigrationRecord] = {}
        self.exceptions: list[MigrationResult] = []
        self.checkpoint: str | None = None

    def load(self, record: MigrationRecord) -> MigrationResult:
        identity = (record.tenant_id, record.canonical_identity)
        current = self.target.get(identity)
        if current is None:
            self.target[identity] = record
            result = MigrationResult(
                MigrationDisposition.LOADED,
                record.canonical_identity,
                record.semantic_digest,
                "continue from the recorded checkpoint",
            )
        elif current.semantic_digest == record.semantic_digest:
            result = MigrationResult(
                MigrationDisposition.REPLAYED,
                record.canonical_identity,
                record.semantic_digest,
                "reuse the verified target record",
            )
        else:
            result = MigrationResult(
                MigrationDisposition.COLLISION,
                record.canonical_identity,
                record.semantic_digest,
                "resolve identity and revision semantics before cutover",
            )
            self.exceptions.append(result)
        self.checkpoint = record.canonical_identity
        return result

    def reconcile(self, source: Iterable[MigrationRecord]) -> ReconciliationReport:
        source_map = {
            (record.tenant_id, record.canonical_identity): record for record in source
        }
        target_keys = set(self.target)
        source_keys = set(source_map)
        missing = source_keys.difference(target_keys)
        extra = target_keys.difference(source_keys)
        shared = source_keys.intersection(target_keys)
        divergent = {
            key
            for key in shared
            if source_map[key].semantic_digest != self.target[key].semantic_digest
        }
        matching = shared.difference(divergent)
        label = lambda key: f"{key[0]}:{key[1]}"
        return ReconciliationReport(
            source_count=len(source_map),
            target_count=len(self.target),
            matching_count=len(matching),
            missing_identities=tuple(sorted(map(label, missing))),
            divergent_identities=tuple(sorted(map(label, divergent))),
            extra_identities=tuple(sorted(map(label, extra))),
        )

    def snapshot(self) -> tuple[MigrationRecord, ...]:
        return tuple(self.target[key] for key in sorted(self.target))

    def rollback(self) -> None:
        self.target.clear()
        self.exceptions.clear()
        self.checkpoint = None

    @staticmethod
    def restore_rehearsal(
        *,
        rehearsal_id: str,
        source: Iterable[MigrationRecord],
        restored: Iterable[MigrationRecord],
        observed_rto_seconds: float,
        observed_rpo_seconds: float,
        operator_id: str,
        witness_id: str,
        completed_at: datetime,
    ) -> RestoreReceipt:
        source_items = tuple(source)
        restored_items = tuple(restored)
        source_digest = canonical_digest(
            [item.semantic_digest for item in sorted(source_items, key=_record_key)]
        )
        restored_digest = canonical_digest(
            [item.semantic_digest for item in sorted(restored_items, key=_record_key)]
        )
        source_artifacts = {item.artifact_sha256 for item in source_items}
        restored_artifacts = {item.artifact_sha256 for item in restored_items}
        artifact_matches = len(source_artifacts.intersection(restored_artifacts))
        require_aware_utc(completed_at)
        return RestoreReceipt(
            rehearsal_id=rehearsal_id,
            source_digest=source_digest,
            restored_digest=restored_digest,
            source_count=len(source_items),
            restored_count=len(restored_items),
            artifact_match_count=artifact_matches,
            observed_rto_seconds=observed_rto_seconds,
            observed_rpo_seconds=observed_rpo_seconds,
            operator_id=operator_id,
            witness_id=witness_id,
            completed_at=completed_at,
        )

    @staticmethod
    def data_exit_bundle(records: Iterable[MigrationRecord]) -> tuple[bytes, str]:
        rows = [
            {
                "tenant_id": item.tenant_id,
                "canonical_identity": item.canonical_identity,
                "revision": item.revision,
                "payload": dict(item.payload),
                "artifact_sha256": item.artifact_sha256,
                "semantic_digest": item.semantic_digest,
            }
            for item in sorted(records, key=_record_key)
        ]
        import json

        content = json.dumps(rows, sort_keys=True, indent=2).encode("utf-8")
        return content, sha256(content).hexdigest()


def _record_key(record: MigrationRecord) -> tuple[str, str]:
    return record.tenant_id, record.canonical_identity

