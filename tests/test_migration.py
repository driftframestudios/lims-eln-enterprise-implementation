from __future__ import annotations

from datetime import timedelta
import json
import unittest

from lims_eln_implementation.migration import (
    MigrationDisposition,
    MigrationEngine,
    MigrationRecord,
)

from helpers import NOW


def record(identity: str, *, revision: int = 1, value: str = "12.5") -> MigrationRecord:
    marker = "a" if identity.endswith("1") else "b"
    return MigrationRecord(
        tenant_id="SYN-TENANT-A",
        canonical_identity=identity,
        revision=revision,
        payload={"value": value, "unit": "ng/uL"},
        artifact_sha256=marker * 64,
    )


class MigrationTests(unittest.TestCase):
    def test_resumable_load_and_exact_replay(self) -> None:
        engine = MigrationEngine()
        item = record("SYN-SPECIMEN-0001")
        self.assertEqual(engine.load(item).disposition, MigrationDisposition.LOADED)
        self.assertEqual(engine.load(item).disposition, MigrationDisposition.REPLAYED)
        self.assertEqual(engine.checkpoint.canonical_identity, item.canonical_identity)
        self.assertEqual(engine.checkpoint.tenant_id, item.tenant_id)
        self.assertEqual(engine.checkpoint.source_revision, item.revision)

    def test_changed_content_collision_closes_cutover(self) -> None:
        engine = MigrationEngine()
        engine.load(record("SYN-SPECIMEN-0001", value="12.5"))
        collision = engine.load(record("SYN-SPECIMEN-0001", value="13.0"))
        self.assertEqual(collision.disposition, MigrationDisposition.COLLISION)
        report = engine.reconcile([record("SYN-SPECIMEN-0001", value="13.0")])
        self.assertFalse(report.ready_for_cutover)
        self.assertEqual(report.divergent_identities, ("SYN-TENANT-A:SYN-SPECIMEN-0001",))

    def test_complete_semantic_reconciliation_opens_cutover_gate(self) -> None:
        source = [record("SYN-SPECIMEN-0001"), record("SYN-SPECIMEN-0002")]
        engine = MigrationEngine()
        for item in source:
            engine.load(item)
        report = engine.reconcile(source)
        self.assertTrue(report.ready_for_cutover)
        self.assertEqual(report.matching_count, 2)

    def test_missing_and_extra_identities_are_explicit(self) -> None:
        engine = MigrationEngine()
        engine.load(record("SYN-SPECIMEN-0001"))
        engine.load(record("SYN-SPECIMEN-0003"))
        report = engine.reconcile(
            [record("SYN-SPECIMEN-0001"), record("SYN-SPECIMEN-0002")]
        )
        self.assertEqual(report.missing_identities, ("SYN-TENANT-A:SYN-SPECIMEN-0002",))
        self.assertEqual(report.extra_identities, ("SYN-TENANT-A:SYN-SPECIMEN-0003",))

    def test_clean_restore_with_independent_witness_proves_parity(self) -> None:
        source = [record("SYN-SPECIMEN-0001"), record("SYN-SPECIMEN-0002")]
        receipt = MigrationEngine.restore_rehearsal(
            rehearsal_id="SYN-RESTORE-001",
            source=source,
            restored=list(source),
            observed_rto_seconds=420.0,
            observed_rpo_seconds=0.0,
            rto_objective_seconds=900.0,
            rpo_objective_seconds=60.0,
            operator_id="SYN-OPERATOR-01",
            witness_id="SYN-WITNESS-01",
            completed_at=NOW,
        )
        self.assertTrue(receipt.parity_holds)
        self.assertEqual(receipt.artifact_match_count, 2)

    def test_restore_requires_byte_parity_and_independent_witness(self) -> None:
        source = [record("SYN-SPECIMEN-0001")]
        changed = [
            MigrationRecord(
                tenant_id="SYN-TENANT-A",
                canonical_identity="SYN-SPECIMEN-0001",
                revision=1,
                payload={"value": "12.5", "unit": "ng/uL"},
                artifact_sha256="c" * 64,
            )
        ]
        receipt = MigrationEngine.restore_rehearsal(
            rehearsal_id="SYN-RESTORE-002",
            source=source,
            restored=changed,
            observed_rto_seconds=420.0,
            observed_rpo_seconds=0.0,
            rto_objective_seconds=900.0,
            rpo_objective_seconds=60.0,
            operator_id="SYN-OPERATOR-01",
            witness_id="SYN-OPERATOR-01",
            completed_at=NOW,
        )
        self.assertFalse(receipt.parity_holds)

    def test_duplicate_source_identity_requires_resolution(self) -> None:
        duplicate = record("SYN-SPECIMEN-0001")
        engine = MigrationEngine()
        engine.load(duplicate)
        with self.assertRaisesRegex(ValueError, "uniqueness"):
            engine.reconcile([duplicate, duplicate])

    def test_restore_requires_artifact_multiplicity_and_timing_objectives(self) -> None:
        source = [
            record("SYN-SPECIMEN-0001"),
            record("SYN-SPECIMEN-0001-COPY"),
        ]
        restored = [
            source[0],
            MigrationRecord(
                tenant_id="SYN-TENANT-A",
                canonical_identity="SYN-SPECIMEN-0001-COPY",
                revision=1,
                payload={"value": "12.5", "unit": "ng/uL"},
                artifact_sha256=None,
            ),
        ]
        receipt = MigrationEngine.restore_rehearsal(
            rehearsal_id="SYN-RESTORE-OBJECTIVES",
            source=source,
            restored=restored,
            observed_rto_seconds=901.0,
            observed_rpo_seconds=0.0,
            rto_objective_seconds=900.0,
            rpo_objective_seconds=60.0,
            operator_id="SYN-OPERATOR-01",
            witness_id="SYN-WITNESS-01",
            completed_at=NOW,
        )

        self.assertFalse(receipt.parity_holds)
        self.assertEqual(receipt.artifact_match_count, 1)

    def test_rollback_returns_engine_to_empty_authority(self) -> None:
        engine = MigrationEngine()
        engine.load(record("SYN-SPECIMEN-0001"))
        engine.rollback()
        self.assertEqual(engine.snapshot(), ())
        self.assertIsNone(engine.checkpoint)

    def test_data_exit_bundle_is_deterministic_and_neutral(self) -> None:
        items = [record("SYN-SPECIMEN-0002"), record("SYN-SPECIMEN-0001")]
        first, first_digest = MigrationEngine.data_exit_bundle(items)
        second, second_digest = MigrationEngine.data_exit_bundle(reversed(items))
        self.assertEqual((first, first_digest), (second, second_digest))
        decoded = json.loads(first)
        self.assertEqual(decoded[0]["canonical_identity"], "SYN-SPECIMEN-0001")

    def test_migration_record_snapshots_nested_payload(self) -> None:
        payload = {"values": [{"result": "12.5"}]}
        item = MigrationRecord(
            tenant_id="SYN-TENANT-A",
            canonical_identity="SYN-SPECIMEN-SNAPSHOT",
            revision=1,
            payload=payload,
            artifact_sha256="d" * 64,
        )
        original_digest = item.semantic_digest
        payload["values"][0]["result"] = "mutated"

        self.assertEqual(item.semantic_digest, original_digest)
        self.assertEqual(
            item.decoded_payload(),
            {"values": [{"result": "12.5"}]},
        )


if __name__ == "__main__":
    unittest.main()
