"""Bounded local entry, credential delivery, and selected-adapter readiness."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import hmac
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from lims_eln_implementation.security import TenantSessionBindingError, tenant_context_signing_message
from lims_eln_implementation.workbench import cli, runtime
from lims_eln_implementation.workbench.api import create_app
from lims_eln_implementation.workbench.postgres import PostgresWorkbenchService
from lims_eln_implementation.workbench.service import WorkbenchService

from test_workbench_postgres_adapter import RecordingConnection, RecordingCursor, context_for


class RuntimeSettingsTests(unittest.TestCase):
    def environment(self) -> dict[str, str]:
        return {
            "LIMS_WORKBENCH_ADAPTER": "postgresql",
            "LIMS_WORKBENCH_DB_PASSWORD_FILE": "local/password",
            "LIMS_WORKBENCH_TENANT_KEY_FILE": "local/tenant-key",
        }

    def test_memory_entry_uses_an_immutable_snapshot_without_secret_files(self) -> None:
        environment = {"LIMS_WORKBENCH_DB_PORT": "unused"}
        settings = runtime.settings_from_environment(environment)
        environment["LIMS_WORKBENCH_ADAPTER"] = "postgresql"
        self.assertEqual(settings.adapter, "process_local")
        with self.assertRaises(FrozenInstanceError):
            settings.adapter = "postgresql"

    def test_configured_ports_and_defaults(self) -> None:
        for port in ("1", "5432", "65535"):
            with self.subTest(port=port):
                settings = runtime.settings_from_environment({
                    **self.environment(), "LIMS_WORKBENCH_DB_PORT": port
                })
                self.assertEqual(settings.port, int(port))
                self.assertEqual(settings.database, "laboratory")
                self.assertEqual(settings.host, "127.0.0.1")

    def test_invalid_configuration_names_the_setting_and_preserves_values(self) -> None:
        cases = [
            ("LIMS_WORKBENCH_ADAPTER", "other"),
            ("LIMS_WORKBENCH_DB_HOST", "host,other"),
            ("LIMS_WORKBENCH_DB_NAME", "db name"),
            ("LIMS_WORKBENCH_TENANT_KEY_ID", "key/name"),
            ("LIMS_WORKBENCH_DB_PASSWORD_FILE", " "),
            ("LIMS_WORKBENCH_TENANT_KEY_FILE", "\0"),
        ]
        cases += [("LIMS_WORKBENCH_DB_PORT", value) for value in (
            "0", "65536", "-1", "1.0", " 5432", "１２", "9" * 5000
        )]
        for setting, value in cases:
            with self.subTest(setting=setting, length=len(value)):
                environment = {**self.environment(), setting: value}
                before = dict(environment)
                with self.assertRaisesRegex(runtime.RuntimeConfigurationError, setting):
                    runtime.settings_from_environment(environment)
                self.assertEqual(environment, before)

    def test_secret_file_reads_are_bounded_and_value_free(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "secret"
            target.write_bytes(b"preserved spaces \n")
            self.assertEqual(runtime._read_secret(target, "PASSWORD_FILE"), "preserved spaces ")
            for payload in (b"", b"a\0b", b"a\nb", b"\xff", b"x" * 1025):
                with self.subTest(length=len(payload)):
                    target.write_bytes(payload)
                    with self.assertRaisesRegex(runtime.RuntimeConfigurationError, "PASSWORD_FILE"):
                        runtime._read_secret(target, "PASSWORD_FILE")
            target.unlink()
            for path in (target, Path(directory)):
                with self.subTest(kind=path.name):
                    with self.assertRaisesRegex(runtime.RuntimeConfigurationError, "PASSWORD_FILE"):
                        runtime._read_secret(path, "PASSWORD_FILE")
            target.symlink_to(Path(directory) / "absent")
            with self.assertRaisesRegex(runtime.RuntimeConfigurationError, "PASSWORD_FILE"):
                runtime._read_secret(target, "PASSWORD_FILE")

    def test_tenant_assertions_have_fresh_nonces_and_exact_signed_fields(self) -> None:
        key = bytes(range(32))
        issuer = runtime.local_tenant_issuer(key.hex(), "local-compose-v1")
        with patch.object(runtime.time, "time", side_effect=[1000, 1061]):
            first = issuer("SYN-TENANT-A")
            second = issuer("SYN-TENANT-A")
        self.assertEqual((first.issued_at_epoch, first.expires_at_epoch), (1000, 1060))
        self.assertEqual((second.issued_at_epoch, second.expires_at_epoch), (1061, 1121))
        self.assertNotEqual(first.nonce, second.nonce)
        self.assertEqual(first.subject_id, "svc-golden-specimen-workbench")
        fields = first.as_document()
        signature = fields.pop("signature_hex")
        self.assertEqual(
            signature,
            hmac.digest(key, tenant_context_signing_message(**fields), "sha256").hex(),
        )
        with self.assertRaises(TenantSessionBindingError):
            issuer("SYN-TENANT-B")
        for value in ("", "a" * 63, "A" * 64, "z" * 64):
            with self.subTest(key_length=len(value)):
                with self.assertRaises(runtime.RuntimeConfigurationError):
                    runtime.local_tenant_issuer(value, "local-compose-v1")

    def test_cli_keeps_factory_selection_available_to_reload(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch(
            "sys.argv", ["lims-eln-workbench", "--adapter", "postgresql", "--reload"]
        ), patch.object(cli.uvicorn, "run") as run:
            cli.main()
            self.assertEqual(os.environ["LIMS_WORKBENCH_ADAPTER"], "postgresql")
            run.assert_called_once_with(
                "lims_eln_implementation.workbench.runtime:create_configured_app",
                factory=True, host="127.0.0.1", port=8000, reload=True,
            )

    def test_memory_factory_needs_only_its_own_configuration(self) -> None:
        with patch.dict(os.environ, {}, clear=True), TestClient(runtime.create_configured_app()) as client:
            self.assertEqual(client.get("/health/ready").json(), {
                "status": "ready", "state_adapter": "process_local"
            })

    def test_database_factory_retains_connection_and_issuer_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            password = Path(directory) / "password"
            key = Path(directory) / "key"
            password.write_text("local-fixture-value", encoding="ascii")
            key.write_text(bytes(range(32)).hex(), encoding="ascii")
            environment = {
                **self.environment(),
                "LIMS_WORKBENCH_DB_PASSWORD_FILE": str(password),
                "LIMS_WORKBENCH_TENANT_KEY_FILE": str(key),
            }
            connection = RecordingConnection(ReadinessCursor())
            connect = Mock(return_value=connection)
            with patch.dict(os.environ, environment, clear=True), patch.dict(
                "sys.modules", {"psycopg": SimpleNamespace(connect=connect)}
            ), patch.object(runtime, "contract_available", return_value=True):
                app = runtime.create_configured_app()
                connect.assert_not_called()
                with TestClient(app) as client:
                    self.assertEqual(client.get("/health/ready").status_code, 200)
                self.assertEqual(connect.call_args.kwargs["user"], "laboratory_app")
                self.assertEqual(connect.call_args.kwargs["password"], "local-fixture-value")
                self.assertEqual(connect.call_args.kwargs["connect_timeout"], 5)
                self.assertTrue(connection.closed)
                self.assertEqual(connection.commits, 1)


class ReadinessCursor(RecordingCursor):
    def __init__(self, role=("laboratory_app", "laboratory_app", False, False)):
        super().__init__()
        self.role = role

    def fetchone(self):
        if "from pg_catalog.pg_roles" in self.last_operation:
            return self.role
        return super().fetchone()


class AdapterReadinessTests(unittest.TestCase):
    def test_postgresql_readiness_uses_bound_read_only_transaction(self) -> None:
        connection = RecordingConnection(ReadinessCursor())
        service = PostgresWorkbenchService(lambda: connection, tenant_context_provider=context_for)
        service.check_ready()
        operations = [operation for operation, _ in connection.recording_cursor.operations]
        self.assertIn("set transaction read only", operations)
        self.assertTrue(any("bind_tenant_context" in operation for operation in operations))
        self.assertTrue(any("specimen_workbench_snapshot" in operation for operation in operations))
        self.assertTrue(any("bounded_call_invocation" in operation for operation in operations))
        self.assertIn("select laboratory_security.workbench_migration_head()", operations)
        self.assertEqual(connection.commits, 1)
        self.assertTrue(connection.closed)

    def assert_provenance_readiness_failure(self) -> None:
        for head in (None, ("007",)):
            class UnavailableProvenanceCursor(ReadinessCursor):
                def fetchone(self):
                    if "workbench_migration_head" in self.last_operation:
                        return head
                    return super().fetchone()

            with self.subTest(migration_head=head):
                connection = RecordingConnection(UnavailableProvenanceCursor())
                service = PostgresWorkbenchService(
                    lambda: connection, tenant_context_provider=context_for,
                )
                with TestClient(create_app(service)) as client:
                    self.assertEqual(client.get("/health/live").status_code, 200)
                    self.assertEqual(client.get("/health/ready").status_code, 503)
                self.assertEqual((connection.commits, connection.rollbacks), (0, 1))
                self.assertTrue(connection.closed)

    def test_privileged_or_changed_database_identity_stays_unready(self) -> None:
        self.assert_provenance_readiness_failure()
        for role in (
            ("laboratory_bootstrap", "laboratory_bootstrap", True, True),
            ("laboratory_app", "laboratory_app", False, True),
            ("laboratory_app", "laboratory_owner", False, False),
        ):
            with self.subTest(role=role):
                connection = RecordingConnection(ReadinessCursor(role))
                service = PostgresWorkbenchService(lambda: connection, tenant_context_provider=context_for)
                with TestClient(create_app(service)) as client:
                    self.assertEqual(client.get("/health/live").status_code, 200)
                    response = client.get("/health/ready")
                    self.assertEqual(response.status_code, 503)
                    self.assertEqual(response.json()["state_adapter"], "postgresql")
                self.assertEqual(connection.rollbacks, 1)
                self.assertTrue(connection.closed)

    def test_dependency_outage_recovers_without_replacing_accepted_service(self) -> None:
        service = WorkbenchService()
        with patch.object(service, "check_ready", side_effect=[OSError("protected detail"), None]):
            with TestClient(create_app(service)) as client:
                self.assertEqual(client.get("/health/live").json(), {"status": "live"})
                response = client.get("/health/ready")
                self.assertEqual(response.status_code, 503)
                self.assertNotIn("protected detail", response.text)
                self.assertEqual(client.get("/health/ready").status_code, 200)
                self.assertIs(client.app.state.workbench, service)


if __name__ == "__main__":
    unittest.main()
