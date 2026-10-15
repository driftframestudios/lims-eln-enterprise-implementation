"""Composed DB-API faults preserve transaction outcomes and release ownership."""

import unittest

from lims_eln_implementation import production_adapters as adapters
from lims_eln_implementation.idempotency import TransactionRetryRequired
from lims_eln_implementation.workbench.postgres import _transaction as workbench_transaction
from tests.test_bounded_caller import sample_receipt, tenant_context


class Connection:
    def __init__(self, faults):
        self.faults = faults
        self.events = []
        self.cursor_object = Cursor(self)

    def step(self, stage):
        self.events.append(stage)
        if stage in self.faults:
            raise self.faults[stage]

    def cursor(self):
        self.step("cursor")
        return self.cursor_object

    def commit(self):
        self.step("commit")

    def rollback(self):
        self.step("rollback")

    def close(self):
        self.step("connection_close")


class Cursor:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, parameters):
        if "insert into public.bounded_call_receipt" in sql:
            self.connection.step("body")

    def fetchone(self):
        return (sample_receipt().tenant_id,)

    def close(self):
        self.connection.step("cursor_close")


def run(owner, connection):
    if owner == "receipt":
        adapters.DbApiCallReceiptStore(
            lambda: connection, driver_name="psycopg", driver_version="3.3.6",
            qualified_band=adapters.VersionBand("psycopg", "3.3.0", "4.0.0"),
            tenant_context_provider=tenant_context,
        ).append(sample_receipt())
        return
    transaction = adapters._transaction if owner == "invocation" else workbench_transaction
    with transaction(lambda: connection):
        connection.step("body")


class DatabaseResourceCleanupTests(unittest.TestCase):
    owners = ("invocation", "receipt", "workbench")

    def test_cursor_acquisition_failure_releases_only_acquired_connection(self):
        for owner in self.owners:
            primary = ValueError("synthetic acquisition")
            connection = Connection({"cursor": primary})
            with self.subTest(owner=owner), self.assertRaises(ValueError) as caught:
                run(owner, connection)
            self.assertIs(caught.exception, primary)
            self.assertEqual(connection.events, ["cursor", "rollback", "connection_close"])

    def test_teardown_control_completes_release_after_success_or_body_failure(self):
        for owner in self.owners:
            for stage in ("cursor_close", "connection_close"):
                for signal in (KeyboardInterrupt, SystemExit):
                    for body_failed in (False, True):
                        control = signal("synthetic control")
                        primary = ValueError("synthetic body") if body_failed else None
                        faults = {stage: control} | ({"body": primary} if primary else {})
                        connection = Connection(faults)
                        with self.subTest(owner=owner, stage=stage, signal=signal, body=body_failed):
                            with self.assertRaises(signal) as caught:
                                run(owner, connection)
                            self.assertIs(caught.exception, control)
                            self.assertIs(control.primary_error, primary)
                            self.assertEqual(connection.events, [
                                "cursor", "body", "rollback" if body_failed else "commit",
                                "cursor_close", "connection_close",
                            ])
                            self.assertEqual([f.stage for f in control.cleanup_failures], [stage])

    def test_body_and_commit_failures_keep_all_ordinary_cleanup_diagnostics(self):
        for owner in self.owners:
            for failed_stage in ("body", "commit"):
                primary = ValueError("synthetic primary")
                faults = {failed_stage: primary, "rollback": OSError("private rollback"),
                          "cursor_close": OSError("private cursor"),
                          "connection_close": OSError("private connection")}
                connection = Connection(faults)
                with self.subTest(owner=owner, stage=failed_stage):
                    with self.assertRaises(ValueError) as caught:
                        run(owner, connection)
                    self.assertIs(caught.exception, primary)
                    self.assertEqual([f.stage for f in primary.cleanup_failures],
                                     ["rollback", "cursor_close", "connection_close"])
                    self.assertEqual([f.error for f in primary.cleanup_failures],
                                     [faults[s] for s in ("rollback", "cursor_close", "connection_close")])
                    self.assertTrue(all("private" not in note for note in primary.__notes__))
                    self.assertEqual(connection.events[-3:], ["rollback", "cursor_close", "connection_close"])

    def test_rollback_control_precedes_later_controls_and_keeps_body(self):
        for owner in self.owners:
            primary = ValueError("synthetic body")
            control = KeyboardInterrupt()
            connection = Connection({"body": primary, "rollback": control,
                                     "cursor_close": SystemExit(), "connection_close": OSError()})
            with self.subTest(owner=owner), self.assertRaises(KeyboardInterrupt) as caught:
                run(owner, connection)
            self.assertIs(caught.exception, control)
            self.assertIs(control.primary_error, primary)
            self.assertEqual(connection.events[-3:], ["rollback", "cursor_close", "connection_close"])
            self.assertEqual(len(control.cleanup_failures), 3)

    def test_primary_control_keeps_identity_through_later_control(self):
        for owner in self.owners:
            primary = SystemExit(17)
            connection = Connection({"body": primary, "cursor_close": KeyboardInterrupt()})
            with self.subTest(owner=owner), self.assertRaises(SystemExit) as caught:
                run(owner, connection)
            self.assertIs(caught.exception, primary)
            self.assertEqual(caught.exception.code, 17)
            self.assertEqual(connection.events[-3:], ["rollback", "cursor_close", "connection_close"])

    def test_ordinary_post_commit_failure_preserves_each_owner_error_type(self):
        for owner in self.owners:
            for stage in ("cursor_close", "connection_close"):
                failure = OSError("private close")
                connection = Connection({stage: failure})
                expected = RuntimeError if owner == "workbench" else adapters.ResourceReleaseError
                with self.subTest(owner=owner, stage=stage), self.assertRaises(expected) as caught:
                    run(owner, connection)
                self.assertIs(caught.exception.__cause__, failure)
                self.assertEqual(connection.events, ["cursor", "body", "commit", "cursor_close", "connection_close"])

    def test_workbench_retry_translation_keeps_sqlstate_cause_and_cleanup(self):
        class Retryable(Exception):
            def __init__(self, sqlstate):
                self.sqlstate = sqlstate
        for sqlstate in ("40001", "40P01"):
            primary = Retryable(sqlstate)
            connection = Connection({"body": primary, "connection_close": OSError("private")})
            with self.subTest(sqlstate=sqlstate), self.assertRaises(TransactionRetryRequired) as caught:
                run("workbench", connection)
            self.assertIs(caught.exception.__cause__, primary)
            self.assertEqual([f.stage for f in caught.exception.cleanup_failures], ["connection_close"])

    def test_control_with_driver_metadata_keeps_its_control_identity(self):
        primary = KeyboardInterrupt()
        primary.sqlstate = "40001"
        connection = Connection({"body": primary})
        with self.assertRaises(KeyboardInterrupt) as caught:
            run("workbench", connection)
        self.assertIs(caught.exception, primary)
        self.assertEqual(connection.events[-3:], ["rollback", "cursor_close", "connection_close"])
