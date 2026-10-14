"""Known transaction-abort recovery and deterministic duplicate contention."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
import threading
import unittest
from unittest.mock import Mock
from uuid import uuid4

from lims_eln_implementation.idempotency import ContentCollision, TransactionRetryRequired
from lims_eln_implementation.workbench.api import create_app
from lims_eln_implementation.workbench.postgres import _transaction
from lims_eln_implementation.workbench.runtime import create_configured_app
from test_workbench_postgres_adapter import RecordingConnection


class DatabaseFailure(Exception):
    def __init__(self, sqlstate):
        super().__init__("private database diagnostic")
        self.sqlstate = sqlstate


class TransactionContentionTests(unittest.TestCase):
    def test_known_abort_codes_release_resources_and_request_one_whole_retry(self):
        for sqlstate in ("40001", "40P01"):
            for phase in ("execute", "commit"):
                with self.subTest(sqlstate=sqlstate, phase=phase):
                    connection = RecordingConnection()
                    failure = DatabaseFailure(sqlstate)
                    if phase == "commit":
                        connection.commit = Mock(side_effect=failure)
                    with self.assertRaises(TransactionRetryRequired) as observed:
                        with _transaction(lambda: connection):
                            if phase == "execute":
                                raise failure
                    self.assertIs(observed.exception.__cause__, failure)
                    self.assertNotIn("private", str(observed.exception))
                    self.assertEqual(connection.rollbacks, 1)
                    self.assertTrue(connection.closed)
                    self.assertTrue(connection.recording_cursor.closed)
                    if phase == "commit":
                        connection.commit.assert_called_once()
                    else:
                        self.assertEqual(connection.commits, 0)

    def test_other_errors_keep_their_original_reconciliation_boundary(self):
        for code in (None, "08006", "23505", "23P01", "57014", ["40001"]):
            with self.subTest(code=code):
                connection = RecordingConnection()
                failure = DatabaseFailure(code)
                with self.assertRaises(DatabaseFailure) as observed:
                    with _transaction(lambda: connection):
                        raise failure
                self.assertIs(observed.exception, failure)
                self.assertEqual(connection.rollbacks, 1)
                self.assertTrue(connection.closed)

    def test_failed_rollback_retains_primary_cause_and_attempts_release(self):
        connection = RecordingConnection()
        connection.rollback = Mock(side_effect=OSError("private rollback diagnostic"))
        failure = DatabaseFailure("40001")
        with self.assertRaises(TransactionRetryRequired) as observed:
            with _transaction(lambda: connection):
                raise failure
        self.assertIs(observed.exception.__cause__, failure)
        self.assertTrue(failure.__notes__)
        self.assertTrue(connection.closed)
        self.assertTrue(connection.recording_cursor.closed)
        self.assertNotIn("private", str(observed.exception))

    def test_api_returns_a_specific_value_free_retry_problem(self):
        from fastapi.testclient import TestClient
        service = Mock()
        service.state_adapter = "postgresql"
        service.observation.side_effect = TransactionRetryRequired(
            "Retry the complete request with its original identity and inputs."
        )
        with TestClient(create_app(service)) as client:
            response = client.get(
                "/api/workbench/observations/SYN-RUN-001",
                params={"tenant_id": "SYN-TENANT-A"}, headers={"X-Tenant-ID": "SYN-TENANT-A"},
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["type"], "urn:lims-eln:problem:transaction_retry")
        service.observation.assert_called_once_with("SYN-TENANT-A", "SYN-RUN-001")


class SnapshotCursor:
    """Hold the second attempt after its repeatable-read snapshot exists."""
    def __init__(self, inner, snapshot, committed):
        self.inner, self.snapshot, self.committed = inner, snapshot, committed

    def execute(self, operation, parameters=()):
        if "insert into public.bounded_call_invocation" in operation:
            self.inner.execute("select count(*) from public.bounded_call_invocation")
            self.inner.fetchone()
            self.snapshot.set()
            if not self.committed.wait(10):
                raise TimeoutError("first commit fixture deadline")
        return self.inner.execute(operation, parameters)

    def __getattr__(self, name):
        return getattr(self.inner, name)


class SnapshotConnection:
    def __init__(self, inner, snapshot, committed):
        self.inner, self.snapshot, self.committed = inner, snapshot, committed

    def cursor(self):
        return SnapshotCursor(self.inner.cursor(), self.snapshot, self.committed)

    def __getattr__(self, name):
        return getattr(self.inner, name)


@unittest.skipUnless(
    os.environ.get("LIMS_WORKBENCH_CONTENTION_CHECK") == "1",
    "configured contention requires the prepared local workbench environment",
)
class ConfiguredOverlapTests(unittest.TestCase):
    def test_snapshot_conflict_preserves_one_result_and_exact_replay(self):
        first = create_configured_app().state.workbench
        second = create_configured_app().state.workbench
        self.assertEqual(first.state_adapter, "postgresql")
        self.assertEqual(second.state_adapter, "postgresql")
        held, release, snapshot, committed = (threading.Event() for _ in range(4))
        def hold(stage):
            if stage == "before_commit":
                held.set()
                if not release.wait(10):
                    raise TimeoutError("first release fixture deadline")
        first._failure_probe = hold
        connect = second._connection_factory
        second._connection_factory = lambda: SnapshotConnection(connect(), snapshot, committed)
        suffix = uuid4().hex[:12]
        arguments = dict(
            run_id="SYN-OVERLAP-" + suffix, tenant_id="SYN-TENANT-A",
            specimen_id="SYN-OVERLAP-SPM-" + suffix,
            actor_id="SYN-ACTOR-01", scientist_id="SYN-SCIENTIST-01",
            quality_actor_id="SYN-QUALITY-01", occurred_at=datetime.now(timezone.utc),
            raw_instrument_json=b'{"analyte":"synthetic-dna","value":"12.5","unit":"ng/uL"}',
            vendor_payload={"status": "released"},
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            initial = executor.submit(first.run_golden_specimen, **arguments)
            try:
                self.assertTrue(held.wait(10))
                competing = executor.submit(second.run_golden_specimen, **arguments)
                self.assertTrue(snapshot.wait(10))
                release.set()
                accepted = initial.result(timeout=15)
                committed.set()
                with self.assertRaises(TransactionRetryRequired):
                    competing.result(timeout=15)
            finally:
                release.set()
                committed.set()
        first._failure_probe = lambda stage: None
        second._connection_factory = connect
        replay = second.run_golden_specimen(**arguments)
        self.assertEqual(accepted, replay)
        self.assertEqual(accepted["specimen"]["state"], "released")
        self.assertEqual(accepted["specimen"]["version"], 5)
        self.assertEqual(len(accepted["specimen"]["events"]), 5)
        with self.assertRaises(ContentCollision):
            second.run_golden_specimen(**{**arguments, "vendor_payload": {"status": "changed"}})
        self.assertEqual(second.run_golden_specimen(**arguments), accepted)


if __name__ == "__main__":
    unittest.main()
