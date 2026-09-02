from __future__ import annotations

import unittest

from lims_eln_implementation.labkey_adapter import (
    LabKeyHttpResponse,
    LabKeyJsonApiClient,
)
from lims_eln_implementation.production_adapters import (
    RetryPolicy,
    VersionBand,
    VersionedVendorGatewayAdapter,
)


class FakeTransport:
    def __init__(self, responses: list[LabKeyHttpResponse]) -> None:
        self.responses = responses
        self.requests: list[dict[str, object]] = []
        self.closed = False

    def request(self, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0)

    def close(self) -> None:
        self.closed = True


def row(identity: str, revision: int = 1) -> dict[str, object]:
    return {
        "tenant_id": "SYN-TENANT-A",
        "external_identity": identity,
        "revision": revision,
        "canonical_sha256": "a" * 64,
        "payload": {"status": "under_review"},
    }


class LabKeyAdapterTests(unittest.TestCase):
    def client(self, transport: FakeTransport) -> LabKeyJsonApiClient:
        return LabKeyJsonApiClient(
            transport=transport,
            authorization_header=lambda: "Bearer SYN-RUNTIME-TOKEN",
            container_path="synthetic/laboratory",
            schema_name="lims",
            query_name="specimen_projection",
        )

    def test_write_binds_identity_revision_and_request_header(self) -> None:
        transport = FakeTransport(
            [
                LabKeyHttpResponse(
                    200,
                    {"X-Request-ID": "SYN-REQUEST-1"},
                    {"rows": [row("SYN-SPECIMEN-1")]},
                )
            ]
        )
        result = self.client(transport).write_record(
            tenant_id="SYN-TENANT-A",
            external_identity="SYN-SPECIMEN-1",
            expected_revision=0,
            payload={"status": "under_review"},
            request_id="SYN-REQUEST-1",
        )

        self.assertEqual((result.external_identity, result.revision), ("SYN-SPECIMEN-1", 1))
        self.assertEqual(
            transport.requests[0]["headers"]["X-Request-ID"],  # type: ignore[index]
            "SYN-REQUEST-1",
        )
        self.assertIn("query-insertRows.api", transport.requests[0]["path"])

    def test_gateway_retries_safe_read_with_bounded_backoff(self) -> None:
        first = FakeTransport([LabKeyHttpResponse(503, {}, {})])
        second = FakeTransport(
            [LabKeyHttpResponse(200, {}, {"rows": [row("SYN-SPECIMEN-1")]})]
        )
        transports = iter((first, second))
        delays: list[float] = []
        adapter = VersionedVendorGatewayAdapter(
            vendor_name="labkey",
            client_factory=lambda: self.client(next(transports)),
            sdk_name="labkey-json-api-reference",
            qualified_sdk_band=VersionBand(
                "labkey-json-api-reference", "0.3.1", "0.4.0"
            ),
            required_api_version="query-v1",
            retry_policy=RetryPolicy(
                max_attempts=2,
                initial_delay_seconds=0.01,
                maximum_delay_seconds=0.01,
            ),
            sleep=delays.append,
        )

        record = adapter.read(
            tenant_id="SYN-TENANT-A",
            external_identity="SYN-SPECIMEN-1",
        )

        self.assertIsNotNone(record)
        self.assertEqual(delays, [0.01])
        self.assertTrue(first.closed)
        self.assertTrue(second.closed)

    def test_pagination_advances_by_bounded_offset(self) -> None:
        page_one = FakeTransport(
            [
                LabKeyHttpResponse(
                    200,
                    {},
                    {
                        "rows": [row("SYN-SPECIMEN-1")],
                        "rowCount": 2,
                    },
                )
            ]
        )
        page_two = FakeTransport(
            [
                LabKeyHttpResponse(
                    200,
                    {},
                    {
                        "rows": [row("SYN-SPECIMEN-2")],
                        "rowCount": 2,
                    },
                )
            ]
        )
        transports = iter((page_one, page_two))
        adapter = VersionedVendorGatewayAdapter(
            vendor_name="labkey",
            client_factory=lambda: self.client(next(transports)),
            sdk_name="labkey-json-api-reference",
            qualified_sdk_band=VersionBand(
                "labkey-json-api-reference", "0.3.1", "0.4.0"
            ),
            required_api_version="query-v1",
            sleep=lambda _seconds: None,
        )

        records = tuple(adapter.iter_records(tenant_id="SYN-TENANT-A", page_size=1))

        self.assertEqual(
            [record.external_identity for record in records],
            ["SYN-SPECIMEN-1", "SYN-SPECIMEN-2"],
        )
        self.assertEqual(
            page_two.requests[0]["query"]["query.offset"],  # type: ignore[index]
            "1",
        )


if __name__ == "__main__":
    unittest.main()
