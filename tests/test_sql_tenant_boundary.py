from __future__ import annotations

import hashlib
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import unittest

from lims_eln_implementation.security import (
    PostgresTenantBinding,
    SignedTenantContext,
    TenantSessionBindingError,
    tenant_context_signing_message,
)


ROOT = Path(__file__).resolve().parents[1]
TENANT_TABLES = {
    "tenant",
    "specimen",
    "specimen_event",
    "idempotency_ledger",
    "custody_position",
    "custody_event",
    "instrument_inbox",
    "instrument_measurement",
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
            self.observed = (json.loads(parameters[0])["tenant_id"],)

    def fetchone(self) -> tuple[object, ...] | None:
        return self.observed


class SqlTenantStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sql = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((ROOT / "sql").glob("[0-9][0-9][0-9]_*.sql"))
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
        predicate = r"tenant_id\s*=\s*laboratory_security\.authorized_tenant_id\(\)"
        for table in TENANT_TABLES:
            with self.subTest(table=table):
                policies = re.findall(
                    rf"create\s+policy\s+\w+\s+on\s+{table}"
                    rf"\s+using\s*\(({predicate})\)"
                    rf"\s+with\s+check\s*\(({predicate})\)\s*;",
                    self.sql,
                )
                self.assertTrue(policies)

    def test_caller_controlled_tenant_setting_is_replaced_by_signed_context(self) -> None:
        migration = (ROOT / "sql" / "002_principal_data_boundaries.sql").read_text(
            encoding="utf-8"
        ).lower()
        self.assertIn("laboratory_security.authorized_tenant_id()", migration)
        self.assertIn("public.hmac", migration)
        self.assertIn("laboratory_security.constant_time_equal", migration)
        self.assertIn("current_setting('app.tenant_context', true)", migration)
        self.assertNotIn("current_setting('app.tenant_id'", migration)

    def test_postgresql_regex_bounds_fit_the_engine_limit(self) -> None:
        upper_bounds = [
            int(value)
            for value in re.findall(r"\{\d+,(\d+)\}", self.sql)
        ]
        self.assertTrue(upper_bounds)
        self.assertTrue(all(value <= 255 for value in upper_bounds))

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

    def test_outbox_worker_mutations_use_tenant_bound_fenced_functions(self) -> None:
        migration = (
            ROOT / "sql" / "004_outbox_attempt_evidence_and_recovery.sql"
        ).read_text(encoding="utf-8").lower()
        self.assertRegex(
            migration,
            r"revoke\s+all\s+privileges\s+on\s+public\.transactional_outbox\s+"
            r"from\s+laboratory_outbox_worker,\s+laboratory_outbox_recovery_operator",
        )
        for function_name in (
            "claim_outbox_delivery",
            "reclaim_outbox_delivery",
            "confirm_outbox_delivery",
            "fail_outbox_delivery",
            "release_outbox_recovery",
        ):
            with self.subTest(function=function_name):
                self.assertIn(f"create function public.{function_name}", migration)
                self.assertIn(
                    f"grant execute on function public.{function_name}",
                    migration,
                )
        self.assertGreaterEqual(
            migration.count("laboratory_security.authorized_tenant_id()"),
            9,
        )
        self.assertIn("lease_principal = session_user", migration)
        self.assertIn("for update skip locked", migration)
        self.assertIn("delivery.fencing_token = expected_fencing_value", migration)
        self.assertIn("delivery.lease_token = lease_token_value", migration)
        self.assertIn("delivery.lease_expires_at_utc > pg_catalog.clock_timestamp()", migration)
        self.assertIn("lease_duration_seconds_value integer", migration)
        self.assertIn(
            "lease_duration_seconds_value not between 1 and 900",
            migration,
        )
        self.assertIn(
            "pg_catalog.make_interval(secs => lease_duration_seconds_value)",
            migration,
        )
        self.assertNotIn("lease_duration_value interval", migration)

    def test_migration_004_locks_outbox_before_provenance_preflight(self) -> None:
        migration = (
            ROOT / "sql" / "004_outbox_attempt_evidence_and_recovery.sql"
        ).read_text(encoding="utf-8").lower()
        self.assertIn("set local lock_timeout = '30s';", migration)
        self.assertIn("set local statement_timeout = '5min';", migration)
        self.assertIn(
            "set local idle_in_transaction_session_timeout = '5min';",
            migration,
        )
        lock_statement = (
            "lock table public.transactional_outbox in access exclusive mode;"
        )
        self.assertEqual(migration.count(lock_statement), 1)
        self.assertLess(
            migration.index(lock_statement),
            migration.index("do $migration_preflight$"),
        )

    def test_outbox_attempt_outcome_and_recovery_evidence_are_append_only(self) -> None:
        migration = (
            ROOT / "sql" / "004_outbox_attempt_evidence_and_recovery.sql"
        ).read_text(encoding="utf-8").lower()
        for relation in (
            "outbox_delivery_attempt",
            "outbox_delivery_attempt_outcome",
            "outbox_recovery_release",
        ):
            with self.subTest(relation=relation):
                self.assertIn(f"create table public.{relation}", migration)
                self.assertIn(f"alter table public.{relation} force row level security", migration)
                self.assertIn(f"{relation}_append_only", migration)
        self.assertIn("transport_receipt ~ '^[ -~]+$'", migration)
        self.assertIn("octet_length(transport_receipt) <= 512", migration)
        self.assertIn("transport_system is not null", migration)
        self.assertIn("transport_receipt is not null", migration)
        self.assertIn("transport_acknowledged_at_utc is not null", migration)
        self.assertIn("error_code is not null", migration)
        self.assertIn(
            "unique (tenant_id, transport_system, transport_receipt)",
            migration,
        )
        self.assertIn("outcome_kind = 'delivery_confirmed'", migration)
        self.assertIn("outcome_kind = 'recovery_required'", migration)

    def test_outbox_transition_matrix_and_initial_authority_are_explicit(self) -> None:
        migration = (
            ROOT / "sql" / "004_outbox_attempt_evidence_and_recovery.sql"
        ).read_text(encoding="utf-8").lower()
        for transition in (
            "old.delivery_state = 'ready' and new.delivery_state = 'leased'",
            "old.delivery_state = 'leased' and new.delivery_state = 'leased'",
            "old.delivery_state = 'leased' and new.delivery_state = 'delivered'",
            "new.delivery_state = 'recovery_required'",
            "new.delivery_state = 'ready'",
        ):
            with self.subTest(transition=transition):
                self.assertIn(transition, migration)
        self.assertIn("an outbox message begins in the ready state", migration)
        self.assertIn("last_error_code is not null", migration)
        self.assertIn(
            "revoke all privileges on public.transactional_outbox from laboratory_app",
            migration,
        )
        self.assertIn("grant insert (", migration)
        self.assertIn("add constraint outbox_message_id_bounded", migration)
        self.assertIn("octet_length(message_id) <= 256", migration)
        self.assertIn(
            "migration 004 requires bounded outbox message identities",
            migration,
        )
        self.assertIn(
            "migration 004 requires an initial ready outbox provenance boundary",
            migration,
        )
        self.assertIn(
            "pg_catalog.make_interval(secs => 86400)",
            migration,
        )
        self.assertNotIn("interval '1 day'", migration)

    def test_migration_003_remains_immutable_and_004_is_successor(self) -> None:
        migration_003 = ROOT / "sql" / "003_trusted_routines_and_outbox_cas.sql"
        self.assertEqual(
            hashlib.sha256(migration_003.read_bytes()).hexdigest(),
            "13925ea70a930ef69240de8e0ffe56e5cb4479fb64e48cf41e6051dc8eb66a70",
        )
        manifest = json.loads(
            (ROOT / "database" / "migration-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            [entry["id"] for entry in manifest["migrations"]],
            ["001", "002", "003", "004"],
        )

    def test_security_definer_data_objects_are_schema_qualified(self) -> None:
        migration = (ROOT / "sql" / "003_trusted_routines_and_outbox_cas.sql").read_text(
            encoding="utf-8"
        ).lower()
        self.assertGreaterEqual(
            migration.count("set search_path = pg_catalog, pg_temp"),
            5,
        )
        self.assertIn("returns public.custody_position", migration)
        self.assertIn("public.custody_position%rowtype", migration)
        self.assertIn("public.custody_event%rowtype", migration)
        for fragment in (
            "from public.custody_event",
            "from public.custody_position",
            "insert into public.custody_event",
            "insert into public.custody_position",
            "update public.custody_position",
            "insert into public.transactional_outbox",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, migration)

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
    def context(self, tenant_id: str = "SYN-TENANT-A") -> SignedTenantContext:
        return SignedTenantContext(
            tenant_id=tenant_id,
            subject_id="SYN-SERVICE-IDENTITY-01",
            key_id="synthetic-test-v1",
            issued_at_epoch=1_785_240_000,
            expires_at_epoch=1_785_240_300,
            nonce="SYNTHETIC-NONCE-0001",
            signature_hex="a" * 64,
        )

    def test_binding_uses_a_transaction_local_parameter_and_verifies_result(self) -> None:
        cursor = FakeCursor()
        binding = PostgresTenantBinding(self.context())
        binding.bind(cursor)
        assert cursor.execution is not None
        self.assertEqual(cursor.execution[0], PostgresTenantBinding.STATEMENT)
        self.assertEqual(json.loads(cursor.execution[1][0])["tenant_id"], "SYN-TENANT-A")
        self.assertNotIn("SYN-TENANT-A", PostgresTenantBinding.STATEMENT)

    def test_binding_returns_connection_to_recovery_on_identity_mismatch(self) -> None:
        cursor = FakeCursor(("SYN-TENANT-B",))
        with self.assertRaisesRegex(
            TenantSessionBindingError,
            "fresh transaction",
        ):
            PostgresTenantBinding(self.context()).bind(cursor)

    def test_provider_context_must_match_the_requested_tenant(self) -> None:
        cursor = FakeCursor()
        with self.assertRaisesRegex(TenantSessionBindingError, "identity reconciliation"):
            PostgresTenantBinding(self.context("SYN-TENANT-B")).bind(
                cursor,
                expected_tenant_id="SYN-TENANT-A",
            )
        self.assertIsNone(cursor.execution)

    def test_context_requires_bounded_identity_lifetime_nonce_and_signature(self) -> None:
        with self.assertRaisesRegex(ValueError, "1..128"):
            self.context("")
        with self.assertRaisesRegex(ValueError, "900 seconds"):
            SignedTenantContext(
                tenant_id="SYN-TENANT-A",
                subject_id="SYN-SERVICE-IDENTITY-01",
                key_id="synthetic-test-v1",
                issued_at_epoch=1_785_240_000,
                expires_at_epoch=1_785_241_000,
                nonce="SYNTHETIC-NONCE-0001",
                signature_hex="a" * 64,
            )

    def test_issuer_and_database_share_one_signing_byte_contract(self) -> None:
        context = self.context()
        self.assertEqual(
            tenant_context_signing_message(
                tenant_id=context.tenant_id,
                subject_id=context.subject_id,
                key_id=context.key_id,
                issued_at_epoch=context.issued_at_epoch,
                expires_at_epoch=context.expires_at_epoch,
                nonce=context.nonce,
            ),
            (
                "SYN-TENANT-A\nSYN-SERVICE-IDENTITY-01\nsynthetic-test-v1\n"
                "1785240000\n1785240300\nSYNTHETIC-NONCE-0001"
            ).encode("utf-8"),
        )


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
