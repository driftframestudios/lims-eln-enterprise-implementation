from __future__ import annotations

import json
import unittest

from lims_eln_implementation.custody import CustodyService
from lims_eln_implementation.instrument import (
    IngressDisposition,
    InstrumentEnvelope,
    InstrumentIngress,
)
from lims_eln_implementation.model import DomainError
from lims_eln_implementation.store import (
    InMemoryOutbox,
    OutboxContentCollision,
    OutboxMessage,
)

from helpers import NOW


class CustodyTests(unittest.TestCase):
    def test_transfer_updates_position_and_outbox_together(self) -> None:
        outbox = InMemoryOutbox()
        service = CustodyService(outbox)
        position = service.place(
            tenant_id="SYN-TENANT-A",
            specimen_id="SYN-SPECIMEN-0001",
            location="SYN-FREEZER-A/SHELF-2",
            custodian_id="SYN-ACTOR-01",
            expected_version=0,
            transfer_id="SYN-TRANSFER-001",
            occurred_at=NOW,
        )
        self.assertEqual(position.version, 1)
        self.assertEqual(service.current("SYN-TENANT-A", "SYN-SPECIMEN-0001"), position)
        self.assertEqual(len(outbox.messages), 1)
        self.assertEqual(outbox.messages[0].aggregate_version, 1)
        payload = json.loads(outbox.messages[0].payload_json)
        self.assertEqual(payload["transfer_id"], "SYN-TRANSFER-001")
        self.assertEqual(payload["to_location"], "SYN-FREEZER-A/SHELF-2")
        self.assertEqual(len(service.history("SYN-TENANT-A", "SYN-SPECIMEN-0001")), 1)

    def test_exact_transfer_replay_returns_recorded_outcome_once(self) -> None:
        outbox = InMemoryOutbox()
        service = CustodyService(outbox)
        arguments = {
            "tenant_id": "SYN-TENANT-A",
            "specimen_id": "SYN-SPECIMEN-0001",
            "location": "SYN-FREEZER-A/SHELF-2",
            "custodian_id": "SYN-ACTOR-01",
            "expected_version": 0,
            "transfer_id": "SYN-TRANSFER-001",
            "occurred_at": NOW,
        }
        first = service.place(**arguments)
        replay = service.place(**arguments)
        self.assertEqual(replay, first)
        self.assertEqual(len(service.history("SYN-TENANT-A", "SYN-SPECIMEN-0001")), 1)
        self.assertEqual(len(outbox.messages), 1)

    def test_changed_transfer_content_routes_to_review(self) -> None:
        service = CustodyService(InMemoryOutbox())
        service.place(
            tenant_id="SYN-TENANT-A",
            specimen_id="SYN-SPECIMEN-0001",
            location="SYN-RECEIVING",
            custodian_id="SYN-ACTOR-01",
            expected_version=0,
            transfer_id="SYN-TRANSFER-001",
            occurred_at=NOW,
        )
        with self.assertRaisesRegex(DomainError, "different content"):
            service.place(
                tenant_id="SYN-TENANT-A",
                specimen_id="SYN-SPECIMEN-0001",
                location="SYN-SECONDARY-FREEZER",
                custodian_id="SYN-ACTOR-01",
                expected_version=0,
                transfer_id="SYN-TRANSFER-001",
                occurred_at=NOW,
            )

    def test_stale_transfer_preserves_current_position(self) -> None:
        service = CustodyService(InMemoryOutbox())
        first = service.place(
            tenant_id="SYN-TENANT-A",
            specimen_id="SYN-SPECIMEN-0001",
            location="SYN-RECEIVING",
            custodian_id="SYN-ACTOR-01",
            expected_version=0,
            transfer_id="SYN-TRANSFER-001",
            occurred_at=NOW,
        )
        with self.assertRaisesRegex(DomainError, "reload"):
            service.place(
                tenant_id="SYN-TENANT-A",
                specimen_id="SYN-SPECIMEN-0001",
                location="SYN-FREEZER",
                custodian_id="SYN-ACTOR-02",
                expected_version=0,
                transfer_id="SYN-TRANSFER-002",
                occurred_at=NOW,
            )
        self.assertEqual(
            service.current("SYN-TENANT-A", "SYN-SPECIMEN-0001"), first
        )

    def test_outbox_failure_rolls_back_custody_position(self) -> None:
        class FailingOutbox(InMemoryOutbox):
            def append(self, message):
                super().append(message)
                raise RuntimeError("synthetic outbox failure")

        outbox = FailingOutbox()
        service = CustodyService(outbox)
        with self.assertRaisesRegex(RuntimeError, "synthetic outbox failure"):
            service.place(
                tenant_id="SYN-TENANT-A",
                specimen_id="SYN-SPECIMEN-0001",
                location="SYN-FREEZER",
                custodian_id="SYN-ACTOR-01",
                expected_version=0,
                transfer_id="SYN-TRANSFER-ATOMIC",
                occurred_at=NOW,
            )

        self.assertIsNone(service.current("SYN-TENANT-A", "SYN-SPECIMEN-0001"))
        self.assertEqual(outbox.messages, [])

    def test_outbox_identity_is_tenant_scoped_and_content_bound(self) -> None:
        outbox = InMemoryOutbox()
        first = OutboxMessage(
            message_id="SYN-MESSAGE-001",
            tenant_id="SYN-TENANT-A",
            topic="synthetic.changed",
            aggregate_id="SYN-AGGREGATE-001",
            aggregate_version=1,
            payload={"value": "first"},
        )
        outbox.append(first)
        outbox.append(first)
        outbox.append(
            OutboxMessage(
                message_id="SYN-MESSAGE-001",
                tenant_id="SYN-TENANT-B",
                topic="synthetic.changed",
                aggregate_id="SYN-AGGREGATE-001",
                aggregate_version=1,
                payload={"value": "first"},
            )
        )
        with self.assertRaisesRegex(OutboxContentCollision, "different content"):
            outbox.append(
                OutboxMessage(
                    message_id="SYN-MESSAGE-001",
                    tenant_id="SYN-TENANT-A",
                    topic="synthetic.changed",
                    aggregate_id="SYN-AGGREGATE-001",
                    aggregate_version=1,
                    payload={"value": "second"},
                )
            )
        self.assertEqual(len(outbox.messages), 2)

    def test_outbox_snapshots_payload_before_caller_mutation(self) -> None:
        source = {"state": "ready"}
        message = OutboxMessage(
            message_id="SYN-MESSAGE-001",
            tenant_id="SYN-TENANT-A",
            topic="synthetic.changed",
            aggregate_id="SYN-AGGREGATE-001",
            aggregate_version=1,
            payload=source,
        )
        digest = message.payload_digest
        source["state"] = "changed"
        self.assertEqual(message.payload_json, '{"state":"ready"}')
        self.assertEqual(message.payload_digest, digest)


class InstrumentIngressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ingress = InstrumentIngress()

    def envelope(
        self, raw: bytes, *, message_id: str = "SYN-INSTRUMENT-MESSAGE-001"
    ) -> InstrumentEnvelope:
        return InstrumentEnvelope(
            tenant_id="SYN-TENANT-A",
            message_id=message_id,
            instrument_id="SYN-INSTRUMENT-01",
            specimen_id="SYN-SPECIMEN-0001",
            captured_at=NOW,
            media_type="application/json",
            raw_bytes=raw,
        )

    def test_valid_message_preserves_raw_digest(self) -> None:
        envelope = self.envelope(
            b'{"analyte":"synthetic-dna","value":"12.5","unit":"ng/uL"}'
        )
        result = self.ingress.ingest(envelope)
        self.assertEqual(result.disposition, IngressDisposition.ACCEPTED)
        self.assertEqual(result.raw_sha256, envelope.raw_sha256)
        self.assertIsNotNone(result.normalized_digest)
        normalized = json.loads(result.normalized_document_json or "{}")
        self.assertEqual(normalized["quantity"]["decimal"], "12.5")
        self.assertEqual(normalized["quantity"]["precision"], 3)
        self.assertEqual(normalized["quantity"]["scale"], 1)
        self.assertEqual(
            normalized["quantity"]["unit_system"],
            "http://unitsofmeasure.org",
        )
        self.assertIsNotNone(result.normalized_observation)
        assert result.normalized_observation is not None
        self.assertEqual(
            result.normalized_observation.to_document(),
            {
                "tenant_id": "SYN-TENANT-A",
                "specimen_id": "SYN-SPECIMEN-0001",
                "instrument_id": "SYN-INSTRUMENT-01",
                "captured_at": NOW.isoformat(),
                "analyte": "SYNTHETIC-DNA",
                "value": "12.5",
                "unit": "ng/uL",
                "raw_sha256": envelope.raw_sha256,
            },
        )

    def test_exact_replay_reuses_normalized_outcome(self) -> None:
        envelope = self.envelope(
            b'{"analyte":"synthetic-dna","value":"12.5","unit":"ng/uL"}'
        )
        first = self.ingress.ingest(envelope)
        replay = self.ingress.ingest(envelope)
        self.assertEqual(replay.disposition, IngressDisposition.REPLAYED)
        self.assertEqual(replay.normalized_observation, first.normalized_observation)
        self.assertEqual(replay.normalized_digest, first.normalized_digest)

    def test_changed_bytes_on_message_identity_enter_quarantine(self) -> None:
        self.ingress.ingest(
            self.envelope(b'{"analyte":"A","value":"1","unit":"ng/uL"}')
        )
        collision = self.ingress.ingest(
            self.envelope(b'{"analyte":"A","value":"2","unit":"ng/uL"}')
        )
        self.assertEqual(collision.disposition, IngressDisposition.QUARANTINED)
        self.assertEqual(collision.reason_code, "message_identity_collision")
        self.assertIn("new source message identity", collision.recovery)

    def test_unsupported_unit_routes_to_scientific_mapping(self) -> None:
        result = self.ingress.ingest(
            self.envelope(b'{"analyte":"A","value":"1","unit":"mystery"}')
        )
        self.assertEqual(result.disposition, IngressDisposition.QUARANTINED)
        self.assertEqual(result.reason_code, "unsupported_unit")
        self.assertIn("scientific review", result.recovery)

    def test_malformed_payload_has_recovery_instruction(self) -> None:
        result = self.ingress.ingest(self.envelope(b"{broken"))
        self.assertEqual(result.reason_code, "malformed_json")
        self.assertIn("repair", result.recovery)

    def test_nonfinite_duplicate_and_structured_values_enter_quarantine(self) -> None:
        examples = {
            "nonfinite": b'{"analyte":"A","value":NaN,"unit":"ng/uL"}',
            "duplicate": b'{"analyte":"A","value":"1","value":"2","unit":"ng/uL"}',
            "structured": b'{"analyte":"A","value":{"n":1},"unit":"ng/uL"}',
            "boolean": b'{"analyte":"A","value":true,"unit":"ng/uL"}',
        }
        for index, (label, raw) in enumerate(examples.items(), start=1):
            with self.subTest(label=label):
                result = self.ingress.ingest(
                    self.envelope(raw, message_id=f"SYN-STRICT-{index}")
                )
                self.assertEqual(result.disposition, IngressDisposition.QUARANTINED)
                self.assertIsNone(result.normalized_digest)

    def test_analyte_and_released_fields_require_profile_conformance(self) -> None:
        object_analyte = self.ingress.ingest(
            self.envelope(
                b'{"analyte":{"code":"A"},"value":"1","unit":"ng/uL"}',
                message_id="SYN-ANALYTE-OBJECT",
            )
        )
        additional_field = self.ingress.ingest(
            self.envelope(
                b'{"analyte":"A","value":"1","unit":"ng/uL","flag":true}',
                message_id="SYN-ADDITIONAL-FIELD",
            )
        )
        self.assertEqual(object_analyte.reason_code, "analyte_requires_mapping")
        self.assertEqual(additional_field.reason_code, "unreleased_fields")

    def test_quantity_precision_is_bounded_by_released_decimal_profile(self) -> None:
        examples = (
            b'{"analyte":"A","value":"0.0000000000000000001","unit":"ng/uL"}',
            b'{"analyte":"A","value":"1E+20","unit":"ng/uL"}',
        )
        for index, raw in enumerate(examples, start=1):
            with self.subTest(index=index):
                result = self.ingress.ingest(
                    self.envelope(
                        raw,
                        message_id=f"SYN-PRECISION-LIMIT-{index}",
                    )
                )
                self.assertEqual(result.reason_code, "quantity_precision_exceeded")

    def test_quarantine_replay_retains_original_decision_and_identity(self) -> None:
        envelope = self.envelope(b"{broken")
        first = self.ingress.ingest(envelope)
        replay = self.ingress.ingest(envelope)
        changed = self.ingress.ingest(
            self.envelope(
                b'{"analyte":"A","value":"1","unit":"ng/uL"}',
                message_id=envelope.message_id,
            )
        )

        self.assertEqual(first.disposition, IngressDisposition.QUARANTINED)
        self.assertEqual(replay.disposition, IngressDisposition.REPLAYED)
        self.assertEqual(replay.reason_code, "malformed_json")
        self.assertEqual(changed.reason_code, "message_identity_collision")


if __name__ == "__main__":
    unittest.main()
