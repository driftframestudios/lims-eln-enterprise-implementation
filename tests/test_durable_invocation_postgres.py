"""Configured ordinary-role proofs for canonical invocation and receipt storage."""

from dataclasses import replace
from datetime import datetime, timezone
import json
import os
import unittest
from uuid import uuid4

from lims_eln_implementation.bounded_caller import (
    CallDecision, CallReceipt, EffectClass, InvocationState, StoredCallOutcome,
)
from lims_eln_implementation.model import canonical_digest
from lims_eln_implementation.production_adapters import (
    DbApiCallReceiptStore, DbApiInvocationLedger, DurableInvocationError, VersionBand,
)
from lims_eln_implementation.security import SignedTenantContext
from tests.test_postgres_integration import signed_context

try:
    import psycopg
except ModuleNotFoundError:
    psycopg = None

ADMIN_DSN = os.environ.get("LIMS_TEST_POSTGRES_ADMIN_DSN")
APP_DSN = os.environ.get("LIMS_TEST_POSTGRES_APP_DSN")


@unittest.skipUnless(
    ADMIN_DSN and APP_DSN and os.environ.get("LIMS_TEST_TENANT_HMAC_HEX") and psycopg,
    "configured PostgreSQL identities and synthetic signing key enable this proof",
)
class DurableInvocationPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tenants = tuple("SYN-LEDGER-" + uuid4().hex for _ in range(2))
        with psycopg.connect(ADMIN_DSN) as connection:
            for tenant in cls.tenants:
                connection.execute(
                    "insert into public.tenant(tenant_id, display_name) values (%s, %s)",
                    (tenant, "Synthetic durable ledger fixture"),
                )

    def scalar(self, statement, parameters=()):
        with psycopg.connect(ADMIN_DSN) as connection:
            return connection.execute(statement, parameters).fetchone()[0]

    def context(self, tenant):
        return SignedTenantContext(**json.loads(signed_context(tenant)))

    def connection(self, *, shadows=False):
        connection = psycopg.connect(APP_DSN)
        if shadows:
            for table in ("bounded_call_invocation", "bounded_call_receipt"):
                connection.execute(
                    f"create temporary table {table} (like public.{table} including all)"
                )
            connection.commit()
        return connection

    def options(self, *, shadows=False):
        return dict(
            connection_factory=lambda: self.connection(shadows=shadows),
            driver_name="psycopg", driver_version=psycopg.__version__,
            qualified_band=VersionBand("psycopg", "3.3.0", "4.0.0"),
            tenant_context_provider=self.context,
        )

    def ledger(self, *, shadows=False):
        return DbApiInvocationLedger(
            **self.options(shadows=shadows), clock=lambda: datetime.now(timezone.utc),
        )

    def reserve(self, ledger):
        call_id = "SYN-LEDGER-CALL-" + uuid4().hex
        reservation = ledger.reserve(
            self.tenants[0], call_id, "a" * 64,
            operation_name="specimen.read", operation_version="1.0.0",
            operation_contract_digest="b" * 64, evaluated_at=datetime.now(timezone.utc),
        )
        return call_id, reservation

    def release(self, ledger, call_id, reservation, **changes):
        arguments = dict(
            tenant_id=self.tenants[0], call_id=call_id, content_digest="a" * 64,
            lease_token=reservation.lease_token, fencing_token=reservation.fencing_token,
        )
        ledger.release(**(arguments | changes))

    def state(self, call_id):
        return self.scalar(
            "select coalesce((select state from public.bounded_call_invocation "
            "where tenant_id=%s and call_id=%s), 'absent')",
            (self.tenants[0], call_id),
        )

    def outcome(self):
        return StoredCallOutcome("1.0.0", "b" * 64, '{"accepted":true}', canonical_digest({"accepted": True}))

    def complete(self, ledger, call_id, reservation):
        ledger.commit(
            self.tenants[0], call_id, "a" * 64, lease_token=reservation.lease_token,
            fencing_token=reservation.fencing_token, outcome=self.outcome(),
        )

    def test_release_uses_the_narrow_routine_and_current_ownership(self):
        ledger = self.ledger()
        call_id, reservation = self.reserve(ledger)
        self.release(ledger, call_id, reservation)
        self.assertEqual(self.state(call_id), "absent")
        self.assertFalse(self.scalar(
            "select has_table_privilege('laboratory_app', 'public.bounded_call_invocation', 'DELETE')"
        ))
        self.assertTrue(self.scalar(
            "select has_function_privilege('laboratory_app', "
            "'public.release_bounded_call_invocation(text,text,text,uuid,bigint)', 'EXECUTE')"
        ))
        self.assertFalse(self.scalar(
            "select has_function_privilege('laboratory_outbox_worker', "
            "'public.release_bounded_call_invocation(text,text,text,uuid,bigint)', 'EXECUTE')"
        ))
        self.assertTrue(self.scalar(
            "select prosecdef and pg_get_userbyid(proowner)='laboratory_owner' "
            "and proconfig=array['search_path=pg_catalog, pg_temp'] "
            "from pg_proc where oid='public.release_bounded_call_invocation(text,text,text,uuid,bigint)'::regprocedure"
        ))

    def test_release_rejects_changed_identity_and_preserves_the_row(self):
        ledger = self.ledger()
        for change in (
            {"tenant_id": self.tenants[1]}, {"content_digest": "c" * 64},
            {"lease_token": str(uuid4())}, {"fencing_token": 2},
        ):
            with self.subTest(field=next(iter(change))):
                call_id, reservation = self.reserve(ledger)
                with self.assertRaises(DurableInvocationError):
                    self.release(ledger, call_id, reservation, **change)
                self.assertEqual(self.state(call_id), "in_progress")
                self.release(ledger, call_id, reservation)

    def test_expired_completed_and_recovery_rows_remain_retained(self):
        ledger = self.ledger()
        for state in ("expired", "completed", "recovery_required"):
            with self.subTest(state=state):
                call_id, reservation = self.reserve(ledger)
                if state == "expired":
                    with psycopg.connect(ADMIN_DSN) as connection:
                        connection.execute(
                            "update public.bounded_call_invocation set lease_expires_at_utc="
                            "clock_timestamp()-interval '1 second' where tenant_id=%s and call_id=%s",
                            (self.tenants[0], call_id),
                        )
                elif state == "completed":
                    self.complete(ledger, call_id, reservation)
                else:
                    ledger.mark_recovery_required(
                        self.tenants[0], call_id, "a" * 64,
                        lease_token=reservation.lease_token, fencing_token=reservation.fencing_token,
                        reason_code="synthetic_uncertain_effect",
                    )
                with self.assertRaises(DurableInvocationError):
                    self.release(ledger, call_id, reservation)
                self.assertEqual(self.state(call_id), "in_progress" if state == "expired" else state)

    def test_temporary_shadows_preserve_canonical_storage_and_replay(self):
        ledger = self.ledger(shadows=True)
        call_id, reservation = self.reserve(ledger)
        self.assertEqual(self.state(call_id), "in_progress")
        self.complete(ledger, call_id, reservation)
        replay = ledger.reserve(
            self.tenants[0], call_id, "a" * 64,
            operation_name="specimen.read", operation_version="1.0.0",
            operation_contract_digest="b" * 64, evaluated_at=datetime.now(timezone.utc),
        )
        self.assertEqual(replay.state, InvocationState.REPLAY)
        self.assertEqual(replay.outcome, self.outcome())
        now = datetime.now(timezone.utc)
        receipt = CallReceipt(
            receipt_id="SYN-RECEIPT-" + uuid4().hex, call_id=call_id,
            caller_id="SYN-CALLER", actor_id="SYN-ACTOR", tenant_id=self.tenants[0],
            operation_name="specimen.read", operation_version="1.0.0",
            operation_contract_digest="b" * 64, effect_class=EffectClass.READ,
            resource_ids=("specimen:SYN-LEDGER",), payload_digest="a" * 64,
            invocation_digest="a" * 64, decision=CallDecision.SUCCEEDED,
            reason_code="operation_completed", grant_id="SYN-GRANT",
            budget_window_id="SYN-WINDOW", approval_id=None,
            result_digest=self.outcome().result_digest, requested_at=now, recorded_at=now,
        )
        DbApiCallReceiptStore(**self.options(shadows=True)).append(receipt)
        self.assertEqual(self.scalar(
            "select count(*) from public.bounded_call_receipt where receipt_id=%s", (receipt.receipt_id,)
        ), 1)
        call_id, reservation = self.reserve(ledger)
        self.release(ledger, call_id, reservation)
        self.assertEqual(self.state(call_id), "absent")

    def test_stale_completion_preserves_owned_reservation(self):
        ledger = self.ledger()
        call_id, reservation = self.reserve(ledger)
        with self.assertRaises(DurableInvocationError):
            self.complete(ledger, call_id, replace(reservation, fencing_token=2))
        self.assertEqual(self.state(call_id), "in_progress")
        self.complete(ledger, call_id, reservation)
        self.assertEqual(self.state(call_id), "completed")
