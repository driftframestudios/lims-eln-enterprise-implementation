"""Execution, stored-coordinate, and legacy provenance boundaries."""

from __future__ import annotations

from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from lims_eln_implementation.model import canonical_digest
from lims_eln_implementation.workbench.postgres import (
    MigrationProvenanceUnavailable,
    PostgresWorkbenchService,
    _capture_migration_configuration,
    _recorded_migration_configuration,
)
from test_workbench_postgres_adapter import (
    MissingQualityService,
    PostgresWorkbenchAdapterTests,
    ReadCursor,
    RecordingConnection,
    RecordingCursor,
    VALID_RAW,
    context_for,
)


class HeadCursor(RecordingCursor):
    def __init__(self, head=("008",)):
        super().__init__()
        self.head = head

    def fetchone(self):
        if "workbench_migration_head" in self.last_operation:
            return self.head
        return super().fetchone()


class CaptureService(MissingQualityService):
    def _load_run(self, tenant_id, run_id):
        return {"run_id": run_id}


class CoordinateCursor(ReadCursor):
    """Keep the existing invocation oracle and change only its stored result."""

    def __init__(self, version="3.0.0", head="008", *, corrupt_digest=False):
        super().__init__()
        self.version = version
        self.head = head
        self.corrupt_digest = corrupt_digest
        self.result_digest = None

    def fetchone(self):
        row = super().fetchone()
        if "from public.bounded_call_invocation as invocation" in self.last_operation:
            coordinate = deepcopy(row[0])
            coordinate["coordinate_version"] = self.version
            coordinate["specimen_snapshot"]["events"][1]["payload"]["quality_flag"] = "pass"
            if self.version == "3.0.0":
                coordinate["execution_configuration"] = {
                    "migration_head": self.head,
                    "migration_provenance": "recorded_at_execution",
                }
            self.result_digest = canonical_digest(coordinate)
            digest = "f" * 64 if self.corrupt_digest else self.result_digest
            return (coordinate, *row[1:5], digest)
        if "from public.bounded_call_receipt" in self.last_operation:
            return (*row[:-1], self.result_digest)
        return row


class MigrationProvenanceTests(unittest.TestCase):
    def test_reader_requires_one_exact_supported_coordinate(self):
        for row in (None, (), ("008", "extra"), (None,), (8,), (True,),
                    ("007",), ("008\n",), ("８００",), ("1000",), ("8",)):
            with self.subTest(row=row):
                with self.assertRaises(MigrationProvenanceUnavailable):
                    _capture_migration_configuration(HeadCursor(row))
        for head in ("008", "009"):
            with self.subTest(head=head):
                self.assertEqual(_capture_migration_configuration(HeadCursor((head,))), {
                    "migration_head": head, "migration_provenance": "recorded_at_execution",
                })

    def test_recorded_shape_is_closed_and_returned_value_is_owned(self):
        valid = {"migration_head": "008", "migration_provenance": "recorded_at_execution"}
        for value in (None, [], {}, valid | {"extra": 1}, valid | {"migration_provenance": "unrecorded_legacy"}):
            with self.subTest(value=value), self.assertRaises(MigrationProvenanceUnavailable):
                _recorded_migration_configuration(value)
        admitted = _recorded_migration_configuration(valid)
        valid["migration_head"] = "009"
        self.assertEqual(admitted["migration_head"], "008")

    def capture(self, head):
        cursor = HeadCursor(head)
        connection = RecordingConnection(cursor)
        service = CaptureService(lambda: connection, tenant_context_provider=context_for)
        arguments = PostgresWorkbenchAdapterTests().arguments(VALID_RAW)
        service.run_golden_specimen(**arguments)
        writes = [(sql, args) for sql, args in cursor.operations
                  if "output_document =" in sql]
        self.assertEqual(len(writes), 1)
        coordinate = json.loads(writes[0][1][0])
        self.assertEqual(writes[0][1][1], canonical_digest(coordinate))
        self.assertEqual(connection.commits, 1)
        operations = [sql for sql, _ in cursor.operations]
        head_index = operations.index("select laboratory_security.workbench_migration_head()")
        materialization = next(i for i, sql in enumerate(operations) if "insert into public.specimen" in sql)
        self.assertLess(head_index, materialization)
        return coordinate

    def test_new_completions_bind_distinct_execution_heads_in_the_result_digest(self):
        first, later = self.capture(("008",)), self.capture(("009",))
        self.assertEqual(first["coordinate_version"], "3.0.0")
        self.assertEqual(first["execution_configuration"]["migration_head"], "008")
        self.assertEqual(later["execution_configuration"]["migration_head"], "009")
        self.assertNotEqual(canonical_digest(first), canonical_digest(later))

    def test_unavailable_head_rolls_back_before_domain_materialization(self):
        connection = RecordingConnection(HeadCursor(None))
        service = CaptureService(lambda: connection, tenant_context_provider=context_for)
        with self.assertRaises(MigrationProvenanceUnavailable):
            service.run_golden_specimen(**PostgresWorkbenchAdapterTests().arguments(VALID_RAW))
        self.assertEqual((connection.commits, connection.rollbacks), (0, 1))
        self.assertFalse(any("insert into public.specimen" in sql
                             for sql, _ in connection.recording_cursor.operations))

    def observation_configuration(self, cursor):
        connection = RecordingConnection(cursor)
        service = PostgresWorkbenchService(lambda: connection, tenant_context_provider=context_for)
        with patch("lims_eln_implementation.workbench.postgres.build_observation", return_value=None) as build:
            service._load_run("SYN-TENANT-A", "SYN-RUN-001")
        self.assertFalse(any("workbench_migration_head" in sql for sql, _ in cursor.operations))
        return build.call_args.kwargs["configuration_detail"]

    def test_reloaded_results_use_stored_heads_without_querying_current_history(self):
        self.assertEqual(self.observation_configuration(CoordinateCursor()), {
            "migration_head": "008", "migration_provenance": "recorded_at_execution",
        })
        self.assertEqual(self.observation_configuration(CoordinateCursor(head="009")), {
            "migration_head": "009", "migration_provenance": "recorded_at_execution",
        })

    def test_legacy_coordinate_retains_digest_and_explicit_unrecorded_standing(self):
        self.assertEqual(self.observation_configuration(CoordinateCursor(version="2.0.0")), {
            "migration_head": None, "migration_provenance": "unrecorded_legacy",
        })

    def test_damaged_or_unsupported_stored_coordinate_produces_no_observation(self):
        for cursor, error in (
            (CoordinateCursor(corrupt_digest=True), RuntimeError),
            (CoordinateCursor(version="4.0.0"), RuntimeError),
            (CoordinateCursor(head="007"), MigrationProvenanceUnavailable),
        ):
            with self.subTest(cursor=vars(cursor)), self.assertRaises(error):
                self.observation_configuration(cursor)


if __name__ == "__main__":
    unittest.main()
