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
    "instrument_review_resolution",
    "transactional_outbox",
    "outbox_delivery_attempt",
    "outbox_delivery_attempt_outcome",
    "outbox_recovery_release",
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
            for path in sorted((ROOT / "sql").glob("V[0-9][0-9][0-9]__*.sql"))
        ).lower()

    def test_every_tenant_table_enables_and_forces_row_level_security(self) -> None:
        for table in TENANT_TABLES:
            with self.subTest(table=table):
                self.assertRegex(
                    self.sql,
                    rf"alter\s+table\s+(?:public\.)?{table}\s+enable\s+row\s+level\s+security\s*;",
                )
                self.assertRegex(
                    self.sql,
                    rf"alter\s+table\s+(?:public\.)?{table}\s+force\s+row\s+level\s+security\s*;",
                )

    def test_every_tenant_table_has_read_and_write_tenant_predicates(self) -> None:
        predicate = r"tenant_id\s*=\s*laboratory_security\.authorized_tenant_id\(\)"
        for table in TENANT_TABLES:
            with self.subTest(table=table):
                policies = re.findall(
                    rf"create\s+policy\s+\w+\s+on\s+(?:public\.)?{table}"
                    rf"\s+using\s*\(({predicate})\)"
                    rf"\s+with\s+check\s*\(({predicate})\)\s*;",
                    self.sql,
                )
                self.assertTrue(policies)

    def test_caller_controlled_tenant_setting_is_replaced_by_signed_context(self) -> None:
        migration = (ROOT / "sql" / "V002__principal_data_boundaries.sql").read_text(
            encoding="utf-8"
        ).lower()
        self.assertIn("laboratory_security.authorized_tenant_id()", migration)
        self.assertIn("public.hmac", migration)
        self.assertIn("laboratory_security.constant_time_equal", migration)
        self.assertIn("current_setting('app.tenant_context', true)", migration)
        self.assertNotIn("current_setting('app.tenant_id'", migration)

    def test_cross_tenant_migration_policy_requires_the_bounded_session(self) -> None:
        migration = (ROOT / "sql" / "V002__principal_data_boundaries.sql").read_text(
            encoding="utf-8"
        ).lower()
        function = "laboratory_security.bounded_migration_session_active()"
        for required_fragment in (
            "session_user = 'laboratory_migrator'",
            "current_user = 'laboratory_owner'",
            "current_setting('role', true) = 'laboratory_owner'",
            "not login_role.rolsuper",
            "not login_role.rolinherit",
            "not login_role.rolbypassrls",
            "not membership.admin_option",
            "not membership.inherit_option",
            "membership.set_option",
            "granted_role.rolname = 'laboratory_outbox_authority'",
            "member_role.rolname = 'laboratory_owner'",
            "configuration.value = 'role=laboratory_owner'",
            "database_acl.privilege_type = 'connect'",
            "not database_acl.is_grantable",
        ):
            with self.subTest(required_fragment=required_fragment):
                self.assertIn(required_fragment, migration)
        self.assertIn(
            "if laboratory_security.bounded_migration_session_active() then\n"
            "        return null;",
            migration,
        )
        self.assertIn(
            f"revoke all on function {function}\n    from public",
            migration,
        )
        for table in TENANT_TABLES:
            with self.subTest(table=table):
                self.assertRegex(
                    self.sql,
                    rf"create\s+policy\s+\w+_bounded_migration_policy\s+"
                    rf"on\s+(?:public\.)?{table}\s+for\s+all\s+"
                    rf"to\s+laboratory_owner\s+using\s*\({re.escape(function)}\)\s+"
                    rf"with\s+check\s*\({re.escape(function)}\)\s*;",
                )
        for table in (
            "outbox_delivery_attempt",
            "outbox_delivery_attempt_outcome",
            "outbox_recovery_release",
        ):
            with self.subTest(table=table):
                self.assertIn(
                    f"create policy {table}_bounded_migration_policy",
                    self.sql,
                )

    def test_postgresql_regex_bounds_fit_the_engine_limit(self) -> None:
        upper_bounds = [
            int(value)
            for value in re.findall(r"\{\d+,(\d+)\}", self.sql)
        ]
        self.assertTrue(upper_bounds)
        self.assertTrue(all(value <= 255 for value in upper_bounds))

    def test_all_declared_tenant_id_tables_participate_in_boundary(self) -> None:
        table_definitions = re.findall(
            r"create\s+table\s+(?:public\.)?(\w+)\s*\((.*?)\);",
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
        role_sql = (
            ROOT / "database" / "provision_cluster_roles.sql"
        ).read_text(encoding="utf-8").lower()
        for role in (
            "laboratory_owner",
            "laboratory_app",
            "laboratory_outbox_worker",
            "laboratory_outbox_authority",
            "laboratory_outbox_recovery_operator",
            "laboratory_evidence_writer",
            "laboratory_migrator",
        ):
            with self.subTest(role=role):
                self.assertIn(f"('{role}'::name", role_sql)
        self.assertIn(
            "nosuperuser nocreatedb nocreaterole noinherit noreplication nobypassrls",
            role_sql,
        )
        self.assertIn("observed_role.rolsuper", role_sql)
        self.assertIn("observed_role.rolbypassrls", role_sql)
        self.assertRegex(
            role_sql,
            r"grant\s+laboratory_owner\s+to\s+laboratory_migrator\s+"
            r"with\s+admin\s+false,\s+inherit\s+false,\s+set\s+true",
        )
        self.assertRegex(
            role_sql,
            r"grant\s+laboratory_outbox_authority\s+to\s+laboratory_owner\s+"
            r"with\s+admin\s+false,\s+inherit\s+false,\s+set\s+true",
        )
        self.assertIn(
            "alter role laboratory_migrator in database %i set role to laboratory_owner",
            role_sql,
        )
        self.assertIn("grant create on database %i to laboratory_owner", role_sql)
        self.assertIn("revoke create on database %i from public", role_sql)
        self.assertIn(
            "revoke create on database %i from laboratory_migrator",
            role_sql,
        )
        self.assertIn("revoke create on schema public from public", role_sql)
        self.assertIn("alter schema public owner to laboratory_owner", role_sql)
        self.assertIn("revoke all on schema public from laboratory_migrator", role_sql)
        self.assertNotRegex(self.sql, r"\bcreate\s+role\b")
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
            ROOT / "sql" / "V004__outbox_attempt_evidence_and_recovery.sql"
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
            ROOT / "sql" / "V004__outbox_attempt_evidence_and_recovery.sql"
        ).read_text(encoding="utf-8").lower()
        self.assertIn("set local lock_timeout = '30s';", migration)
        self.assertIn("set local statement_timeout = '5min';", migration)
        self.assertIn(
            "set local idle_in_transaction_session_timeout = '5min';",
            migration,
        )
        lock_statement = "lock table\n    public.custody_event,"
        self.assertEqual(migration.count(lock_statement), 1)
        self.assertIn("public.transactional_outbox\nin access exclusive mode;", migration)
        self.assertLess(
            migration.index(lock_statement),
            migration.index("do $migration_preflight$"),
        )

    def test_outbox_attempt_outcome_and_recovery_evidence_are_append_only(self) -> None:
        migration = (
            ROOT / "sql" / "V004__outbox_attempt_evidence_and_recovery.sql"
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
            ROOT / "sql" / "V004__outbox_attempt_evidence_and_recovery.sql"
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

    def test_measurement_scale_and_complete_inbox_lineage_are_database_bound(self) -> None:
        migration = (
            ROOT / "sql" / "V004__outbox_attempt_evidence_and_recovery.sql"
        ).read_text(encoding="utf-8").lower()
        self.assertIn("instrument_measurement_source_scale_coherent", migration)
        self.assertIn("source_scale = pg_catalog.scale(quantity)", migration)
        self.assertIn("instrument_measurement_complete_inbox_lineage_fk", migration)
        for field in (
            "tenant_id",
            "message_id",
            "specimen_id",
            "raw_sha256",
            "captured_at_utc",
            "source_disposition",
        ):
            self.assertIn(field, migration)
        self.assertIn("source_disposition in ('accepted', 'replayed')", migration)
        self.assertIn("instrument_inbox_append_only", migration)
        self.assertIn("revoke update on public.instrument_inbox", migration)

    def test_custody_position_binds_the_complete_source_event_coordinate(self) -> None:
        migration = (
            ROOT / "sql" / "V004__outbox_attempt_evidence_and_recovery.sql"
        ).read_text(encoding="utf-8").lower()
        self.assertIn("custody_event_position_binding_key", migration)
        self.assertIn("custody_position_complete_event_fk", migration)
        self.assertIn(
            "tenant_id,\n            specimen_id,\n            custody_version,\n            last_transfer_id",
            migration,
        )
        self.assertIn(
            "tenant_id,\n            specimen_id,\n            resulting_version,\n            transfer_id",
            migration,
        )

    def test_published_migrations_remain_immutable_and_005_is_successor(self) -> None:
        migration_003 = ROOT / "sql" / "V003__trusted_routines_and_outbox_cas.sql"
        self.assertEqual(
            hashlib.sha256(migration_003.read_bytes()).hexdigest(),
            "13925ea70a930ef69240de8e0ffe56e5cb4479fb64e48cf41e6051dc8eb66a70",
        )
        migrations = sorted((ROOT / "sql").glob("V*__*.sql"))
        self.assertEqual(
            [path.name.split("__", 1)[0] for path in migrations],
            ["V001", "V002", "V003", "V004", "V005"],
        )

    def test_workbench_reuses_canonical_measurement_and_custody_truth(self) -> None:
        migration = (
            ROOT / "sql" / "V005__golden_specimen_workbench.sql"
        ).read_text(encoding="utf-8").lower()
        self.assertNotIn("create table public.custody_event", migration)
        self.assertNotIn("create table public.instrument_measurement", migration)
        self.assertIn("create view public.normalized_observation", migration)
        self.assertIn("from public.instrument_measurement as measurement", migration)
        self.assertIn("with (security_invoker = true, security_barrier = true)", migration)

    def test_workbench_resolution_binds_source_replacement_and_specimen(self) -> None:
        migration = (
            ROOT / "sql" / "V005__golden_specimen_workbench.sql"
        ).read_text(encoding="utf-8").lower()
        for fragment in (
            "instrument_inbox_specimen_fk",
            "instrument_inbox_review_lineage_key",
            "quarantine_disposition = 'quarantined'",
            "replacement_disposition in ('accepted', 'replayed')",
            "replacement_message_id <> quarantine_message_id",
            "instrument_review_resolution_append_only",
            "laboratory_security.authorized_tenant_id()",
            "laboratory_security.bounded_migration_session_active()",
            "set search_path = pg_catalog, pg_temp",
            "for key share",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, migration)
        self.assertIn(
            "replacement_inbox.specimen_id <> original_inbox.specimen_id",
            migration,
        )
        self.assertNotIn("current_setting('app.tenant_id'", migration)

    def test_workbench_view_definition_closes_temporary_outbox_authority(self) -> None:
        migration = (
            ROOT / "sql" / "V005__golden_specimen_workbench.sql"
        ).read_text(encoding="utf-8").lower()
        self.assertIn("set local role laboratory_outbox_authority", migration)
        grant = "grant select on public.transactional_outbox to laboratory_owner"
        revoke = "revoke select on public.transactional_outbox from laboratory_owner"
        self.assertEqual(migration.count(grant), 1)
        self.assertEqual(migration.count(revoke), 1)
        self.assertLess(migration.index(grant), migration.index(revoke))
        self.assertNotIn(
            "grant select on public.transactional_outbox to laboratory_app",
            migration,
        )

    def test_security_definer_data_objects_are_schema_qualified(self) -> None:
        migration = (ROOT / "sql" / "V003__trusted_routines_and_outbox_cas.sql").read_text(
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
        role_provisioner = compose.split("\n  database-role-provisioner:", 1)[1]
        role_provisioner = role_provisioner.split("\n  database-migrator:", 1)[0]
        self.assertIn("PGUSER: laboratory_bootstrap", role_provisioner)
        self.assertIn("postgres_password", role_provisioner)
        self.assertIn("postgres_migrator_password", role_provisioner)
        provisioner_script = (
            ROOT / "infra" / "provision-migrator-identity.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("pg_catalog.pg_db_role_setting", provisioner_script)
        self.assertIn(
            'test "$database_role_setting" = "role=laboratory_owner"',
            provisioner_script,
        )
        self.assertIn(
            'test "$startup_identity" = '
            '"laboratory_migrator:laboratory_owner:laboratory_owner"',
            provisioner_script,
        )
        migrator = compose.split("\n  database-migrator:", 1)[1]
        migrator = migrator.split("\n  database-role-bootstrap:", 1)[0]
        self.assertIn("FLYWAY_USER: laboratory_migrator", migrator)
        self.assertIn(
            "FLYWAY_URL: jdbc:postgresql://postgres:5432/laboratory",
            migrator,
        )
        self.assertNotIn("options=-c%20role%3D", migrator)
        self.assertIn("postgres_migrator_password", migrator)
        self.assertNotIn("- postgres_password\n", migrator)
        images = re.findall(r"^\s+image:\s+(\S+)$", compose, flags=re.MULTILINE)
        self.assertGreaterEqual(len(images), 6)
        for image in images:
            with self.subTest(image=image):
                self.assertRegex(image, r"@sha256:[a-f0-9]{64}$")

    def test_secret_and_container_context_exclusions_are_explicit(self) -> None:
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("infra/secrets/*", gitignore)
        self.assertIn("infra/secrets/*.txt", gitignore)
        self.assertIn("!infra/secrets/.gitignore", gitignore)

        dockerignore = (ROOT / ".dockerignore").read_text(
            encoding="utf-8"
        ).splitlines()
        for protected_path in (
            ".git",
            ".env",
            ".env.*",
            ".venv",
            "**/__pycache__",
            "infra/secrets",
            "receipts/local",
        ):
            with self.subTest(protected_path=protected_path):
                self.assertIn(protected_path, dockerignore)


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
