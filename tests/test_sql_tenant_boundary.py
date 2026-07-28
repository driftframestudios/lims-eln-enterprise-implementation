from __future__ import annotations

from pathlib import Path
import re
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


if __name__ == "__main__":
    unittest.main()
