from __future__ import annotations

import unittest
from datetime import UTC, datetime
from typing import Any

from lims_eln_implementation.application import InstrumentReviewRequired
from lims_eln_implementation.model import canonical_digest
from lims_eln_implementation.security import (
    SignedTenantContext,
    TenantSessionBindingError,
)
from lims_eln_implementation.workbench.postgres import (
    PostgresWorkbenchService,
    _operation_contract,
    _receipt_id,
    _transaction,
)

NOW = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)
VALID_RAW = b'{"analyte":"synthetic-dna","value":"12.5","unit":"ng/uL"}'
QUARANTINED_RAW = b'{"analyte":" ","value":"12.5","unit":"ng/uL"}'


def context_for(tenant_id: str) -> SignedTenantContext:
    return SignedTenantContext(
        tenant_id=tenant_id,
        subject_id="svc-golden-specimen-workbench",
        key_id="synthetic-test-v1",
        issued_at_epoch=1_788_274_000,
        expires_at_epoch=1_788_274_600,
        nonce="synthetic_nonce_0001",
        signature_hex="a" * 64,
    )


class RecordingCursor:
    def __init__(self, tenant_id: str = "SYN-TENANT-A") -> None:
        self.tenant_id = tenant_id
        self.operations: list[tuple[str, tuple[Any, ...]]] = []
        self.last_operation = ""
        self.closed = False

    def execute(self, operation: str, parameters: tuple[Any, ...] = ()) -> None:
        self.last_operation = " ".join(operation.split()).lower()
        self.operations.append((self.last_operation, parameters))

    def fetchone(self) -> tuple[Any, ...] | None:
        operation = self.last_operation
        if "bind_tenant_context" in operation:
            return (self.tenant_id,)
        if "workbench_migration_head" in operation:
            return ("008",)
        if "insert into public.bounded_call_invocation" in operation:
            return (
                "in_progress",
                "11111111-1111-4111-8111-111111111111",
                1,
            )
        if "record_custody_transfer" in operation:
            return (1,)
        if "update public.bounded_call_invocation" in operation:
            return ("SYN-RUN-001",)
        return None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return []

    def close(self) -> None:
        self.closed = True


class RecordingConnection:
    def __init__(self, cursor: RecordingCursor | None = None) -> None:
        self.recording_cursor = cursor or RecordingCursor()
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self) -> RecordingCursor:
        return self.recording_cursor

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


class PostgresTransactionTests(unittest.TestCase):
    def test_receipt_identity_uses_an_unambiguous_structured_coordinate(self) -> None:
        self.assertNotEqual(_receipt_id("A:B", "C"), _receipt_id("A", "B:C"))

    def test_transaction_commits_and_releases_owned_resources(self) -> None:
        connection = RecordingConnection()
        with _transaction(lambda: connection) as cursor:
            cursor.execute("select 1")
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)
        self.assertTrue(connection.recording_cursor.closed)
        self.assertTrue(connection.closed)

    def test_transaction_rolls_back_and_releases_after_late_failure(self) -> None:
        connection = RecordingConnection()
        with (
            self.assertRaisesRegex(OSError, "late write failure"),
            _transaction(lambda: connection) as cursor,
        ):
            cursor.execute("insert into candidate values (1)")
            raise OSError("late write failure")
        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)
        self.assertTrue(connection.recording_cursor.closed)
        self.assertTrue(connection.closed)


class PostgresWorkbenchAdapterTests(unittest.TestCase):
    def service(
        self,
        connection: RecordingConnection,
        *,
        failure_probe: Any = None,
    ) -> PostgresWorkbenchService:
        return PostgresWorkbenchService(
            lambda: connection,
            tenant_context_provider=context_for,
            failure_probe=failure_probe,
        )

    def arguments(self, raw: bytes) -> dict[str, Any]:
        return {
            "run_id": "SYN-RUN-001",
            "tenant_id": "SYN-TENANT-A",
            "specimen_id": "SYN-SPECIMEN-0001",
            "actor_id": "SYN-ACTOR-01",
            "scientist_id": "SYN-SCIENTIST-01",
            "quality_actor_id": "SYN-QUALITY-01",
            "occurred_at": NOW,
            "raw_instrument_json": raw,
            "vendor_payload": {"status": "under_review"},
        }

    def test_quarantine_commits_named_recovery_state_after_tenant_binding(self) -> None:
        connection = RecordingConnection()
        with self.assertRaises(InstrumentReviewRequired):
            self.service(connection).run_golden_specimen(**self.arguments(QUARANTINED_RAW))
        operations = [operation for operation, _ in connection.recording_cursor.operations]
        self.assertEqual(
            operations[:2],
            [
                "set transaction isolation level repeatable read",
                next(operation for operation in operations if "bind_tenant_context" in operation),
            ],
        )
        self.assertTrue(
            any("set state = 'recovery_required'" in operation for operation in operations)
        )
        self.assertTrue(
            any(
                "lease_token = %s::uuid and fencing_token = %s" in operation
                and "lease_expires_at_utc > clock_timestamp()" in operation
                for operation in operations
            )
        )
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)

    def test_signed_subject_must_match_the_receipt_caller(self) -> None:
        connection = RecordingConnection()
        service = PostgresWorkbenchService(
            lambda: connection,
            tenant_context_provider=lambda tenant_id: SignedTenantContext(
                tenant_id=tenant_id,
                subject_id="another-workload",
                key_id="synthetic-test-v1",
                issued_at_epoch=1_788_274_000,
                expires_at_epoch=1_788_274_600,
                nonce="synthetic_nonce_0002",
                signature_hex="b" * 64,
            ),
        )
        with self.assertRaisesRegex(TenantSessionBindingError, "another workload"):
            service.run_golden_specimen(**self.arguments(VALID_RAW))
        self.assertEqual(connection.recording_cursor.operations, [])
        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 0)

    def test_unexpected_precommit_failure_rolls_back_complete_candidate(self) -> None:
        connection = RecordingConnection()

        def fail(label: str) -> None:
            if label == "after_materialization":
                raise OSError("late materialization failure")

        with self.assertRaisesRegex(OSError, "late materialization failure"):
            MissingQualityService(
                lambda: connection,
                tenant_context_provider=context_for,
                failure_probe=fail,
            ).run_golden_specimen(**self.arguments(VALID_RAW))
        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)
        self.assertTrue(connection.recording_cursor.closed)
        self.assertTrue(connection.closed)


class MissingQualityService(PostgresWorkbenchService):
    @staticmethod
    def specimen_document(
        tenant_id: str,
        specimen_id: str,
    ) -> dict[str, Any]:
        event_base = {
            "event_id": "event",
            "aggregate_version": 4,
            "actor_id": "SYN-SCIENTIST-01",
            "command_digest": "0" * 64,
            "occurred_at": NOW.isoformat(),
            "reason_code": None,
        }
        return {
            "tenant_id": tenant_id,
            "specimen_id": specimen_id,
            "state": "released",
            "version": 5,
            "attributes": {},
            "events": [
                {
                    **event_base,
                    "aggregate_version": 1,
                    "event_type": "specimen.registered",
                    "actor_id": "SYN-ACTOR-01",
                    "command_id": "SYN-RUN-001:register",
                    "payload": {"specimen_type": "synthetic_plasma"},
                },
                {
                    **event_base,
                    "event_type": "specimen.submit_review",
                    "command_id": "SYN-RUN-001:submit-review",
                    "payload": {
                        "review_id": "SYN-REVIEW-001",
                        "decision": "accepted",
                    },
                },
                {
                    **event_base,
                    "aggregate_version": 5,
                    "event_type": "specimen.release",
                    "actor_id": "SYN-QUALITY-01",
                    "command_id": "SYN-RUN-001:release",
                    "payload": {"approval_receipt_id": "SYN-APPROVAL-001"},
                },
            ],
            "custody": {"location": "SYN-LAB-A/RECEIVING", "version": 1},
            "instrument_receipts": [
                {
                    "message_id": "SYN-RUN-001:instrument",
                    "raw_sha256": "1" * 64,
                    "normalized_digest": "2" * 64,
                    "normalized_observation": {
                        "analyte": "SYNTHETIC-DNA",
                        "value": "12.5",
                        "unit": "ng/uL",
                    },
                }
            ],
            "projection": {},
        }

    def _load_specimen(
        self,
        cursor: Any,
        tenant_id: str,
        specimen_id: str,
    ) -> dict[str, Any]:
        return self.specimen_document(tenant_id, specimen_id)


class ReadCursor(RecordingCursor):
    def fetchone(self) -> tuple[Any, ...] | None:
        if "bind_tenant_context" in self.last_operation:
            return (self.tenant_id,)
        coordinate = {
            "coordinate_version": "2.0.0",
            "mode": "initial",
            "run_id": "SYN-RUN-001",
            "recovery_of_run_id": None,
            "specimen_id": "SYN-SPECIMEN-0001",
            "actor_id": "SYN-ACTOR-01",
            "reviewer_id": "SYN-SCIENTIST-01",
            "quality_actor_id": "SYN-QUALITY-01",
            "instrument_message_id": "SYN-RUN-001:instrument",
            "raw_sha256": "1" * 64,
            "normalized_sha256": "2" * 64,
            "receipt_id": _receipt_id("SYN-TENANT-A", "SYN-RUN-001"),
            "specimen_snapshot": MissingQualityService.specimen_document(
                "SYN-TENANT-A",
                "SYN-SPECIMEN-0001",
            ),
            "outbox_topics": ["specimen.custody.changed"],
        }
        result_digest = canonical_digest(coordinate)
        operation = _operation_contract("initial")
        payload_digest = "4" * 64
        resource_ids = ["specimen:SYN-SPECIMEN-0001"]
        invocation_digest = canonical_digest(
            {
                "caller_id": "svc-golden-specimen-workbench",
                "actor_id": "SYN-ACTOR-01",
                "tenant_id": "SYN-TENANT-A",
                "operation_name": operation[0],
                "operation_version": operation[1],
                "operation_contract_digest": operation[2],
                "resource_ids": resource_ids,
                "payload_digest": payload_digest,
            }
        )
        if "from public.bounded_call_invocation as invocation" in self.last_operation:
            return (
                coordinate,
                invocation_digest,
                *operation,
                result_digest,
            )
        if "from public.bounded_call_receipt" in self.last_operation:
            return (
                coordinate["receipt_id"],
                "svc-golden-specimen-workbench",
                "SYN-ACTOR-01",
                *operation,
                "idempotent_narrow_write",
                resource_ids,
                payload_digest,
                invocation_digest,
                "succeeded",
                "operation_completed",
                "reference:svc-golden-specimen-workbench",
                "reference-hour",
                result_digest,
            )
        return super().fetchone()


class StoredProjectionTests(unittest.TestCase):
    def test_missing_stored_quality_decision_fails_closed(self) -> None:
        connection = RecordingConnection(ReadCursor())
        service = MissingQualityService(
            lambda: connection,
            tenant_context_provider=context_for,
        )
        with self.assertRaisesRegex(RuntimeError, "quality_flag"):
            service.observation("SYN-TENANT-A", "SYN-RUN-001")
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)


if __name__ == "__main__":
    unittest.main()
