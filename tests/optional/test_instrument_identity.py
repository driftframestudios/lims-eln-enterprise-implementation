"""Exercise independent ingress identities with the optional pytest profile."""

from dataclasses import replace

import pytest

from lims_eln_implementation.instrument import (
    IngressDisposition,
    InstrumentEnvelope,
    InstrumentIngress,
)
from tests.helpers import NOW


@pytest.mark.parametrize(
    ("tenant_id", "message_id"),
    [
        pytest.param("SYN-TENANT-A", "SYN-MSG-002", id="new-message-in-same-tenant"),
        pytest.param("SYN-TENANT-B", "SYN-MSG-001", id="same-message-in-other-tenant"),
    ],
)
def test_changing_one_identity_component_admits_a_new_message(
    tenant_id: str, message_id: str
) -> None:
    ingress = InstrumentIngress()
    original = InstrumentEnvelope(
        tenant_id="SYN-TENANT-A",
        message_id="SYN-MSG-001",
        specimen_id="SYN-SPECIMEN-01",
        instrument_id="SYN-INSTRUMENT-01",
        captured_at=NOW,
        media_type="application/json",
        raw_bytes=b'{"analyte":"A","value":"1.250","unit":"ng/uL"}',
    )
    first = ingress.ingest(original)
    second = ingress.ingest(replace(original, tenant_id=tenant_id, message_id=message_id))

    assert first.disposition == IngressDisposition.ACCEPTED
    assert second.disposition == IngressDisposition.ACCEPTED
    assert ingress.result(original.tenant_id, original.message_id) == first
    assert ingress.result(tenant_id, message_id) == second
