"""Configured PostgreSQL proofs for canonical data and the thin outbox."""

from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from uuid import uuid4

ADMIN_DSN = os.environ.get("LIMS_TEST_POSTGRES_ADMIN_DSN")
APP_DSN = os.environ.get("LIMS_TEST_POSTGRES_APP_DSN")


@unittest.skipUnless(
    ADMIN_DSN and APP_DSN and shutil.which("psql"),
    "configured PostgreSQL DSNs and psql enable this proof",
)
class PostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def run_sql(
        cls,
        dsn: str,
        sql: str,
        *,
        variables: dict[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            shutil.which("psql") or "psql",
            dsn,
            "--no-psqlrc",
            "--no-align",
            "--tuples-only",
            "--quiet",
            "--set",
            "ON_ERROR_STOP=1",
        ]
        for name, value in sorted((variables or {}).items()):
            command.extend(("--set", f"{name}={value}"))
        completed = subprocess.run(
            command,
            input=sql,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if check and completed.returncode != 0:
            raise AssertionError(
                "PostgreSQL proof statement failed\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )
        return completed

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        suffix = uuid4().hex[:10].upper()
        cls.tenant_a = f"SYN-LIVE-A-{suffix}"
        cls.tenant_b = f"SYN-LIVE-B-{suffix}"
        cls.specimen_a = f"SYN-LIVE-SPECIMEN-A-{suffix}"
        cls.specimen_b = f"SYN-LIVE-SPECIMEN-B-{suffix}"
        assert ADMIN_DSN is not None
        cls.run_sql(
            ADMIN_DSN,
            """
            insert into public.tenant (tenant_id, display_name)
            values (:'tenant_a', 'Synthetic tenant A'),
                   (:'tenant_b', 'Synthetic tenant B');
            insert into public.specimen (
                tenant_id, specimen_id, lifecycle_state, aggregate_version,
                canonical_document, canonical_sha256, updated_at_utc
            ) values
                (:'tenant_a', :'specimen_a', 'registered', 1, '{}'::jsonb,
                 repeat('a', 64), clock_timestamp()),
                (:'tenant_b', :'specimen_b', 'registered', 1, '{}'::jsonb,
                 repeat('b', 64), clock_timestamp());
            """,
            variables={
                "tenant_a": cls.tenant_a,
                "tenant_b": cls.tenant_b,
                "specimen_a": cls.specimen_a,
                "specimen_b": cls.specimen_b,
            },
        )

    def app_sql(
        self,
        tenant_id: str,
        statement: str,
        *,
        variables: dict[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        assert APP_DSN is not None
        return self.run_sql(
            APP_DSN,
            "begin; select set_config('app.tenant_id', :'tenant', true); "
            + statement
            + "; commit;",
            variables={"tenant": tenant_id, **(variables or {})},
            check=check,
        )

    def test_transaction_local_tenant_scope_filters_rows(self) -> None:
        result = self.app_sql(
            self.tenant_a,
            "select string_agg(tenant_id, ',') from public.tenant",
        )
        self.assertIn(self.tenant_a, result.stdout)
        self.assertNotIn(self.tenant_b, result.stdout)

    def test_custody_event_and_outbox_insert_commit_atomically(self) -> None:
        transfer = "SYN-LIVE-TRANSFER-" + uuid4().hex
        result = self.app_sql(
            self.tenant_a,
            """
            select (public.record_custody_transfer(
                :'specimen', 'SYN-LAB-A/RECEIVING', 'SYN-CUSTODIAN-01',
                0, :'transfer', '2026-08-04T12:00:00Z'
            )).custody_version;
            select
                (select count(*) from public.custody_event
                  where tenant_id = :'tenant' and transfer_id = :'transfer')::text
                || ':' ||
                (select count(*) from public.transactional_outbox
                  where tenant_id = :'tenant' and message_id = :'transfer')::text
            """,
            variables={"specimen": self.specimen_a, "transfer": transfer},
        )
        self.assertIn("1:1", result.stdout)

    def test_transaction_failure_rolls_back_custody_and_outbox_together(self) -> None:
        transfer = "SYN-LIVE-ROLLBACK-" + uuid4().hex
        failed = self.app_sql(
            self.tenant_a,
            """
            select public.record_custody_transfer(
                :'specimen', 'SYN-LAB-A/QUARANTINE', 'SYN-CUSTODIAN-01',
                1, :'transfer', '2026-08-04T12:05:00Z'
            );
            select 1 / 0
            """,
            variables={"specimen": self.specimen_a, "transfer": transfer},
            check=False,
        )
        self.assertNotEqual(failed.returncode, 0)
        assert ADMIN_DSN is not None
        counts = self.run_sql(
            ADMIN_DSN,
            """
            select
                (select count(*) from public.custody_event
                  where tenant_id = :'tenant' and transfer_id = :'transfer')::text
                || ':' ||
                (select count(*) from public.transactional_outbox
                  where tenant_id = :'tenant' and message_id = :'transfer')::text
            """,
            variables={"tenant": self.tenant_a, "transfer": transfer},
        )
        self.assertEqual(counts.stdout.strip(), "0:0")

    def test_application_cannot_update_or_delete_outbox_rows(self) -> None:
        update = self.app_sql(
            self.tenant_a,
            "update public.transactional_outbox set topic = 'changed'",
            check=False,
        )
        delete = self.app_sql(
            self.tenant_a,
            "delete from public.transactional_outbox",
            check=False,
        )
        self.assertNotEqual(update.returncode, 0)
        self.assertNotEqual(delete.returncode, 0)
        self.assertIn("permission denied", update.stderr.lower())
        self.assertIn("permission denied", delete.stderr.lower())

    def test_quarantined_runtime_tables_are_absent(self) -> None:
        assert ADMIN_DSN is not None
        result = self.run_sql(
            ADMIN_DSN,
            """
            select count(*)
              from pg_catalog.pg_class
             where oid in (
                pg_catalog.to_regclass('public.bounded_call_invocation'),
                pg_catalog.to_regclass('public.acceptance_decision'),
                pg_catalog.to_regclass('public.evidence_receipt'),
                pg_catalog.to_regclass('public.outbox_recovery_release')
             )
            """,
        )
        self.assertEqual(result.stdout.strip(), "0")

    def test_catalog_exposes_only_the_thin_outbox_contract(self) -> None:
        assert ADMIN_DSN is not None
        result = self.run_sql(
            ADMIN_DSN,
            """
            select pg_catalog.string_agg(attribute.attname, ',' order by attribute.attnum)
              from pg_catalog.pg_attribute as attribute
             where attribute.attrelid = 'public.transactional_outbox'::regclass
               and attribute.attnum > 0
               and not attribute.attisdropped
            """,
        )
        self.assertEqual(
            result.stdout.strip(),
            "tenant_id,message_id,topic,aggregate_id,aggregate_version,payload,"
            "payload_sha256,payload_canonicalization,created_at_utc",
        )

        functions = self.run_sql(
            ADMIN_DSN,
            """
            select count(*)
              from pg_catalog.pg_proc
             where pronamespace = 'public'::regnamespace
               and proname in (
                   'claim_outbox_delivery', 'reclaim_outbox_delivery',
                   'confirm_outbox_delivery', 'fail_outbox_delivery',
                   'release_outbox_recovery'
               )
            """,
        )
        self.assertEqual(functions.stdout.strip(), "0")

        posture = self.run_sql(
            ADMIN_DSN,
            """
            select tableowner || ':' ||
                   pg_catalog.has_table_privilege(
                       'laboratory_outbox_worker',
                       'public.transactional_outbox', 'select'
                   )::text || ':' ||
                   pg_catalog.has_table_privilege(
                       'laboratory_outbox_worker',
                       'public.transactional_outbox', 'update'
                   )::text || ':' ||
                   pg_catalog.has_table_privilege(
                       'laboratory_outbox_authority',
                       'public.transactional_outbox', 'select'
                   )::text
              from pg_catalog.pg_tables
             where schemaname = 'public'
               and tablename = 'transactional_outbox'
            """,
        )
        self.assertEqual(
            posture.stdout.strip(),
            "laboratory_outbox_authority:true:false:true",
        )

        simplified_security = self.run_sql(
            ADMIN_DSN,
            """
            select
                (select count(*)
                   from pg_catalog.pg_proc
                  where pronamespace = 'laboratory_security'::regnamespace
                    and proname in (
                        'bind_tenant_context',
                        'bounded_migration_session_active',
                        'constant_time_equal'
                    ))::text
                || ':' ||
                (select count(*)
                   from pg_catalog.pg_policies
                  where schemaname = 'public'
                    and tablename = 'transactional_outbox'
                    and policyname = 'outbox_connector_read_policy')::text
            """,
        )
        self.assertEqual(simplified_security.stdout.strip(), "0:1")

    def test_catalog_uses_enterprise_data_primitives(self) -> None:
        assert ADMIN_DSN is not None
        result = self.run_sql(
            ADMIN_DSN,
            """
            select pg_catalog.string_agg(
                column_name || ':' || data_type,
                ',' order by column_name
            )
              from information_schema.columns
             where table_schema = 'public'
               and (
                   (table_name = 'specimen' and column_name = 'updated_at_utc')
                   or (table_name = 'instrument_measurement' and column_name = 'quantity')
                   or (table_name = 'specimen_event' and column_name = 'event_id')
                   or (table_name = 'specimen' and column_name = 'canonical_document')
               )
            """,
        )
        self.assertEqual(
            result.stdout.strip(),
            "canonical_document:jsonb,event_id:uuid,quantity:numeric,"
            "updated_at_utc:timestamp with time zone",
        )


if __name__ == "__main__":
    unittest.main()
