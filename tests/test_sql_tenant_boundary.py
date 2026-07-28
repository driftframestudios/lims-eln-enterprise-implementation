from __future__ import annotations

from pathlib import Path
import os
import re
import shutil
import subprocess
import unittest

from lims_eln_implementation.security import (
    PostgresTenantBinding,
    TenantSessionBindingError,
)


ROOT = Path(__file__).resolve().parents[1]
TENANT_TABLES = {
    "tenant",
    "specimen",
    "specimen_event",
    "idempotency_ledger",
    "custody_position",
    "instrument_inbox",
    "transactional_outbox",
    "vendor_projection",
    "migration_checkpoint",
    "bounded_call_invocation",
    "bounded_call_receipt",
    "evidence_receipt",
    "acceptance_decision",
    "acceptance_decision_receipt",
}


class FakeCursor:
    def __init__(self, observed: tuple[object, ...] | None = None) -> None:
        self.observed = observed
        self.execution: tuple[str, tuple[str]] | None = None

    def execute(self, operation: str, parameters: tuple[str]) -> None:
        self.execution = (operation, parameters)
        if self.observed is None:
            self.observed = parameters

    def fetchone(self) -> tuple[object, ...] | None:
        return self.observed


class SqlTenantStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sql = (ROOT / "sql" / "001_laboratory_core.sql").read_text(
            encoding="utf-8"
        ).lower()

    def test_every_tenant_table_enables_and_forces_row_level_security(self) -> None:
        for table in TENANT_TABLES:
            with self.subTest(table=table):
                self.assertRegex(
                    self.sql,
                    rf"alter\s+table\s+{table}\s+enable\s+row\s+level\s+security\s*;",
                )
                self.assertRegex(
                    self.sql,
                    rf"alter\s+table\s+{table}\s+force\s+row\s+level\s+security\s*;",
                )

    def test_every_tenant_table_has_read_and_write_tenant_predicates(self) -> None:
        predicate = (
            r"tenant_id\s*=\s*current_setting\('app\.tenant_id',\s*true\)"
        )
        for table in TENANT_TABLES:
            with self.subTest(table=table):
                policy = re.search(
                    rf"create\s+policy\s+\w+\s+on\s+{table}"
                    rf"\s+using\s*\(({predicate})\)"
                    rf"\s+with\s+check\s*\(({predicate})\)\s*;",
                    self.sql,
                )
                self.assertIsNotNone(policy)

    def test_all_declared_tenant_id_tables_participate_in_boundary(self) -> None:
        table_definitions = re.findall(
            r"create\s+table\s+(\w+)\s*\((.*?)\);",
            self.sql,
            flags=re.DOTALL,
        )
        declared = {
            table
            for table, columns in table_definitions
            if re.search(r"\btenant_id\s+text\b", columns)
        }
        self.assertEqual(declared, TENANT_TABLES)

    def test_bounded_call_persistence_has_fencing_and_audit_provenance(self) -> None:
        invocation = re.search(
            r"create\s+table\s+bounded_call_invocation\s*\((.*?)\);",
            self.sql,
            flags=re.DOTALL,
        )
        receipt = re.search(
            r"create\s+table\s+bounded_call_receipt\s*\((.*?)\);",
            self.sql,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(invocation)
        self.assertIsNotNone(receipt)
        assert invocation is not None and receipt is not None
        for field in (
            "invocation_sha256",
            "operation_contract_sha256",
            "lease_token",
            "fencing_token",
            "lease_expires_at_utc",
            "output_document",
            "result_sha256",
            "recovery_reason",
        ):
            self.assertIn(field, invocation.group(1))
        for field in (
            "operation_contract_sha256",
            "invocation_sha256",
            "grant_id",
            "budget_window_id",
            "requested_at_utc",
            "recorded_at_utc",
        ):
            self.assertIn(field, receipt.group(1))

    def test_workload_roles_are_non_superuser_and_bypassrls_is_disabled(self) -> None:
        for role in (
            "laboratory_app",
            "laboratory_outbox_worker",
            "laboratory_evidence_writer",
            "laboratory_migrator",
        ):
            with self.subTest(role=role):
                self.assertRegex(
                    self.sql,
                    rf"create\s+role\s+{role}\s+"
                    r"(?:login|nologin)\s+nosuperuser\s+nocreatedb\s+"
                    r"nocreaterole\s+noinherit\s+nobypassrls\s*;",
                )
        self.assertIn("revoke all on all tables in schema public from public", self.sql)
        self.assertNotRegex(
            self.sql,
            r"grant\s+laboratory_(?:owner|migrator|evidence_writer)\s+"
            r"to\s+laboratory_app",
        )

    def test_outbox_has_owned_leases_fencing_and_recovery_state(self) -> None:
        outbox = re.search(
            r"create\s+table\s+transactional_outbox\s*\((.*?)\);",
            self.sql,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(outbox)
        assert outbox is not None
        for field in (
            "delivery_state",
            "lease_owner",
            "lease_token",
            "fencing_token",
            "lease_expires_at_utc",
            "last_error_code",
        ):
            self.assertIn(field, outbox.group(1))

    def test_regulated_evidence_is_tenant_scoped_and_append_only(self) -> None:
        self.assertIn("evidence_receipt_append_only", self.sql)
        self.assertIn("acceptance_decision_append_only", self.sql)
        self.assertIn("acceptance_decision_receipt_append_only", self.sql)
        for table in ("evidence_receipt", "acceptance_decision"):
            definition = re.search(
                rf"create\s+table\s+{table}\s*\((.*?)\);",
                self.sql,
                flags=re.DOTALL,
            )
            self.assertIsNotNone(definition)
            assert definition is not None
            for field in ("tenant_id", "intended_use_id", "release_claim_id"):
                self.assertIn(field, definition.group(1))
        junction = re.search(
            r"create\s+table\s+acceptance_decision_receipt\s*\((.*?)\);",
            self.sql,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(junction)
        assert junction is not None
        self.assertEqual(junction.group(1).count("references"), 3)

    def test_compose_uses_separate_bootstrap_and_application_identities(self) -> None:
        compose = (ROOT / "infra" / "docker-compose.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("POSTGRES_USER: laboratory_bootstrap", compose)
        self.assertIn("PGUSER: laboratory_app", compose)
        self.assertIn("postgres_app_password", compose)
        self.assertNotIn("POSTGRES_USER: laboratory\n", compose)


class PostgresTenantBindingTests(unittest.TestCase):
    def test_binding_uses_a_transaction_local_parameter_and_verifies_result(self) -> None:
        cursor = FakeCursor()
        binding = PostgresTenantBinding("SYN-TENANT-A")
        binding.bind(cursor)
        self.assertEqual(
            cursor.execution,
            (
                "select set_config('app.tenant_id', %s, true)",
                ("SYN-TENANT-A",),
            ),
        )
        self.assertNotIn("SYN-TENANT-A", PostgresTenantBinding.STATEMENT)

    def test_binding_returns_connection_to_recovery_on_identity_mismatch(self) -> None:
        cursor = FakeCursor(("SYN-TENANT-B",))
        with self.assertRaisesRegex(
            TenantSessionBindingError,
            "fresh transaction",
        ):
            PostgresTenantBinding("SYN-TENANT-A").bind(cursor)

    def test_binding_requires_a_printable_bounded_identity(self) -> None:
        with self.assertRaisesRegex(ValueError, "1..128"):
            PostgresTenantBinding("")
        with self.assertRaisesRegex(ValueError, "printable"):
            PostgresTenantBinding("SYN-TENANT\nA")


@unittest.skipUnless(
    os.environ.get("LIMS_TEST_POSTGRES_DSN") and shutil.which("psql"),
    "set LIMS_TEST_POSTGRES_DSN with psql available for the live RLS proof",
)
class PostgresRoleIntegrationTests(unittest.TestCase):
    def test_application_role_cannot_bypass_rls(self) -> None:
        completed = subprocess.run(
            [
                shutil.which("psql") or "psql",
                os.environ["LIMS_TEST_POSTGRES_DSN"],
                "--no-psqlrc",
                "--tuples-only",
                "--no-align",
                "--set",
                "ON_ERROR_STOP=1",
                "--command",
                (
                    "select rolsuper::text || ':' || rolbypassrls::text "
                    "from pg_roles where rolname = current_user"
                ),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.stdout.strip(), "false:false")


if __name__ == "__main__":
    unittest.main()
