"""Owned-process faults and an explicitly enabled native restart observation."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from scripts.check_database_restart import OwnedPostgres, RestartProofError, exercise


class OwnedPostgresTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.commands = []
        self.start_failure = False
        self.stop_failure = False
        self.cluster = None

        def command(cluster, name, *arguments):
            self.commands.append((name, arguments))
            if arguments == ("--version",):
                return subprocess.CompletedProcess([], 0, f"{name} (PostgreSQL) 18.6", "")
            if name == "initdb":
                cluster.data.mkdir(mode=0o700)
            elif name == "pg_ctl" and arguments[-1] == "start":
                (cluster.data / "postmaster.pid").write_text(
                    f"424242\n{cluster.data}\n{int(time.time())}\n", encoding="utf-8"
                )
                if self.start_failure:
                    raise RestartProofError("synthetic startup wait failure")
            elif name == "pg_ctl" and arguments[-1] == "stop":
                if self.stop_failure:
                    raise RestartProofError("synthetic stop failure")
                (cluster.data / "postmaster.pid").unlink()
            return subprocess.CompletedProcess([], 0, "", "")

        self.fake_command = patch.object(OwnedPostgres, "_command", command)
        self.fake_command.start()
        self.addCleanup(self.fake_command.stop)
        self.addCleanup(self.remove_test_files)

    def remove_test_files(self):
        # These tests create files through the fake process runner; they own zero live servers.
        if self.cluster is not None and self.cluster.root is not None:
            shutil.rmtree(self.cluster.root)

    def create(self):
        self.cluster = OwnedPostgres(Path(tempfile.gettempdir()), 18)
        return self.cluster

    def test_major_and_binary_version_mismatch_precede_resource_acquisition(self):
        with self.assertRaisesRegex(RestartProofError, "major differs"):
            OwnedPostgres(Path(tempfile.gettempdir()), 17)
        with patch.object(OwnedPostgres, "_command", side_effect=[
            subprocess.CompletedProcess([], 0, f"tool (PostgreSQL) {version}", "")
            for version in ("18.6", "18.5", "18.6", "18.6", "18.6")
        ]):
            with self.assertRaisesRegex(RestartProofError, "one exact version"):
                OwnedPostgres(Path(tempfile.gettempdir()), 18)

    def test_external_connection_environment_precedes_resource_acquisition(self):
        with patch.dict(os.environ, {"PGSERVICE": "synthetic-external-service"}):
            with self.assertRaisesRegex(RestartProofError, "overrides cleared"):
                self.create()
        self.assertEqual(self.commands, [])

    def test_success_removes_only_fresh_owned_directory(self):
        with tempfile.TemporaryDirectory() as neighboring:
            marker = Path(neighboring) / "retain"
            marker.write_text("owned elsewhere", encoding="utf-8")
            with self.create() as cluster:
                owned = cluster.root
                self.assertEqual(owned.stat().st_mode & 0o777, 0o700)
                self.assertEqual(cluster.socket.stat().st_mode & 0o777, 0o700)
            self.assertFalse(owned.exists())
            self.assertEqual(marker.read_text(encoding="utf-8"), "owned elsewhere")

    def test_changed_process_lifetime_preserves_directory_and_sends_zero_signals(self):
        cluster = self.create().__enter__()
        identity = cluster._process_identity
        pid = cluster.data / "postmaster.pid"
        pid.write_text(f"424243\n{cluster.data}\n{identity[2]}\n", encoding="utf-8")
        calls_before = len(self.commands)
        with self.assertRaisesRegex(RestartProofError, "lifetime changed"):
            cluster.stop()
        self.assertEqual(len(self.commands), calls_before)
        self.assertTrue(pid.exists())

    def test_changed_data_directory_preserves_replacement_and_sends_zero_signals(self):
        cluster = self.create().__enter__()
        cluster.data.rename(cluster.root / "original-data")
        cluster.data.mkdir(mode=0o700)
        marker = cluster.data / "retain"
        marker.write_text("replacement owner", encoding="utf-8")
        calls_before = len(self.commands)
        with self.assertRaisesRegex(RestartProofError, "data identity changed"):
            cluster.stop()
        self.assertEqual(len(self.commands), calls_before)
        self.assertEqual(marker.read_text(encoding="utf-8"), "replacement owner")

    def test_partial_start_failure_stops_acquired_process_and_removes_files(self):
        self.start_failure = True
        cluster = self.create()
        with self.assertRaisesRegex(RestartProofError, "startup wait failure"):
            cluster.__enter__()
        self.assertIsNone(cluster.root)
        self.assertEqual(self.commands[-1][1][-1], "stop")

    def test_body_failure_releases_owned_cluster_and_preserves_primary(self):
        with self.assertRaisesRegex(ValueError, "synthetic body failure"):
            with self.create():
                raise ValueError("synthetic body failure")
        self.assertIsNone(self.cluster.root)

    def test_cleanup_failure_preserves_primary_and_private_recovery_path(self):
        self.stop_failure = True
        with self.assertRaisesRegex(ValueError, "synthetic body failure") as observed:
            with self.create():
                raise ValueError("synthetic body failure")
        self.assertTrue(self.cluster.root.exists())
        self.assertIn(str(self.cluster.root), " ".join(observed.exception.__notes__))

    def test_cleanup_failure_turns_success_into_explicit_recovery(self):
        self.stop_failure = True
        with self.assertRaisesRegex(RestartProofError, "retained for private recovery"):
            with self.create():
                pass
        self.assertTrue(self.cluster.root.exists())

    def test_subprocess_timeout_has_bounded_value_free_error(self):
        self.fake_command.stop()
        with patch("scripts.check_database_restart.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("synthetic-private-command", 35)) as run:
            with self.assertRaisesRegex(RestartProofError, "postgres invocation failed"):
                OwnedPostgres(Path(tempfile.gettempdir()), 18, timeout=30)
        self.assertEqual(run.call_args.kwargs["timeout"], 35)
        self.fake_command.start()

    def test_authored_history_is_explicit_and_keeps_source_order(self):
        sources = [
            {"path": "database/provision_cluster_roles.sql", "sha256": "a" * 64},
            {"path": "sql/V001__first.sql", "sha256": "b" * 64},
            {"path": "sql/V002__second.sql", "sha256": "c" * 64},
        ]
        connection = MagicMock()
        cursor = connection.__enter__.return_value.cursor.return_value.__enter__.return_value
        with self.create() as cluster, patch.object(cluster, "connect", return_value=connection) as connect:
            metadata = cluster.install_authored_history_fixture(sources)
        connect.assert_called_once_with("proof_owner")
        self.assertEqual(cursor.executemany.call_args.args[1], [
            (1, "001", "SQL", "V001__first.sql", 0, True),
            (2, "002", "SQL", "V002__second.sql", 0, True),
        ])
        self.assertEqual(metadata, {
            "origin": "authored_native_proof_fixture", "rows": 2,
            "checksum_meaning": "placeholder_zero", "source_binding": "migration_sources_sha256",
        })
        ddl = cursor.execute.call_args.args[0]
        self.assertIn("owner to laboratory_owner", ddl)
        self.assertIn("revoke all on public.flyway_schema_history from public, laboratory_app", ddl)
        self.assertIn("Authored native proof fixture", ddl)

    def test_authored_history_rejects_incomplete_source_sets_before_connecting(self):
        for paths in ([], ["sql/V002__second.sql"], ["sql/V001__first.sql"] * 2,
                      ["sql/V001xxfirst.sql"], ["sql/V001__first.sql", "sql/V003__third.sql"]):
            with self.subTest(paths=paths), self.create() as cluster:
                with patch.object(cluster, "connect") as connect:
                    with self.assertRaises(RestartProofError):
                        cluster.install_authored_history_fixture(
                            [{"path": path, "sha256": "a" * 64} for path in paths]
                        )
                    connect.assert_not_called()


@unittest.skipUnless(os.environ.get("LIMS_DATABASE_RESTART_CHECK") == "1",
                     "explicit native owned-cluster activation enables database restart proof")
class ConfiguredDatabaseRestartTests(unittest.TestCase):
    def test_database_process_restart_crash_rollback_and_reentry(self):
        binaries = Path(os.environ["LIMS_RESTART_POSTGRES_BIN"])
        major = int(os.environ["LIMS_RESTART_EXPECTED_MAJOR"])
        result = exercise(binaries, major)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["server_lifetimes"], 3)
        self.assertEqual(result["owned_clusters_cleaned"], 3)
        self.assertEqual(len(result["scenarios"]), 7)
        self.assertEqual(result["migration_history_fixture"], {
            "origin": "authored_native_proof_fixture", "rows": 8,
            "checksum_meaning": "placeholder_zero", "source_binding": "migration_sources_sha256",
        })


if __name__ == "__main__":
    unittest.main()
