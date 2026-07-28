from __future__ import annotations

import unittest

from lims_eln_implementation.custody import CustodyService
from lims_eln_implementation.instrument import (
    IngressDisposition,
    InstrumentEnvelope,
    InstrumentIngress,
)
from lims_eln_implementation.model import DomainError
from lims_eln_implementation.store import InMemoryOutbox

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

    def test_exact_replay_reuses_normalized_outcome(self) -> None:
        envelope = self.envelope(
            b'{"analyte":"synthetic-dna","value":"12.5","unit":"ng/uL"}'
        )
        first = self.ingress.ingest(envelope)
        replay = self.ingress.ingest(envelope)
        self.assertEqual(replay.disposition, IngressDisposition.REPLAYED)
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


if __name__ == "__main__":
    unittest.main()

