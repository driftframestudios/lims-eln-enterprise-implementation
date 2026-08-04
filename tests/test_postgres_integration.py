"""Configured PostgreSQL proofs for tenant, custody, and outbox invariants."""

from __future__ import annotations

from hashlib import sha256
import hmac
import json
import os
import shutil
import subprocess
import time
import unittest
from uuid import uuid4

from lims_eln_implementation.security import tenant_context_signing_message


ADMIN_DSN = os.environ.get("LIMS_TEST_POSTGRES_ADMIN_DSN")
APP_DSN = os.environ.get("LIMS_TEST_POSTGRES_APP_DSN")
HMAC_KEY_HEX = os.environ.get("LIMS_TEST_TENANT_HMAC_HEX")


def signed_context(
    tenant_id: str,
    *,
    issued_offset_seconds: int = 0,
    expires_offset_seconds: int = 300,
    signature_tenant_id: str | None = None,
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
        subject_id="SYN-CI-SERVICE-IDENTITY",
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
            "subject_id": "SYN-CI-SERVICE-IDENTITY",
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
    ADMIN_DSN and APP_DSN and HMAC_KEY_HEX and shutil.which("psql"),
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

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        suffix = uuid4().hex[:10].upper()
        cls.tenant_a = f"SYN-LIVE-A-{suffix}"
        cls.tenant_b = f"SYN-LIVE-B-{suffix}"
        cls.specimen = f"SYN-LIVE-SPECIMEN-{suffix}"
        assert ADMIN_DSN is not None
        cls.run_sql(
            ADMIN_DSN,
            """
            insert into tenant (tenant_id, display_name)
            values (:'tenant_a', 'Synthetic live tenant A'),
                   (:'tenant_b', 'Synthetic live tenant B');
            insert into specimen (
                tenant_id, specimen_id, lifecycle_state, aggregate_version,
                canonical_document, canonical_sha256, updated_at_utc
            ) values
                (:'tenant_a', :'specimen', 'registered', 1, '{}'::jsonb,
                 repeat('0', 64), clock_timestamp()),
                (:'tenant_b', :'specimen', 'registered', 1, '{}'::jsonb,
                 repeat('0', 64), clock_timestamp());
            """,
            variables={
                "tenant_a": cls.tenant_a,
                "tenant_b": cls.tenant_b,
                "specimen": cls.specimen,
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
                "begin; select set_config('app.tenant_id', :'tenant', true); "
                "select count(*) from tenant; commit;",
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
                raw_sha256, normalized_sha256
            ) values (
                :'tenant', :'measurement', :'message', :'specimen',
                'DNA_CONCENTRATION', 12.123456789012345678, 20, 18,
                'ng/uL', 'http://unitsofmeasure.org',
                '2026-08-04T12:00:00Z', repeat('1', 64), repeat('2', 64)
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
                raw_sha256, normalized_sha256
            ) values (
                :'tenant', :'measurement', :'message', :'specimen',
                'DNA_COPIES', 0.1234567890123456789, 20, 18,
                '{copies}/uL', 'http://unitsofmeasure.org',
                '2026-08-04T12:00:00Z', repeat('1', 64), repeat('3', 64)
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
                "'{\"state\":\"ready\"}'::jsonb, "
                "encode(public.digest(convert_to("
                "'{\"state\":\"ready\"}'::jsonb::text, 'UTF8'), 'sha256'), 'hex'))",
            )

        assert ADMIN_DSN is not None
        context = signed_context(self.tenant_a)
        changed = self.run_sql(
            ADMIN_DSN,
            "begin; select laboratory_security.bind_tenant_context(:'context'::jsonb); "
            "set local role laboratory_owner; "
            "update transactional_outbox "
            "set payload = '{\"state\":\"changed\"}'::jsonb, "
            "payload_sha256 = encode(public.digest(convert_to("
            "'{\"state\":\"changed\"}'::jsonb::text, 'UTF8'), 'sha256'), 'hex') "
            "where message_id = :'message'; commit;",
            variables={"context": context, "message": message_id},
            check=False,
        )
        self.assertNotEqual(changed.returncode, 0)
        self.assertIn("immutable", changed.stderr.lower())


if __name__ == "__main__":
    unittest.main()
