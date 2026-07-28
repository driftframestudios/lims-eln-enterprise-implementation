"""Resumable migration, semantic parity, rollback, restore, and data-exit evidence."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
import json
import re
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .model import canonical_digest, canonical_json, require_aware_utc


def _immutable_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _immutable_json(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_immutable_json(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class MigrationRecord:
    tenant_id: str
    canonical_identity: str
    revision: int
    payload: Mapping[str, object]
    artifact_sha256: str | None = None
    _payload_json: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("tenant_id", self.tenant_id),
            ("canonical_identity", self.canonical_identity),
        ):
            if not value.strip():
                raise ValueError(f"migration {name} requires a populated value")
        if self.revision < 1:
            raise ValueError("migration revision requires a positive integer")
        payload_json = canonical_json(dict(self.payload))
        payload = json.loads(payload_json)
        if not isinstance(payload, dict):
            raise ValueError("migration payload requires an object")
        object.__setattr__(self, "payload", _immutable_json(payload))
        object.__setattr__(self, "_payload_json", payload_json)
        if (
            self.artifact_sha256 is not None
            and re.fullmatch(r"[a-f0-9]{64}", self.artifact_sha256) is None
        ):
            raise ValueError("migration artifact requires a lowercase SHA-256 digest")

    def decoded_payload(self) -> dict[str, object]:
        payload = json.loads(self._payload_json)
        assert isinstance(payload, dict)
        return payload

    @property
    def semantic_digest(self) -> str:
        return canonical_digest(
            {
                "tenant_id": self.tenant_id,
                "canonical_identity": self.canonical_identity,
                "revision": self.revision,
                "payload": self.decoded_payload(),
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
class MigrationCheckpoint:
    rehearsal_id: str
    tenant_id: str
    canonical_identity: str
    source_revision: int
    semantic_digest: str


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
    rto_objective_seconds: float
    rpo_objective_seconds: float
    operator_id: str
    witness_id: str
    completed_at: datetime

    def __post_init__(self) -> None:
        require_aware_utc(self.completed_at)
        if not self.rehearsal_id.strip():
            raise ValueError("restore receipt requires a rehearsal identity")
        if not self.operator_id.strip() or not self.witness_id.strip():
            raise ValueError("restore receipt requires operator and witness identities")
        timings = (
            self.observed_rto_seconds,
            self.observed_rpo_seconds,
            self.rto_objective_seconds,
            self.rpo_objective_seconds,
        )
        if any(value < 0 for value in timings):
            raise ValueError("restore timing values require nonnegative seconds")

    @property
    def parity_holds(self) -> bool:
        return (
            self.source_digest == self.restored_digest
            and self.source_count == self.restored_count == self.artifact_match_count
            and self.operator_id != self.witness_id
            and self.observed_rto_seconds <= self.rto_objective_seconds
            and self.observed_rpo_seconds <= self.rpo_objective_seconds
        )


class MigrationEngine:
    def __init__(self, *, rehearsal_id: str = "reference-migration") -> None:
        if not rehearsal_id.strip():
            raise ValueError("migration engine requires a rehearsal identity")
        self.rehearsal_id = rehearsal_id
        self.target: dict[tuple[str, str], MigrationRecord] = {}
        self.exceptions: list[MigrationResult] = []
        self.checkpoint: MigrationCheckpoint | None = None

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
        self.checkpoint = MigrationCheckpoint(
            rehearsal_id=self.rehearsal_id,
            tenant_id=record.tenant_id,
            canonical_identity=record.canonical_identity,
            source_revision=record.revision,
            semantic_digest=record.semantic_digest,
        )
        return result

    def reconcile(self, source: Iterable[MigrationRecord]) -> ReconciliationReport:
        source_map: dict[tuple[str, str], MigrationRecord] = {}
        for record in source:
            identity = (record.tenant_id, record.canonical_identity)
            if identity in source_map:
                raise ValueError(
                    "migration source identities require uniqueness before reconciliation"
                )
            source_map[identity] = record
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
        rto_objective_seconds: float,
        rpo_objective_seconds: float,
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
        source_artifacts = Counter(
            item.artifact_sha256
            for item in source_items
            if item.artifact_sha256 is not None
        )
        restored_artifacts = Counter(
            item.artifact_sha256
            for item in restored_items
            if item.artifact_sha256 is not None
        )
        artifact_matches = sum((source_artifacts & restored_artifacts).values())
        return RestoreReceipt(
            rehearsal_id=rehearsal_id,
            source_digest=source_digest,
            restored_digest=restored_digest,
            source_count=len(source_items),
            restored_count=len(restored_items),
            artifact_match_count=artifact_matches,
            observed_rto_seconds=observed_rto_seconds,
            observed_rpo_seconds=observed_rpo_seconds,
            rto_objective_seconds=rto_objective_seconds,
            rpo_objective_seconds=rpo_objective_seconds,
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
                "payload": item.decoded_payload(),
                "artifact_sha256": item.artifact_sha256,
                "semantic_digest": item.semantic_digest,
            }
            for item in sorted(records, key=_record_key)
        ]
        content = json.dumps(rows, sort_keys=True, indent=2).encode("utf-8")
        return content, sha256(content).hexdigest()


def _record_key(record: MigrationRecord) -> tuple[str, str]:
    return record.tenant_id, record.canonical_identity
