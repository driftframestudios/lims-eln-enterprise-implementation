"""Configured PostgreSQL proofs for tenant, custody, and outbox invariants."""

from __future__ import annotations

import hmac
import json
import os
import shutil
import subprocess
import time
import unittest
from base64 import b64encode
from collections.abc import Callable
from datetime import datetime, timedelta
from hashlib import sha256
from importlib.util import find_spec
from uuid import uuid4

from fastapi.testclient import TestClient

from lims_eln_implementation.security import (
    PostgresTenantBinding,
    SignedTenantContext,
    tenant_context_signing_message,
)
from lims_eln_implementation.workbench.api import create_app
from lims_eln_implementation.workbench.postgres import (
    PostgresWorkbenchService,
    _operation_contract,
)
from lims_eln_implementation.workbench.service import ObservationAbsent, SpecimenAbsent

try:
    import psycopg
except ModuleNotFoundError:  # pragma: no cover - exercised by the configured job
    psycopg = None


ADMIN_DSN = os.environ.get("LIMS_TEST_POSTGRES_ADMIN_DSN")
APP_DSN = os.environ.get("LIMS_TEST_POSTGRES_APP_DSN")
OUTBOX_DSN = os.environ.get("LIMS_TEST_POSTGRES_OUTBOX_DSN")
RECOVERY_DSN = os.environ.get("LIMS_TEST_POSTGRES_RECOVERY_DSN")
MIGRATOR_DSN = os.environ.get("LIMS_TEST_POSTGRES_MIGRATOR_DSN")
HMAC_KEY_HEX = os.environ.get("LIMS_TEST_TENANT_HMAC_HEX")
UPGRADE_OUTBOX_DSN = os.environ.get("LIMS_TEST_POSTGRES_UPGRADE_OUTBOX_DSN")
UPGRADE_RECOVERY_DSN = os.environ.get("LIMS_TEST_POSTGRES_UPGRADE_RECOVERY_DSN")
UPGRADE_TENANT = "SYN-UPGRADE-TENANT"


def signed_context(
    tenant_id: str,
    *,
    issued_offset_seconds: int = 0,
    expires_offset_seconds: int = 300,
    signature_tenant_id: str | None = None,
    subject_id: str = "SYN-CI-SERVICE-IDENTITY",
) -> str:
    if HMAC_KEY_HEX is None:
        raise RuntimeError("integration context requires the configured synthetic key")
    issued_at = int(time.time()) + issued_offset_seconds
    expires_at = issued_at + expires_offset_seconds
    key_id = "synthetic-ci-v1"
    nonce = "SYNTHETIC-CI-NONCE-" + uuid4().hex
    signed_tenant = signature_tenant_id or tenant_id
    content = tenant_context_signing_message(
        tenant_id=signed_tenant,
        subject_id=subject_id,
        key_id=key_id,
        issued_at_epoch=issued_at,
        expires_at_epoch=expires_at,
        nonce=nonce,
    )
    signature = hmac.new(
        bytes.fromhex(HMAC_KEY_HEX),
        content,
        sha256,
    ).hexdigest()
    return json.dumps(
        {
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "key_id": key_id,
            "issued_at_epoch": issued_at,
            "expires_at_epoch": expires_at,
            "nonce": nonce,
            "signature_hex": signature,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


@unittest.skipUnless(
    ADMIN_DSN
    and APP_DSN
    and OUTBOX_DSN
    and RECOVERY_DSN
    and MIGRATOR_DSN
    and HMAC_KEY_HEX
    and shutil.which("psql"),
    "configured PostgreSQL DSNs, synthetic HMAC key, and psql enable this proof",
)
class PostgresDataBoundaryIntegrationTests(unittest.TestCase):
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
        cls.outbox_tenant = f"SYN-LIVE-OUTBOX-{suffix}"
        cls.specimen = f"SYN-LIVE-SPECIMEN-{suffix}"
        cls.shadow_specimen = f"SYN-LIVE-SHADOW-SPECIMEN-{suffix}"
        assert ADMIN_DSN is not None
        cls.run_sql(
            ADMIN_DSN,
            """
            insert into tenant (tenant_id, display_name)
            values (:'tenant_a', 'Synthetic live tenant A'),
                   (:'tenant_b', 'Synthetic live tenant B'),
                   (:'outbox_tenant', 'Synthetic live outbox tenant');
            insert into specimen (
                tenant_id, specimen_id, lifecycle_state, aggregate_version,
                canonical_document, canonical_sha256, updated_at_utc
            ) values
                (:'tenant_a', :'specimen', 'registered', 1, '{}'::jsonb,
                 repeat('0', 64), clock_timestamp()),
                (:'tenant_a', :'shadow_specimen', 'registered', 1, '{}'::jsonb,
                 repeat('0', 64), clock_timestamp()),
                (:'tenant_b', :'specimen', 'registered', 1, '{}'::jsonb,
                 repeat('0', 64), clock_timestamp());
            """,
            variables={
                "tenant_a": cls.tenant_a,
                "tenant_b": cls.tenant_b,
                "outbox_tenant": cls.outbox_tenant,
                "specimen": cls.specimen,
                "shadow_specimen": cls.shadow_specimen,
            },
        )

    def app_transaction(self, context: str, statement: str) -> str:
        assert APP_DSN is not None
        completed = self.run_sql(
            APP_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            + statement
            + "; commit;",
            variables={"context": context},
        )
        return completed.stdout

    @staticmethod
    def last_output_row(completed: subprocess.CompletedProcess[str]) -> str:
        rows = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        if not rows:
            raise AssertionError("PostgreSQL proof requires one result row")
        return rows[-1]

    def test_signed_context_is_the_effective_tenant_authority(self) -> None:
        context_a = signed_context(self.tenant_a)
        output = self.app_transaction(
            context_a,
            "select string_agg(tenant_id, ',') from tenant",
        )
        self.assertIn(self.tenant_a, output)
        self.assertNotIn(self.tenant_b, output)

        output_with_legacy_guc = self.app_transaction(
            context_a,
            "set local app.tenant_id = '" + self.tenant_b + "'; "
            "select string_agg(tenant_id, ',') from tenant",
        )
        self.assertIn(self.tenant_a, output_with_legacy_guc)
        self.assertNotIn(self.tenant_b, output_with_legacy_guc)

    def test_tampered_expired_and_unsigned_contexts_fail_closed(self) -> None:
        assert APP_DSN is not None
        tampered = signed_context(
            self.tenant_b,
            signature_tenant_id=self.tenant_a,
        )
        expired = signed_context(
            self.tenant_a,
            issued_offset_seconds=-600,
            expires_offset_seconds=300,
        )
        for label, sql, variables in (
            (
                "tampered",
                "select laboratory_security.bind_tenant_context(:'context'::jsonb)",
                {"context": tampered},
            ),
            (
                "expired",
                "select laboratory_security.bind_tenant_context(:'context'::jsonb)",
                {"context": expired},
            ),
            (
                "unsigned",
                (
                    "begin; select set_config('app.tenant_id', :'tenant', true); "
                    "select count(*) from tenant; commit;"
                ),
                {"tenant": self.tenant_a},
            ),
        ):
            with self.subTest(label=label):
                completed = self.run_sql(
                    APP_DSN,
                    sql,
                    variables=variables,
                    check=False,
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("tenant context", completed.stderr.lower())

    def test_application_identity_cannot_read_verification_keys(self) -> None:
        assert APP_DSN is not None
        completed = self.run_sql(
            APP_DSN,
            "select count(*) from laboratory_security.tenant_context_key",
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("permission denied", completed.stderr.lower())

    def test_bounded_migration_policy_is_scoped_to_the_migration_session(self) -> None:
        assert APP_DSN is not None and MIGRATOR_DSN is not None
        application_probe = self.run_sql(
            APP_DSN,
            "select laboratory_security.bounded_migration_session_active()",
            check=False,
        )
        self.assertNotEqual(application_probe.returncode, 0)
        self.assertIn("permission denied", application_probe.stderr.lower())

        migration_identity = self.run_sql(
            MIGRATOR_DSN,
            "select session_user || ':' || current_user || ':' || "
            "current_setting('role') || ':' || "
            "laboratory_security.bounded_migration_session_active()::text",
        ).stdout.strip()
        self.assertEqual(
            migration_identity,
            "laboratory_migrator:laboratory_owner:laboratory_owner:true",
        )
        migration_visible_rows = int(
            self.run_sql(
                MIGRATOR_DSN,
                "select count(*) from public.tenant",
            ).stdout.strip()
        )
        self.assertGreaterEqual(migration_visible_rows, 3)

        security_definer_probe = self.run_sql(
            APP_DSN,
            "select public.record_custody_transfer("
            "'SYN-DENIED-SPECIMEN', 'SYN-DENIED-LOCATION', "
            "'SYN-DENIED-CUSTODIAN', 0, 'SYN-DENIED-TRANSFER', "
            "clock_timestamp())",
            check=False,
        )
        self.assertNotEqual(security_definer_probe.returncode, 0)
        self.assertIn("tenant context", security_definer_probe.stderr.lower())

        direct_login_identity = self.run_sql(
            MIGRATOR_DSN,
            "set role none; select session_user || ':' || current_user || ':' || "
            "current_setting('role')",
        ).stdout.strip()
        self.assertEqual(
            direct_login_identity,
            "laboratory_migrator:laboratory_migrator:none",
        )
        direct_login_read = self.run_sql(
            MIGRATOR_DSN,
            "set role none; select count(*) from public.tenant",
            check=False,
        )
        self.assertNotEqual(direct_login_read.returncode, 0)
        self.assertIn("tenant context", direct_login_read.stderr.lower())

    def test_scientific_quantity_retains_exact_scale_and_rejects_over_scale(self) -> None:
        assert APP_DSN is not None
        message_id = "SYN-LIVE-MEASUREMENT-MESSAGE-" + uuid4().hex
        measurement_id = "SYN-LIVE-MEASUREMENT-" + uuid4().hex
        variables = {
            "context": signed_context(self.tenant_a),
            "measurement": measurement_id,
            "message": message_id,
            "specimen": self.specimen,
            "tenant": self.tenant_a,
        }
        accepted = self.run_sql(
            APP_DSN,
            """
            begin;
            select laboratory_security.bind_tenant_context(:'context'::jsonb);
            insert into instrument_inbox (
                tenant_id, message_id, instrument_id, specimen_id,
                raw_object_key, raw_sha256, captured_at_utc, disposition,
                reason_code, recovery_instruction
            ) values (
                :'tenant', :'message', 'SYN-INSTRUMENT-01', :'specimen',
                'synthetic/measurement.json', repeat('1', 64),
                '2026-08-04T12:00:00Z', 'accepted', null,
                'projection completed'
            );
            insert into instrument_measurement (
                tenant_id, measurement_id, message_id, specimen_id,
                analyte_code, quantity, source_precision, source_scale,
                unit_code, unit_system, captured_at_utc,
                raw_sha256, normalized_sha256, source_disposition
            ) values (
                :'tenant', :'measurement', :'message', :'specimen',
                'DNA_CONCENTRATION', 12.123456789012345678, 20, 18,
                'ng/uL', 'http://unitsofmeasure.org',
                '2026-08-04T12:00:00Z', repeat('1', 64), repeat('2', 64),
                'accepted'
            );
            select quantity::text || ':' || source_scale::text
              from instrument_measurement
             where tenant_id = :'tenant'
               and measurement_id = :'measurement';
            commit;
            """,
            variables=variables,
        )
        self.assertIn("12.123456789012345678:18", accepted.stdout)

        over_scale = self.run_sql(
            APP_DSN,
            """
            begin;
            select laboratory_security.bind_tenant_context(:'context'::jsonb);
            insert into instrument_measurement (
                tenant_id, measurement_id, message_id, specimen_id,
                analyte_code, quantity, source_precision, source_scale,
                unit_code, unit_system, captured_at_utc,
                raw_sha256, normalized_sha256, source_disposition
            ) values (
                :'tenant', :'measurement', :'message', :'specimen',
                'DNA_COPIES', 0.1234567890123456789, 20, 18,
                '{copies}/uL', 'http://unitsofmeasure.org',
                '2026-08-04T12:00:00Z', repeat('1', 64), repeat('3', 64),
                'accepted'
            );
            commit;
            """,
            variables={
                "context": signed_context(self.tenant_a),
                "measurement": "SYN-LIVE-OVER-SCALE-" + uuid4().hex,
                "message": message_id,
                "specimen": self.specimen,
                "tenant": self.tenant_a,
            },
            check=False,
        )
        self.assertNotEqual(over_scale.returncode, 0)
        self.assertIn("instrument_measurement_quantity_check", over_scale.stderr)

        for label, quantity, source_scale, raw_sha256, captured_at, disposition in (
            (
                "stored-scale",
                "12.340",
                "2",
                "1" * 64,
                "2026-08-04T12:00:00Z",
                "accepted",
            ),
            (
                "raw-object-lineage",
                "12.34",
                "2",
                "9" * 64,
                "2026-08-04T12:00:00Z",
                "accepted",
            ),
            (
                "capture-time-lineage",
                "12.34",
                "2",
                "1" * 64,
                "2026-08-04T12:00:01Z",
                "accepted",
            ),
            (
                "disposition-lineage",
                "12.34",
                "2",
                "1" * 64,
                "2026-08-04T12:00:00Z",
                "replayed",
            ),
        ):
            with self.subTest(label=label):
                rejected = self.run_sql(
                    APP_DSN,
                    """
                    begin;
                    select laboratory_security.bind_tenant_context(:'context'::jsonb);
                    insert into instrument_measurement (
                        tenant_id, measurement_id, message_id, specimen_id,
                        analyte_code, quantity, source_precision, source_scale,
                        unit_code, unit_system, captured_at_utc,
                        raw_sha256, normalized_sha256, source_disposition
                    ) values (
                        :'tenant', :'measurement', :'message', :'specimen',
                        'DNA_LINEAGE_PROBE', :'quantity'::numeric, 8,
                        :'source_scale'::smallint,
                        'ng/uL', 'http://unitsofmeasure.org',
                        :'captured_at'::timestamptz, :'raw_sha256',
                        repeat('8', 64), :'disposition'
                    );
                    commit;
                    """,
                    variables={
                        "context": signed_context(self.tenant_a),
                        "measurement": "SYN-LIVE-LINEAGE-" + uuid4().hex,
                        "message": message_id,
                        "specimen": self.specimen,
                        "tenant": self.tenant_a,
                        "quantity": quantity,
                        "source_scale": source_scale,
                        "raw_sha256": raw_sha256,
                        "captured_at": captured_at,
                        "disposition": disposition,
                    },
                    check=False,
                )
                self.assertNotEqual(rejected.returncode, 0)
                self.assertTrue(
                    "instrument_measurement_source_scale_coherent" in rejected.stderr
                    or "instrument_measurement_complete_inbox_lineage_fk" in rejected.stderr
                )

    def test_workbench_resolution_and_views_reuse_canonical_instrument_facts(self) -> None:
        assert APP_DSN is not None
        quarantine_message = "SYN-LIVE-QUARANTINE-" + uuid4().hex
        replacement_message = "SYN-LIVE-REPLACEMENT-" + uuid4().hex
        measurement_id = "SYN-LIVE-WORKBENCH-MEASUREMENT-" + uuid4().hex
        resolution_id = "SYN-LIVE-RESOLUTION-" + uuid4().hex
        completed = self.run_sql(
            APP_DSN,
            """
            begin;
            select laboratory_security.bind_tenant_context(:'context'::jsonb);
            insert into public.instrument_inbox (
                tenant_id, message_id, instrument_id, specimen_id,
                raw_object_key, raw_sha256, captured_at_utc, disposition,
                reason_code, recovery_instruction
            ) values
                (:'tenant', :'quarantine', 'SYN-INSTRUMENT-01', :'specimen',
                 'synthetic/quarantine.json', repeat('3', 64),
                 '2026-08-04T13:00:00Z', 'quarantined',
                 'analyte_requires_mapping', 'supply an approved analyte code'),
                (:'tenant', :'replacement', 'SYN-INSTRUMENT-01', :'specimen',
                 'synthetic/replacement.json', repeat('4', 64),
                 '2026-08-04T13:01:00Z', 'accepted', null,
                 'continue to scientific review');
            insert into public.instrument_measurement (
                tenant_id, measurement_id, message_id, specimen_id,
                analyte_code, quantity, source_precision, source_scale,
                unit_code, unit_system, captured_at_utc, raw_sha256,
                normalized_sha256, source_disposition
            ) values (
                :'tenant', :'measurement', :'replacement', :'specimen',
                'SYNTHETIC-DNA', 12.50, 4, 2, 'ng/uL',
                'http://unitsofmeasure.org', '2026-08-04T13:01:00Z',
                repeat('4', 64), repeat('5', 64), 'accepted'
            );
            select (public.record_instrument_review_resolution(
                :'quarantine', :'resolution', 'accepted_replacement',
                :'replacement', 'SYN-QUALITY-01',
                'replacement evidence passed scientific review',
                '2026-08-04T13:02:00Z'
            )).disposition;
            select latest_observed_value_text || ':' ||
                   open_instrument_review_count::text || ':' ||
                   quarantine_history_count::text
              from public.specimen_workbench_snapshot
             where specimen_id = :'specimen';
            commit;
            """,
            variables={
                "context": signed_context(self.tenant_a),
                "tenant": self.tenant_a,
                "specimen": self.specimen,
                "quarantine": quarantine_message,
                "replacement": replacement_message,
                "measurement": measurement_id,
                "resolution": resolution_id,
            },
        )
        self.assertIn("accepted_replacement", completed.stdout)
        self.assertIn("12.50:0:1", completed.stdout)

        assert ADMIN_DSN is not None
        mutation = self.run_sql(
            ADMIN_DSN,
            "update public.instrument_review_resolution set rationale = 'changed' "
            "where resolution_id = :'resolution'",
            variables={"resolution": resolution_id},
            check=False,
        )
        self.assertNotEqual(mutation.returncode, 0)
        self.assertIn("append-only", mutation.stderr.lower())

        missing_specimen = self.run_sql(
            APP_DSN,
            "begin; select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "insert into public.instrument_inbox (tenant_id, message_id, "
            "instrument_id, specimen_id, raw_object_key, raw_sha256, "
            "captured_at_utc, disposition, reason_code, recovery_instruction) "
            "values (:'tenant', :'message', 'SYN-INSTRUMENT-01', "
            "'SYN-ABSENT-SPECIMEN', 'synthetic/absent.json', repeat('6', 64), "
            "clock_timestamp(), 'quarantined', 'source_missing', "
            "'register the specimen identity'); commit;",
            variables={
                "context": signed_context(self.tenant_a),
                "tenant": self.tenant_a,
                "message": "SYN-LIVE-MISSING-SPECIMEN-" + uuid4().hex,
            },
            check=False,
        )
        self.assertNotEqual(missing_specimen.returncode, 0)
        self.assertIn("instrument_inbox_specimen_fk", missing_specimen.stderr)

    def test_custody_compare_and_set_history_replay_and_outbox_are_atomic(self) -> None:
        assert APP_DSN is not None
        context = signed_context(self.tenant_a)
        transfer_id = "SYN-LIVE-TRANSFER-" + uuid4().hex
        variables = {
            "context": context,
            "specimen": self.specimen,
            "transfer": transfer_id,
        }
        transfer_sql = """
            begin;
            select laboratory_security.bind_tenant_context(:'context'::jsonb);
            select custody_version
              from record_custody_transfer(
                  :'specimen', 'SYN-FREEZER-A', 'SYN-CUSTODIAN-01',
                  0, :'transfer', '2026-08-04T12:00:00Z'
              );
            commit;
        """
        first = self.run_sql(APP_DSN, transfer_sql, variables=variables)
        replay = self.run_sql(APP_DSN, transfer_sql, variables=variables)
        self.assertIn("1", first.stdout)
        self.assertIn("1", replay.stdout)
        evidence = self.app_transaction(
            signed_context(self.tenant_a),
            "select (select count(*) from custody_event where transfer_id = '"
            + transfer_id
            + "')::text || ':' || "
            "(select count(*) from transactional_outbox where message_id = '"
            + transfer_id
            + "')::text",
        )
        self.assertIn("1:1", evidence)

        stale_variables = dict(variables)
        stale_variables["transfer"] = "SYN-LIVE-TRANSFER-" + uuid4().hex
        stale = self.run_sql(
            APP_DSN,
            transfer_sql,
            variables=stale_variables,
            check=False,
        )
        self.assertNotEqual(stale.returncode, 0)
        self.assertIn("custody revision", stale.stderr.lower())

        binding_specimen = "SYN-LIVE-BINDING-SPECIMEN-" + uuid4().hex
        shadow_transfer = "SYN-LIVE-SHADOW-BINDING-" + uuid4().hex
        assert ADMIN_DSN is not None
        self.run_sql(
            ADMIN_DSN,
            """
            insert into public.specimen (
                tenant_id, specimen_id, lifecycle_state, aggregate_version,
                canonical_document, canonical_sha256, updated_at_utc
            ) values (
                :'tenant', :'binding_specimen', 'registered', 1, '{}'::jsonb,
                repeat('0', 64), pg_catalog.clock_timestamp()
            )
            """,
            variables={
                "tenant": self.tenant_a,
                "binding_specimen": binding_specimen,
            },
        )
        self.run_sql(
            APP_DSN,
            transfer_sql,
            variables={
                "context": context,
                "specimen": binding_specimen,
                "transfer": shadow_transfer,
            },
        )
        incoherent_position = self.run_sql(
            ADMIN_DSN,
            "update public.custody_position "
            "set last_transfer_id = :'shadow_transfer' "
            "where tenant_id = :'tenant' and specimen_id = :'specimen'",
            variables={
                "shadow_transfer": shadow_transfer,
                "tenant": self.tenant_a,
                "specimen": self.specimen,
            },
            check=False,
        )
        self.assertNotEqual(incoherent_position.returncode, 0)
        self.assertIn("custody_position_complete_event_fk", incoherent_position.stderr)

    def test_custody_security_definer_ignores_temp_relation_shadows(self) -> None:
        assert APP_DSN is not None
        transfer_id = "SYN-LIVE-TEMP-SHADOW-" + uuid4().hex
        completed = self.run_sql(
            APP_DSN,
            """
            begin;
            select laboratory_security.bind_tenant_context(:'context'::jsonb);
            create temporary table custody_event (marker text);
            create temporary table custody_position (marker text);
            create temporary table transactional_outbox (marker text);
            select custody_version
              from public.record_custody_transfer(
                  :'specimen', 'SYN-FREEZER-SHADOW', 'SYN-CUSTODIAN-SHADOW',
                  0, :'transfer', '2026-08-04T12:30:00Z'
              );
            select (select count(*) from pg_temp.custody_event)::text || ':' ||
                   (select count(*) from pg_temp.custody_position)::text || ':' ||
                   (select count(*) from pg_temp.transactional_outbox)::text;
            commit;
            """,
            variables={
                "context": signed_context(self.tenant_a),
                "specimen": self.shadow_specimen,
                "transfer": transfer_id,
            },
        )
        self.assertEqual(self.last_output_row(completed), "0:0:0")
        evidence = self.app_transaction(
            signed_context(self.tenant_a),
            "select (select count(*) from public.custody_event where transfer_id = '"
            + transfer_id
            + "')::text || ':' || "
            "(select count(*) from public.transactional_outbox where message_id = '"
            + transfer_id
            + "')::text",
        )
        self.assertIn("1:1", evidence)

    def test_outbox_identity_is_tenant_scoped_and_content_is_immutable(self) -> None:
        message_id = "SYN-LIVE-OUTBOX-" + uuid4().hex
        for tenant in (self.tenant_a, self.tenant_b):
            self.app_transaction(
                signed_context(tenant),
                "insert into transactional_outbox ("
                "tenant_id, message_id, topic, aggregate_id, aggregate_version, "
                "payload, payload_sha256) values ('"
                + tenant
                + "', '"
                + message_id
                + "', 'synthetic.changed', 'SYN-AGGREGATE', 1, "
                '\'{"state":"ready"}\'::jsonb, '
                "encode(public.digest(convert_to("
                "'{\"state\":\"ready\"}'::jsonb::text, 'UTF8'), 'sha256'), 'hex'))",
            )

        assert ADMIN_DSN is not None
        context = signed_context(self.tenant_a)
        changed = self.run_sql(
            ADMIN_DSN,
            "begin; select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "set local role laboratory_outbox_authority; "
            "update transactional_outbox "
            'set payload = \'{"state":"changed"}\'::jsonb, '
            "payload_sha256 = encode(public.digest(convert_to("
            "'{\"state\":\"changed\"}'::jsonb::text, 'UTF8'), 'sha256'), 'hex') "
            "where message_id = :'message'; commit;",
            variables={"context": context, "message": message_id},
            check=False,
        )
        self.assertNotEqual(changed.returncode, 0)
        self.assertIn("immutable", changed.stderr.lower())

    def test_outbox_worker_uses_fenced_claim_reclaim_and_confirm(self) -> None:
        assert OUTBOX_DSN is not None
        message_id = "SYN-LIVE-LEASE-" + uuid4().hex
        context = signed_context(self.outbox_tenant)
        self.app_transaction(
            context,
            "insert into public.transactional_outbox ("
            "tenant_id, message_id, topic, aggregate_id, aggregate_version, "
            "payload, payload_sha256) values ('"
            + self.outbox_tenant
            + "', '"
            + message_id
            + "', 'synthetic.delivery', 'SYN-OUTBOX-AGGREGATE', 1, "
            '\'{"state":"ready"}\'::jsonb, '
            "encode(public.digest(convert_to("
            "'{\"state\":\"ready\"}'::jsonb::text, 'UTF8'), 'sha256'), 'hex'))",
        )

        direct_update = self.run_sql(
            OUTBOX_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "update public.transactional_outbox set delivery_attempts = 99 "
            "where tenant_id = :'tenant' and message_id = :'message'; commit;",
            variables={
                "context": context,
                "tenant": self.outbox_tenant,
                "message": message_id,
            },
            check=False,
        )
        self.assertNotEqual(direct_update.returncode, 0)
        self.assertIn("permission denied", direct_update.stderr.lower())

        claimed = self.run_sql(
            OUTBOX_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "select message_id || '|' || lease_owner || '|' || "
            "lease_principal::text || '|' || lease_token::text || '|' || "
            "fencing_token::text "
            "from public.claim_outbox_delivery("
            "'SYN-WORKER-A', 1); commit;",
            variables={"context": context},
        )
        claimed_fields = self.last_output_row(claimed).split("|")
        self.assertEqual(
            claimed_fields[:3], [message_id, "SYN-WORKER-A", "laboratory_outbox_worker"]
        )
        first_token = claimed_fields[3]
        first_fence = int(claimed_fields[4])
        self.assertEqual(first_fence, 1)

        time.sleep(1.1)
        reclaimed = self.run_sql(
            OUTBOX_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "select message_id || '|' || lease_owner || '|' || "
            "lease_principal::text || '|' || lease_token::text || '|' || "
            "fencing_token::text "
            "from public.reclaim_outbox_delivery("
            ":'message', :fence, 'SYN-WORKER-B', 300); commit;",
            variables={
                "context": context,
                "message": message_id,
                "fence": str(first_fence),
            },
        )
        reclaimed_fields = self.last_output_row(reclaimed).split("|")
        self.assertEqual(
            reclaimed_fields[:3],
            [message_id, "SYN-WORKER-B", "laboratory_outbox_worker"],
        )
        second_token = reclaimed_fields[3]
        second_fence = int(reclaimed_fields[4])
        self.assertNotEqual(second_token, first_token)
        self.assertEqual(second_fence, first_fence + 1)

        stale_confirmation = self.run_sql(
            OUTBOX_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "select delivery_state from public.confirm_outbox_delivery("
            ":'message', 'SYN-WORKER-A', :'token'::uuid, :fence, "
            "'SYN-BROKER', 'SYN-STALE-ACK'); commit;",
            variables={
                "context": context,
                "message": message_id,
                "token": first_token,
                "fence": str(first_fence),
            },
            check=False,
        )
        self.assertNotEqual(stale_confirmation.returncode, 0)
        self.assertIn("current unexpired lease coordinate", stale_confirmation.stderr)

        confirmed = self.run_sql(
            OUTBOX_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "select delivery_state || '|' || delivery_attempts::text || '|' || "
            "fencing_token::text || '|' || (delivered_at_utc is not null)::text "
            "from public.confirm_outbox_delivery("
            ":'message', 'SYN-WORKER-B', :'token'::uuid, :fence, "
            "'SYN-BROKER', 'SYN-ACK-SECOND-ATTEMPT'); commit;",
            variables={
                "context": context,
                "message": message_id,
                "token": second_token,
                "fence": str(second_fence),
            },
        )
        self.assertEqual(self.last_output_row(confirmed), "delivered|2|2|true")

        attempt_evidence = self.run_sql(
            OUTBOX_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "select string_agg(attempt.attempt_number::text || ':' || "
            "outcome.outcome_kind || ':' || "
            "coalesce(outcome.transport_receipt, ''), ',' "
            "order by attempt.attempt_number) "
            "from public.outbox_delivery_attempt as attempt "
            "join public.outbox_delivery_attempt_outcome as outcome "
            "using (tenant_id, message_id, attempt_number) "
            "where attempt.message_id = :'message'; commit;",
            variables={"context": context, "message": message_id},
        )
        self.assertEqual(
            self.last_output_row(attempt_evidence),
            "1:lease_expired:,2:delivery_confirmed:SYN-ACK-SECOND-ATTEMPT",
        )

        immutable_attempt = self.run_sql(
            ADMIN_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "set local role laboratory_outbox_authority; "
            "update public.outbox_delivery_attempt "
            "set worker_instance = 'SYN-REWRITTEN' "
            "where tenant_id = :'tenant' and message_id = :'message' "
            "and attempt_number = 1; commit;",
            variables={
                "context": context,
                "tenant": self.outbox_tenant,
                "message": message_id,
            },
            check=False,
        )
        self.assertNotEqual(immutable_attempt.returncode, 0)
        self.assertIn("append-only", immutable_attempt.stderr.lower())

    def test_outbox_lease_api_rejects_mixed_unit_interval_bypass(self) -> None:
        assert OUTBOX_DSN is not None
        context = signed_context(self.outbox_tenant)
        bypass = self.run_sql(
            OUTBOX_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "select message_id from public.claim_outbox_delivery("
            "'SYN-WORKER-INTERVAL', interval '1 month -30 days + 1 second'); "
            "commit;",
            variables={"context": context},
            check=False,
        )
        self.assertNotEqual(bypass.returncode, 0)
        self.assertIn("does not exist", bypass.stderr.lower())

        over_limit = self.run_sql(
            OUTBOX_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "select message_id from public.claim_outbox_delivery("
            "'SYN-WORKER-LONG', 901); commit;",
            variables={"context": context},
            check=False,
        )
        self.assertNotEqual(over_limit.returncode, 0)
        self.assertIn("1..900 lease seconds", over_limit.stderr)

    def test_outbox_message_identity_is_bounded_and_completable(self) -> None:
        assert APP_DSN is not None
        assert OUTBOX_DSN is not None
        context = signed_context(self.outbox_tenant)
        invalid_messages = (
            "SYN-" + "A" * 253,
            "SYN-UNICODE-\N{SNOWMAN}",
        )
        for message_id in invalid_messages:
            with self.subTest(message_id=message_id[:24]):
                rejected = self.run_sql(
                    APP_DSN,
                    "begin; "
                    "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
                    "insert into public.transactional_outbox ("
                    "tenant_id, message_id, topic, aggregate_id, aggregate_version, "
                    "payload, payload_sha256) values ("
                    ":'tenant', :'message', 'synthetic.identity', "
                    "'SYN-AGGREGATE', 1, '{\"state\":\"ready\"}'::jsonb, "
                    "encode(public.digest(convert_to("
                    "'{\"state\":\"ready\"}'::jsonb::text, 'UTF8'), "
                    "'sha256'), 'hex')); commit;",
                    variables={
                        "context": context,
                        "tenant": self.outbox_tenant,
                        "message": message_id,
                    },
                    check=False,
                )
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn("outbox_message_id_bounded", rejected.stderr)

        valid_message = "SYN-" + uuid4().hex + "B" * 220
        self.assertEqual(len(valid_message), 256)
        self.app_transaction(
            context,
            "insert into public.transactional_outbox ("
            "tenant_id, message_id, topic, aggregate_id, aggregate_version, "
            "payload, payload_sha256) values ('"
            + self.outbox_tenant
            + "', '"
            + valid_message
            + "', 'synthetic.identity', 'SYN-AGGREGATE', 1, "
            '\'{"state":"ready"}\'::jsonb, '
            "encode(public.digest(convert_to("
            "'{\"state\":\"ready\"}'::jsonb::text, 'UTF8'), 'sha256'), 'hex'))",
        )
        claimed = self.run_sql(
            OUTBOX_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "select message_id || '|' || lease_token::text || '|' || "
            "fencing_token::text from public.claim_outbox_delivery("
            "'SYN-WORKER-IDENTITY', 300); commit;",
            variables={"context": context},
        )
        claimed_message, token_value, fence_value = self.last_output_row(claimed).split("|")
        self.assertEqual(claimed_message, valid_message)
        confirmed = self.run_sql(
            OUTBOX_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "select delivery_state from public.confirm_outbox_delivery("
            ":'message', 'SYN-WORKER-IDENTITY', :'token'::uuid, :fence, "
            "'SYN-BROKER', :'receipt'); commit;",
            variables={
                "context": context,
                "message": valid_message,
                "token": token_value,
                "fence": fence_value,
                "receipt": "SYN-IDENTITY-ACK-" + uuid4().hex,
            },
        )
        self.assertEqual(self.last_output_row(confirmed), "delivered")

    def test_outbox_transport_receipt_is_unique_within_tenant(self) -> None:
        assert OUTBOX_DSN is not None
        context = signed_context(self.outbox_tenant)
        shared_receipt = "SYN-SHARED-ACK-" + uuid4().hex
        leases: list[tuple[str, str, str]] = []
        for sequence in (1, 2):
            message_id = f"SYN-LIVE-RECEIPT-{sequence}-" + uuid4().hex
            self.app_transaction(
                context,
                "insert into public.transactional_outbox ("
                "tenant_id, message_id, topic, aggregate_id, aggregate_version, "
                "payload, payload_sha256) values ('"
                + self.outbox_tenant
                + "', '"
                + message_id
                + "', 'synthetic.receipt', 'SYN-AGGREGATE', 1, "
                '\'{"state":"ready"}\'::jsonb, '
                "encode(public.digest(convert_to("
                "'{\"state\":\"ready\"}'::jsonb::text, 'UTF8'), 'sha256'), 'hex'))",
            )
            claimed = self.run_sql(
                OUTBOX_DSN,
                "begin; "
                "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
                "select message_id || '|' || lease_token::text || '|' || "
                "fencing_token::text from public.claim_outbox_delivery("
                ":'worker', 300); commit;",
                variables={
                    "context": context,
                    "worker": f"SYN-WORKER-RECEIPT-{sequence}",
                },
            )
            message_value, token_value, fence_value = self.last_output_row(claimed).split("|")
            self.assertEqual(message_value, message_id)
            leases.append((message_value, token_value, fence_value))
            if sequence == 1:
                accepted = self.run_sql(
                    OUTBOX_DSN,
                    "begin; "
                    "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
                    "select delivery_state from public.confirm_outbox_delivery("
                    ":'message', :'worker', :'token'::uuid, :fence, "
                    "'SYN-BROKER', :'receipt'); commit;",
                    variables={
                        "context": context,
                        "message": message_value,
                        "worker": f"SYN-WORKER-RECEIPT-{sequence}",
                        "token": token_value,
                        "fence": fence_value,
                        "receipt": shared_receipt,
                    },
                )
                self.assertEqual(self.last_output_row(accepted), "delivered")

        second_message, second_token, second_fence = leases[1]
        duplicate = self.run_sql(
            OUTBOX_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "select delivery_state from public.confirm_outbox_delivery("
            ":'message', 'SYN-WORKER-RECEIPT-2', :'token'::uuid, :fence, "
            "'SYN-BROKER', :'receipt'); commit;",
            variables={
                "context": context,
                "message": second_message,
                "token": second_token,
                "fence": second_fence,
                "receipt": shared_receipt,
            },
            check=False,
        )
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertIn("duplicate key", duplicate.stderr.lower())

        completed = self.run_sql(
            OUTBOX_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "select delivery_state from public.confirm_outbox_delivery("
            ":'message', 'SYN-WORKER-RECEIPT-2', :'token'::uuid, :fence, "
            "'SYN-BROKER', :'receipt'); commit;",
            variables={
                "context": context,
                "message": second_message,
                "token": second_token,
                "fence": second_fence,
                "receipt": "SYN-DISTINCT-ACK-" + uuid4().hex,
            },
        )
        self.assertEqual(self.last_output_row(completed), "delivered")

    def test_outbox_initial_and_transition_authority_is_explicit(self) -> None:
        assert APP_DSN is not None
        assert ADMIN_DSN is not None
        context = signed_context(self.outbox_tenant)
        forged_message = "SYN-LIVE-FORGED-TERMINAL-" + uuid4().hex
        forged_terminal = self.run_sql(
            APP_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "insert into public.transactional_outbox ("
            "tenant_id, message_id, topic, aggregate_id, aggregate_version, "
            "payload, payload_sha256, delivery_state, delivery_attempts, "
            "fencing_token, delivered_at_utc) values ("
            ":'tenant', :'message', 'synthetic.forged', 'SYN-AGGREGATE', 1, "
            '\'{"state":"forged"}\'::jsonb, '
            "encode(public.digest(convert_to("
            "'{\"state\":\"forged\"}'::jsonb::text, 'UTF8'), 'sha256'), 'hex'), "
            "'delivered', 1, 1, clock_timestamp()); commit;",
            variables={
                "context": context,
                "tenant": self.outbox_tenant,
                "message": forged_message,
            },
            check=False,
        )
        self.assertNotEqual(forged_terminal.returncode, 0)
        self.assertIn("permission denied", forged_terminal.stderr.lower())

        authority_null_state = self.run_sql(
            ADMIN_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "set local role laboratory_outbox_authority; "
            "insert into public.transactional_outbox ("
            "tenant_id, message_id, topic, aggregate_id, aggregate_version, "
            "payload, payload_sha256, delivery_state, delivery_attempts, "
            "fencing_token, last_error_code) values ("
            ":'tenant', :'message', 'synthetic.null-state', 'SYN-AGGREGATE', 1, "
            '\'{"state":"recovery_required"}\'::jsonb, '
            "encode(public.digest(convert_to("
            "'{\"state\":\"recovery_required\"}'::jsonb::text, 'UTF8'), "
            "'sha256'), 'hex'), 'recovery_required', 1, 1, null); commit;",
            variables={
                "context": context,
                "tenant": self.outbox_tenant,
                "message": "SYN-LIVE-NULL-STATE-" + uuid4().hex,
            },
            check=False,
        )
        self.assertNotEqual(authority_null_state.returncode, 0)
        self.assertIn("begins in the ready state", authority_null_state.stderr.lower())

        ready_message = "SYN-LIVE-ILLEGAL-TRANSITION-" + uuid4().hex
        self.app_transaction(
            context,
            "insert into public.transactional_outbox ("
            "tenant_id, message_id, topic, aggregate_id, aggregate_version, "
            "payload, payload_sha256, available_at_utc) values ('"
            + self.outbox_tenant
            + "', '"
            + ready_message
            + "', 'synthetic.transition', 'SYN-AGGREGATE', 1, "
            '\'{"state":"ready"}\'::jsonb, '
            "encode(public.digest(convert_to("
            "'{\"state\":\"ready\"}'::jsonb::text, 'UTF8'), 'sha256'), 'hex'), "
            "'2035-01-01T00:00:00Z')",
        )
        illegal_recovery = self.run_sql(
            ADMIN_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "set local role laboratory_outbox_authority; "
            "update public.transactional_outbox "
            "set delivery_state = 'recovery_required', delivery_attempts = 1, "
            "fencing_token = 1, last_error_code = 'SYN.FORGED' "
            "where tenant_id = :'tenant' and message_id = :'message'; commit;",
            variables={
                "context": context,
                "tenant": self.outbox_tenant,
                "message": ready_message,
            },
            check=False,
        )
        self.assertNotEqual(illegal_recovery.returncode, 0)
        self.assertIn("released state-machine edge", illegal_recovery.stderr.lower())

    def test_outbox_failure_and_recovery_are_governed_and_reconstructable(self) -> None:
        assert OUTBOX_DSN is not None
        assert RECOVERY_DSN is not None
        assert ADMIN_DSN is not None
        message_id = "SYN-LIVE-RECOVERY-" + uuid4().hex
        context = signed_context(self.outbox_tenant)
        self.app_transaction(
            context,
            "insert into public.transactional_outbox ("
            "tenant_id, message_id, topic, aggregate_id, aggregate_version, "
            "payload, payload_sha256) values ('"
            + self.outbox_tenant
            + "', '"
            + message_id
            + "', 'synthetic.recovery', 'SYN-AGGREGATE', 1, "
            '\'{"state":"ready"}\'::jsonb, '
            "encode(public.digest(convert_to("
            "'{\"state\":\"ready\"}'::jsonb::text, 'UTF8'), 'sha256'), 'hex'))",
        )

        claimed = self.run_sql(
            OUTBOX_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "select message_id || '|' || lease_token::text || '|' || "
            "fencing_token::text from public.claim_outbox_delivery("
            "'SYN-WORKER-RECOVERY', 300); commit;",
            variables={"context": context},
        )
        claimed_fields = self.last_output_row(claimed).split("|")
        self.assertEqual(claimed_fields[0], message_id)
        first_token = claimed_fields[1]
        first_fence = claimed_fields[2]

        authority_null_outcome = self.run_sql(
            ADMIN_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "set local role laboratory_outbox_authority; "
            "insert into public.outbox_delivery_attempt_outcome ("
            "tenant_id, message_id, attempt_number, outcome_kind, closed_at_utc) "
            "values (:'tenant', :'message', 1, 'delivery_confirmed', "
            "clock_timestamp()); commit;",
            variables={
                "context": context,
                "tenant": self.outbox_tenant,
                "message": message_id,
            },
            check=False,
        )
        self.assertNotEqual(authority_null_outcome.returncode, 0)
        self.assertIn(
            "outbox_delivery_attempt_outcome_check",
            authority_null_outcome.stderr,
        )

        failed = self.run_sql(
            OUTBOX_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "select delivery_state || '|' || last_error_code "
            "from public.fail_outbox_delivery("
            ":'message', 'SYN-WORKER-RECOVERY', :'token'::uuid, :fence, "
            "'BROKER.UNAVAILABLE'); commit;",
            variables={
                "context": context,
                "message": message_id,
                "token": first_token,
                "fence": first_fence,
            },
        )
        self.assertEqual(
            self.last_output_row(failed),
            "recovery_required|BROKER.UNAVAILABLE",
        )

        arbitrary_ready = self.run_sql(
            ADMIN_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "set local role laboratory_outbox_authority; "
            "update public.transactional_outbox "
            "set delivery_state = 'ready', last_error_code = null "
            "where tenant_id = :'tenant' and message_id = :'message'; commit;",
            variables={
                "context": context,
                "tenant": self.outbox_tenant,
                "message": message_id,
            },
            check=False,
        )
        self.assertNotEqual(arbitrary_ready.returncode, 0)
        self.assertIn("immutable release decision", arbitrary_ready.stderr.lower())

        released = self.run_sql(
            RECOVERY_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "select delivery_state || '|' || (last_error_code is null)::text "
            "from public.release_outbox_recovery("
            ":'message', :fence, 0, 'SYN-INCIDENT-0042'); commit;",
            variables={
                "context": context,
                "message": message_id,
                "fence": first_fence,
            },
        )
        self.assertEqual(self.last_output_row(released), "ready|true")

        reclaimed = self.run_sql(
            OUTBOX_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "select message_id || '|' || lease_token::text || '|' || "
            "fencing_token::text from public.claim_outbox_delivery("
            "'SYN-WORKER-RECOVERED', 300); commit;",
            variables={"context": context},
        )
        reclaimed_fields = self.last_output_row(reclaimed).split("|")
        self.assertEqual(reclaimed_fields[0], message_id)
        second_token = reclaimed_fields[1]
        second_fence = reclaimed_fields[2]
        self.assertEqual(int(second_fence), int(first_fence) + 1)

        confirmed = self.run_sql(
            OUTBOX_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "select delivery_state from public.confirm_outbox_delivery("
            ":'message', 'SYN-WORKER-RECOVERED', :'token'::uuid, :fence, "
            "'SYN-BROKER', 'SYN-ACK-AFTER-RECOVERY'); commit;",
            variables={
                "context": context,
                "message": message_id,
                "token": second_token,
                "fence": second_fence,
            },
        )
        self.assertEqual(self.last_output_row(confirmed), "delivered")

        evidence = self.run_sql(
            RECOVERY_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "select (select count(*) from public.outbox_delivery_attempt "
            "where message_id = :'message')::text || '|' || "
            "(select count(*) from public.outbox_delivery_attempt_outcome "
            "where message_id = :'message')::text || '|' || "
            "(select recovery_reference || ':' || released_by::text "
            "from public.outbox_recovery_release "
            "where message_id = :'message') || '|' || "
            "(select transport_receipt from public.outbox_delivery_attempt_outcome "
            "where message_id = :'message' "
            "and outcome_kind = 'delivery_confirmed'); commit;",
            variables={"context": context, "message": message_id},
        )
        self.assertEqual(
            self.last_output_row(evidence),
            "2|2|SYN-INCIDENT-0042:laboratory_outbox_recovery_operator|SYN-ACK-AFTER-RECOVERY",
        )


@unittest.skipUnless(
    UPGRADE_OUTBOX_DSN and UPGRADE_RECOVERY_DSN and HMAC_KEY_HEX and shutil.which("psql"),
    "configured upgrade DSNs, synthetic HMAC key, and psql enable this proof",
)
class PostgresUpgradeBoundaryIntegrationTests(unittest.TestCase):
    @staticmethod
    def run_sql(
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
        return subprocess.run(
            command,
            input=sql,
            check=check,
            capture_output=True,
            text=True,
            timeout=20,
        )

    @staticmethod
    def last_output_row(completed: subprocess.CompletedProcess[str]) -> str:
        rows = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        if not rows:
            raise AssertionError("PostgreSQL upgrade proof requires one result row")
        return rows[-1]

    def test_pre_004_ready_rows_enter_governed_delivery_with_complete_evidence(self) -> None:
        assert UPGRADE_OUTBOX_DSN is not None
        assert UPGRADE_RECOVERY_DSN is not None
        context = signed_context(UPGRADE_TENANT)

        confirmed_claim = self.run_sql(
            UPGRADE_OUTBOX_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "select message_id || '|' || lease_token::text || '|' || "
            "fencing_token::text from public.claim_outbox_delivery("
            "'SYN-UPGRADE-WORKER-CONFIRM', 300); commit;",
            variables={"context": context},
        )
        message_value, token_value, fence_value = self.last_output_row(confirmed_claim).split("|")
        self.assertEqual(message_value, "SYN-UPGRADE-READY-CONFIRM")
        confirmed = self.run_sql(
            UPGRADE_OUTBOX_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "select delivery_state from public.confirm_outbox_delivery("
            ":'message', 'SYN-UPGRADE-WORKER-CONFIRM', :'token'::uuid, :fence, "
            "'SYN-UPGRADE-BROKER', 'SYN-UPGRADE-ACK-CONFIRM'); commit;",
            variables={
                "context": context,
                "message": message_value,
                "token": token_value,
                "fence": fence_value,
            },
        )
        self.assertEqual(self.last_output_row(confirmed), "delivered")

        recovery_claim = self.run_sql(
            UPGRADE_OUTBOX_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "select message_id || '|' || lease_token::text || '|' || "
            "fencing_token::text from public.claim_outbox_delivery("
            "'SYN-UPGRADE-WORKER-RECOVERY', 300); commit;",
            variables={"context": context},
        )
        recovery_message, recovery_token, recovery_fence = self.last_output_row(
            recovery_claim
        ).split("|")
        self.assertEqual(recovery_message, "SYN-UPGRADE-READY-RECOVERY")
        failed = self.run_sql(
            UPGRADE_OUTBOX_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "select delivery_state from public.fail_outbox_delivery("
            ":'message', 'SYN-UPGRADE-WORKER-RECOVERY', :'token'::uuid, :fence, "
            "'SYN.UPGRADE.FAILURE'); commit;",
            variables={
                "context": context,
                "message": recovery_message,
                "token": recovery_token,
                "fence": recovery_fence,
            },
        )
        self.assertEqual(self.last_output_row(failed), "recovery_required")

        released = self.run_sql(
            UPGRADE_RECOVERY_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "select delivery_state from public.release_outbox_recovery("
            ":'message', :fence, 0, 'SYN-UPGRADE-RECOVERY-RELEASE'); commit;",
            variables={
                "context": context,
                "message": recovery_message,
                "fence": recovery_fence,
            },
        )
        self.assertEqual(self.last_output_row(released), "ready")

        second_claim = self.run_sql(
            UPGRADE_OUTBOX_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "select message_id || '|' || lease_token::text || '|' || "
            "fencing_token::text from public.claim_outbox_delivery("
            "'SYN-UPGRADE-WORKER-RECOVERED', 300); commit;",
            variables={"context": context},
        )
        second_message, second_token, second_fence = self.last_output_row(second_claim).split("|")
        self.assertEqual(second_message, recovery_message)
        recovered = self.run_sql(
            UPGRADE_OUTBOX_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "select delivery_state from public.confirm_outbox_delivery("
            ":'message', 'SYN-UPGRADE-WORKER-RECOVERED', :'token'::uuid, :fence, "
            "'SYN-UPGRADE-BROKER', 'SYN-UPGRADE-ACK-RECOVERED'); commit;",
            variables={
                "context": context,
                "message": second_message,
                "token": second_token,
                "fence": second_fence,
            },
        )
        self.assertEqual(self.last_output_row(recovered), "delivered")

        evidence = self.run_sql(
            UPGRADE_RECOVERY_DSN,
            "begin; "
            "select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "select (select count(*) from public.outbox_delivery_attempt)::text "
            "|| '|' || "
            "(select count(*) from public.outbox_delivery_attempt_outcome)::text "
            "|| '|' || "
            "(select count(*) from public.outbox_recovery_release)::text; commit;",
            variables={"context": context},
        )
        self.assertEqual(self.last_output_row(evidence), "3|3|1")


@unittest.skipUnless(
    ADMIN_DSN and APP_DSN and HMAC_KEY_HEX and psycopg is not None,
    "configured PostgreSQL DSNs, synthetic HMAC key, and psycopg enable this proof",
)
class PostgresGoldenSpecimenIntegrationTests(unittest.TestCase):
    """One durable FastAPI journey with restart and recovery evidence."""

    CALLER_ID = "SYN-CI-SERVICE-IDENTITY"
    VALID_RAW = b'{"analyte":"synthetic-dna","value":"12.5","unit":"ng/uL"}'
    QUARANTINED_RAW = b'{"analyte":" ","value":"12.5","unit":"ng/uL"}'
    ACTORS = frozenset({"SYN-ACTOR-01", "SYN-SCIENTIST-01", "SYN-QUALITY-01"})
    OCCURRED_AT = datetime.fromisoformat("2026-08-17T14:30:00+00:00")

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        suffix = uuid4().hex[:10].upper()
        cls.tenant_a = f"SYN-WORKBENCH-A-{suffix}"
        cls.tenant_b = f"SYN-WORKBENCH-B-{suffix}"
        cls.run_sql(
            """
            insert into public.tenant (tenant_id, display_name)
            values (%s, 'Synthetic durable workbench tenant A'),
                   (%s, 'Synthetic durable workbench tenant B')
            """,
            (cls.tenant_a, cls.tenant_b),
        )

    @classmethod
    def run_sql(cls, statement: str, parameters: tuple[object, ...]) -> None:
        assert ADMIN_DSN is not None and psycopg is not None
        with psycopg.connect(ADMIN_DSN) as connection, connection.cursor() as cursor:
            cursor.execute(statement, parameters)

    @classmethod
    def scalar(cls, statement: str, parameters: tuple[object, ...]) -> str:
        assert ADMIN_DSN is not None and psycopg is not None
        with psycopg.connect(ADMIN_DSN) as connection, connection.cursor() as cursor:
            cursor.execute(statement, parameters)
            row = cursor.fetchone()
        if row is None:
            raise AssertionError("configured PostgreSQL proof requires one result row")
        return str(row[0])

    @classmethod
    def context_for(cls, tenant_id: str) -> SignedTenantContext:
        return SignedTenantContext(
            **json.loads(signed_context(tenant_id, subject_id=cls.CALLER_ID))
        )

    @classmethod
    def service(
        cls,
        *,
        tenant_id: str | None = None,
        failure_probe: Callable[[str], None] | None = None,
    ) -> PostgresWorkbenchService:
        assert APP_DSN is not None and psycopg is not None
        return PostgresWorkbenchService(
            lambda: psycopg.connect(APP_DSN),
            tenant_context_provider=cls.context_for,
            tenant_id=tenant_id or cls.tenant_a,
            caller_id=cls.CALLER_ID,
            actor_ids=cls.ACTORS,
            failure_probe=failure_probe,
        )

    def identity(self, label: str) -> tuple[str, str]:
        suffix = uuid4().hex[:12].upper()
        return f"SYN-PG-RUN-{label}-{suffix}", f"SYN-PG-SPM-{label}-{suffix}"

    def payload(
        self,
        run_id: str,
        specimen_id: str,
        *,
        raw: bytes | None = None,
    ) -> dict[str, object]:
        return {
            "run_id": run_id,
            "tenant_id": self.tenant_a,
            "specimen_id": specimen_id,
            "actor_id": "SYN-ACTOR-01",
            "scientist_id": "SYN-SCIENTIST-01",
            "quality_actor_id": "SYN-QUALITY-01",
            "occurred_at": self.OCCURRED_AT.isoformat(),
            "raw_instrument_payload_base64": b64encode(
                raw if raw is not None else self.VALID_RAW
            ).decode("ascii"),
            "vendor_payload": {"status": "under_review"},
        }

    def post(self, client: TestClient, route: str, payload: dict[str, object]):
        return client.post(
            route,
            headers={"X-Tenant-ID": self.tenant_a},
            json=payload,
        )

    def test_fastapi_result_reloads_from_canonical_state_after_restart(self) -> None:
        run_id, specimen_id = self.identity("RESTART")
        first_client = TestClient(create_app(self.service()))
        self.assertEqual(
            first_client.get("/health/ready").json(),
            {"status": "ready", "state_adapter": "postgresql"},
        )
        created = self.post(
            first_client,
            "/api/workbench/golden-runs",
            self.payload(run_id, specimen_id),
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["specimen"]["state"], "released")
        self.assertEqual(created.json()["specimen"]["version"], 5)

        restarted_client = TestClient(create_app(self.service()))
        specimen = restarted_client.get(
            f"/api/workbench/specimens/{specimen_id}",
            headers={"X-Tenant-ID": self.tenant_a},
            params={"tenant_id": self.tenant_a},
        )
        observation = restarted_client.get(
            f"/api/workbench/observations/{run_id}",
            headers={"X-Tenant-ID": self.tenant_a},
            params={"tenant_id": self.tenant_a},
        )
        self.assertEqual(specimen.status_code, 200, specimen.text)
        self.assertEqual(specimen.json(), created.json()["specimen"])

        if find_spec("lims_eln_contracts") is None:
            self.assertIsNone(created.json()["observation"])
            self.assertEqual(observation.status_code, 404, observation.text)
            self.assertEqual(
                observation.json()["type"],
                "urn:lims-eln:problem:observation_absent",
            )
        else:
            from lims_eln_contracts import (
                GoldenSpecimenObservation,
                model_from_strict_json,
            )

            self.assertEqual(observation.status_code, 200, observation.text)
            self.assertEqual(observation.json(), created.json()["observation"])
            typed = model_from_strict_json(
                GoldenSpecimenObservation,
                json.dumps(observation.json(), separators=(",", ":")),
            )
            self.assertEqual(
                typed.result.producer_detail["configuration"]["state_adapter"],
                "postgresql",
            )
            self.assertEqual(
                typed.result.producer_detail["configuration"]["migration_head"],
                "008",
            )

        temporal = self.scalar(
            """
            select (
                invocation.lease_expires_at_utc > invocation.reserved_at_utc
                and invocation.completed_at_utc >= invocation.reserved_at_utc
                and receipt.recorded_at_utc >= receipt.requested_at_utc
            )::text
              from public.bounded_call_invocation as invocation
              join public.bounded_call_receipt as receipt
                on receipt.tenant_id = invocation.tenant_id
               and receipt.call_id = invocation.call_id
             where invocation.tenant_id = %s and invocation.call_id = %s
            """,
            (self.tenant_a, run_id),
        )
        self.assertEqual(temporal, "true")

    def test_replay_collision_and_tenant_isolation_remain_bounded(self) -> None:
        run_id, specimen_id = self.identity("REPLAY")
        payload = self.payload(run_id, specimen_id)
        first = self.post(
            TestClient(create_app(self.service())),
            "/api/workbench/golden-runs",
            payload,
        )
        self.assertEqual(first.status_code, 201, first.text)
        before = self.row_counts(run_id, specimen_id)
        replay = self.post(
            TestClient(create_app(self.service())),
            "/api/workbench/golden-runs",
            payload,
        )
        self.assertEqual(replay.status_code, 201, replay.text)
        self.assertEqual(replay.json(), first.json())
        self.assertEqual(self.row_counts(run_id, specimen_id), before)

        changed_time_payload = dict(payload)
        changed_time_payload["occurred_at"] = (self.OCCURRED_AT + timedelta(seconds=1)).isoformat()
        changed_time = self.post(
            TestClient(create_app(self.service())),
            "/api/workbench/golden-runs",
            changed_time_payload,
        )
        self.assertEqual(changed_time.status_code, 409, changed_time.text)
        self.assertIn("different content", changed_time.json()["detail"])

        changed = self.post(
            TestClient(create_app(self.service())),
            "/api/workbench/golden-runs",
            self.payload(
                run_id,
                specimen_id,
                raw=b'{"analyte":"synthetic-dna","value":"12.6","unit":"ng/uL"}',
            ),
        )
        self.assertEqual(changed.status_code, 409, changed.text)
        self.assertIn("different content", changed.json()["detail"])
        with self.assertRaises(SpecimenAbsent):
            self.service(tenant_id=self.tenant_b).specimen(self.tenant_b, specimen_id)

        outside_run, _ = self.identity("OUTSIDE-GRANT")
        outside = self.post(
            TestClient(create_app(self.service())),
            "/api/workbench/golden-runs",
            self.payload(outside_run, "OUTSIDE-GRANT-SPECIMEN"),
        )
        self.assertEqual(outside.status_code, 403, outside.text)
        self.assertEqual(
            outside.json()["type"],
            "urn:lims-eln:problem:resource_outside_grant",
        )

    def test_workbench_authority_failures_return_typed_forbidden_problems(self) -> None:
        actor_run, actor_specimen = self.identity("ACTOR-AUTHORITY")
        actor_payload = self.payload(actor_run, actor_specimen)
        actor_payload["actor_id"] = "SYN-ACTOR-OUTSIDE-WORKBENCH"
        actor_response = self.post(
            TestClient(create_app(self.service())),
            "/api/workbench/golden-runs",
            actor_payload,
        )
        self.assertEqual(actor_response.status_code, 403, actor_response.text)
        self.assertEqual(
            actor_response.json()["type"],
            "urn:lims-eln:problem:actor_outside_workbench_authority",
        )

        tenant_run, tenant_specimen = self.identity("TENANT-AUTHORITY")
        tenant_payload = self.payload(tenant_run, tenant_specimen)
        tenant_payload["tenant_id"] = self.tenant_b
        tenant_response = TestClient(create_app(self.service())).post(
            "/api/workbench/golden-runs",
            headers={"X-Tenant-ID": self.tenant_b},
            json=tenant_payload,
        )
        self.assertEqual(tenant_response.status_code, 403, tenant_response.text)
        self.assertEqual(
            tenant_response.json()["type"],
            "urn:lims-eln:problem:tenant_outside_workbench_authority",
        )

    def test_completed_replay_keeps_its_snapshot_after_later_custody_move(self) -> None:
        assert APP_DSN is not None and psycopg is not None
        run_id, specimen_id = self.identity("IMMUTABLE-REPLAY")
        payload = self.payload(run_id, specimen_id)
        client = TestClient(create_app(self.service()))
        first = self.post(client, "/api/workbench/golden-runs", payload)
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(
            first.json()["specimen"]["custody"]["location"],
            "SYN-LAB-A/RECEIVING",
        )

        moved_location = "SYN-LAB-A/ARCHIVE"
        with psycopg.connect(APP_DSN) as connection, connection.cursor() as cursor:
            PostgresTenantBinding(self.context_for(self.tenant_a)).bind(
                cursor,
                expected_tenant_id=self.tenant_a,
            )
            cursor.execute(
                """
                select custody_version
                  from public.record_custody_transfer(%s, %s, %s, 1, %s, %s)
                """,
                (
                    specimen_id,
                    moved_location,
                    "SYN-ACTOR-01",
                    f"{run_id}:custody:archive",
                    self.OCCURRED_AT + timedelta(minutes=1),
                ),
            )
            moved = cursor.fetchone()
        self.assertIsNotNone(moved)
        self.assertEqual(int(moved[0]), 2)

        replay = self.post(
            TestClient(create_app(self.service())),
            "/api/workbench/golden-runs",
            payload,
        )
        self.assertEqual(replay.status_code, 201, replay.text)
        self.assertEqual(replay.json(), first.json())

        current = TestClient(create_app(self.service())).get(
            f"/api/workbench/specimens/{specimen_id}",
            headers={"X-Tenant-ID": self.tenant_a},
            params={"tenant_id": self.tenant_a},
        )
        self.assertEqual(current.status_code, 200, current.text)
        self.assertEqual(current.json()["custody"]["location"], moved_location)
        self.assertEqual(current.json()["custody"]["version"], 2)
        self.assertEqual(
            replay.json()["specimen"]["custody"]["location"],
            "SYN-LAB-A/RECEIVING",
        )

    def row_counts(self, run_id: str, specimen_id: str) -> str:
        return self.scalar(
            """
            select concat_ws(':',
                (select count(*) from public.specimen_event
                  where tenant_id = %s and specimen_id = %s),
                (select count(*) from public.instrument_inbox
                  where tenant_id = %s and specimen_id = %s),
                (select count(*) from public.bounded_call_receipt
                  where tenant_id = %s and call_id = %s))
            """,
            (
                self.tenant_a,
                specimen_id,
                self.tenant_a,
                specimen_id,
                self.tenant_a,
                run_id,
            ),
        )

    def test_late_failure_rolls_back_then_a_fresh_request_repairs(self) -> None:
        run_id, specimen_id = self.identity("ROLLBACK")

        def fail_after_materialization(label: str) -> None:
            if label == "after_materialization":
                raise OSError("synthetic late materialization failure")

        with self.assertRaisesRegex(OSError, "late materialization"):
            self.service(failure_probe=fail_after_materialization).run_golden_specimen(
                run_id=run_id,
                tenant_id=self.tenant_a,
                specimen_id=specimen_id,
                actor_id="SYN-ACTOR-01",
                scientist_id="SYN-SCIENTIST-01",
                quality_actor_id="SYN-QUALITY-01",
                occurred_at=self.OCCURRED_AT,
                raw_instrument_json=self.VALID_RAW,
                vendor_payload={"status": "under_review"},
            )
        with self.assertRaises(SpecimenAbsent):
            self.service().specimen(self.tenant_a, specimen_id)
        self.assertEqual(self.partial_row_count(run_id, specimen_id), "0")

        repaired = self.post(
            TestClient(create_app(self.service())),
            "/api/workbench/golden-runs",
            self.payload(run_id, specimen_id),
        )
        self.assertEqual(repaired.status_code, 201, repaired.text)
        self.assertEqual(repaired.json()["specimen"]["state"], "released")

    def partial_row_count(self, run_id: str, specimen_id: str) -> str:
        return self.scalar(
            """
            select (
                (select count(*) from public.specimen
                  where tenant_id = %s and specimen_id = %s)
              + (select count(*) from public.specimen_event
                  where tenant_id = %s and specimen_id = %s)
              + (select count(*) from public.instrument_inbox
                  where tenant_id = %s and specimen_id = %s)
              + (select count(*) from public.bounded_call_invocation
                  where tenant_id = %s and call_id = %s)
              + (select count(*) from public.bounded_call_receipt
                  where tenant_id = %s and call_id = %s)
            )::text
            """,
            (
                self.tenant_a,
                specimen_id,
                self.tenant_a,
                specimen_id,
                self.tenant_a,
                specimen_id,
                self.tenant_a,
                run_id,
                self.tenant_a,
                run_id,
            ),
        )

    def test_quarantine_and_one_recovery_survive_two_restarts(self) -> None:
        quarantine_run, specimen_id = self.identity("QUARANTINE")
        recovery_run, _ = self.identity("RECOVERY")
        invalid_recovery_run, _ = self.identity("INVALID-RECOVERY")
        review = self.post(
            TestClient(create_app(self.service())),
            "/api/workbench/golden-runs",
            self.payload(quarantine_run, specimen_id, raw=self.QUARANTINED_RAW),
        )
        self.assertEqual(review.status_code, 409, review.text)
        self.assertEqual(self.service().summary(self.tenant_a)["quarantine_count"], 1)

        invalid_recovery_payload = {
            **self.payload(
                invalid_recovery_run,
                specimen_id,
                raw=self.QUARANTINED_RAW,
            ),
            "recovery_of_run_id": quarantine_run,
        }
        invalid_recovery = self.post(
            TestClient(create_app(self.service())),
            "/api/workbench/instrument-recovery-runs",
            invalid_recovery_payload,
        )
        self.assertEqual(invalid_recovery.status_code, 409, invalid_recovery.text)
        self.assertEqual(
            self.scalar(
                """
                select count(*)::text
                  from public.bounded_call_invocation
                 where tenant_id = %s and call_id = %s
                """,
                (self.tenant_a, invalid_recovery_run),
            ),
            "0",
        )

        recovery_payload = {
            **self.payload(recovery_run, specimen_id),
            "recovery_of_run_id": quarantine_run,
        }
        recovered = self.post(
            TestClient(create_app(self.service())),
            "/api/workbench/instrument-recovery-runs",
            recovery_payload,
        )
        self.assertEqual(recovered.status_code, 201, recovered.text)
        second_restart = self.service()
        if find_spec("lims_eln_contracts") is None:
            self.assertIsNone(recovered.json()["observation"])
            with self.assertRaises(ObservationAbsent):
                second_restart.observation(self.tenant_a, recovery_run)
        else:
            self.assertEqual(
                second_restart.observation(self.tenant_a, recovery_run),
                recovered.json()["observation"],
            )
        final_summary = second_restart.summary(self.tenant_a)
        self.assertEqual(final_summary["quarantine_count"], 0)
        self.assertEqual(final_summary["quarantine_history_count"], 1)

    def test_recovery_requires_the_original_failed_receipt(self) -> None:
        rogue_run, specimen_id = self.identity("ROGUE-RECOVERY-SOURCE")
        recovery_run, _ = self.identity("ROGUE-RECOVERY")
        operation_name, operation_version, operation_digest = _operation_contract("initial")
        self.run_sql(
            """
            insert into public.bounded_call_invocation (
                tenant_id, call_id, invocation_sha256, operation_name,
                operation_version, operation_contract_sha256, state,
                lease_token, fencing_token, lease_expires_at_utc, recovery_reason
            ) values (
                %s, %s, %s, %s, %s, %s, 'recovery_required',
                %s, 1, clock_timestamp() + interval '5 minutes', %s
            )
            """,
            (
                self.tenant_a,
                rogue_run,
                sha256(rogue_run.encode("ascii")).hexdigest(),
                operation_name,
                operation_version,
                operation_digest,
                uuid4(),
                "instrument.analyte.required",
            ),
        )

        with self.assertRaisesRegex(RuntimeError, "exact failed receipt"):
            self.service().resume_instrument_review(
                recovery_of_run_id=rogue_run,
                run_id=recovery_run,
                tenant_id=self.tenant_a,
                specimen_id=specimen_id,
                actor_id="SYN-ACTOR-01",
                scientist_id="SYN-SCIENTIST-01",
                quality_actor_id="SYN-QUALITY-01",
                occurred_at=self.OCCURRED_AT,
                raw_instrument_json=self.VALID_RAW,
                vendor_payload={"status": "under_review"},
            )
        self.assertEqual(
            self.scalar(
                """
                select count(*)::text
                  from public.bounded_call_invocation
                 where tenant_id = %s and call_id = %s
                """,
                (self.tenant_a, recovery_run),
            ),
            "0",
        )

    def test_recovery_fails_closed_when_canonical_digest_has_drifted(self) -> None:
        quarantine_run, specimen_id = self.identity("RECOVERY-DIGEST-SOURCE")
        recovery_run, _ = self.identity("RECOVERY-DIGEST")
        review = self.post(
            TestClient(create_app(self.service())),
            "/api/workbench/golden-runs",
            self.payload(quarantine_run, specimen_id, raw=self.QUARANTINED_RAW),
        )
        self.assertEqual(review.status_code, 409, review.text)
        self.run_sql(
            """
            update public.specimen
               set canonical_sha256 = repeat('0', 64)
             where tenant_id = %s and specimen_id = %s
            """,
            (self.tenant_a, specimen_id),
        )

        with self.assertRaisesRegex(RuntimeError, "stored digest"):
            self.service().resume_instrument_review(
                recovery_of_run_id=quarantine_run,
                run_id=recovery_run,
                tenant_id=self.tenant_a,
                specimen_id=specimen_id,
                actor_id="SYN-ACTOR-01",
                scientist_id="SYN-SCIENTIST-01",
                quality_actor_id="SYN-QUALITY-01",
                occurred_at=self.OCCURRED_AT,
                raw_instrument_json=self.VALID_RAW,
                vendor_payload={"status": "under_review"},
            )
        self.assertEqual(
            self.scalar(
                """
                select count(*)::text
                  from public.bounded_call_invocation
                 where tenant_id = %s and call_id = %s
                """,
                (self.tenant_a, recovery_run),
            ),
            "0",
        )

    def test_decimal_source_shape_survives_postgresql_roundtrip(self) -> None:
        cases = (
            ("EXPONENT", "1E+2", "100:1:0"),
            ("SIGNED-ZERO", "-0.0", "0.0:1:1"),
        )
        for label, value, expected in cases:
            with self.subTest(label=label):
                run_id, specimen_id = self.identity(label)
                raw = json.dumps(
                    {
                        "analyte": "synthetic-dna",
                        "value": value,
                        "unit": "ng/uL",
                    },
                    separators=(",", ":"),
                ).encode("ascii")
                created = self.post(
                    TestClient(create_app(self.service())),
                    "/api/workbench/golden-runs",
                    self.payload(run_id, specimen_id, raw=raw),
                )
                self.assertEqual(created.status_code, 201, created.text)
                if find_spec("lims_eln_contracts") is None:
                    self.assertIsNone(created.json()["observation"])
                    with self.assertRaises(ObservationAbsent):
                        self.service().observation(self.tenant_a, run_id)
                else:
                    self.service().observation(self.tenant_a, run_id)
                self.assertEqual(
                    self.scalar(
                        """
                        select quantity::text || ':' || source_precision::text
                               || ':' || source_scale::text
                          from public.instrument_measurement
                         where tenant_id = %s and message_id = %s
                        """,
                        (self.tenant_a, f"{run_id}:instrument"),
                    ),
                    expected,
                )

    def test_canonical_digest_drift_fails_closed_on_reload(self) -> None:
        run_id, specimen_id = self.identity("DIGEST")
        created = self.post(
            TestClient(create_app(self.service())),
            "/api/workbench/golden-runs",
            self.payload(run_id, specimen_id),
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.run_sql(
            """
            update public.specimen
               set canonical_sha256 = repeat('0', 64)
             where tenant_id = %s and specimen_id = %s
            """,
            (self.tenant_a, specimen_id),
        )
        with self.assertRaisesRegex(RuntimeError, "stored digest"):
            self.service().specimen(self.tenant_a, specimen_id)


if __name__ == "__main__":
    unittest.main()
