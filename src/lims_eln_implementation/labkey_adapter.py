"""Credential-free LabKey JSON API adapter exemplar.

The adapter targets LabKey's documented ``query/selectRows``,
``query/insertRows``, and ``query/updateRows`` API family. An injected
transport owns TLS, workload authentication, connection pooling, and endpoint
configuration; the repository carries no credential value.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import quote

from .model import canonical_digest
from .ports import ExternalRecord, VendorRevisionConflict
from .production_adapters import (
    AmbiguousVendorWrite,
    RetryableVendorRead,
    VendorRecordPage,
    VendorSdkWrite,
)


@dataclass(frozen=True, slots=True)
class LabKeyHttpResponse:
    status_code: int
    headers: Mapping[str, str]
    document: Mapping[str, Any]


class LabKeyHttpTransport(Protocol):
    """Preconfigured HTTP transport with an approved destination allowlist."""

    def request(
        self,
        *,
        method: str,
        path: str,
        headers: Mapping[str, str],
        query: Mapping[str, str] | None = None,
        document: Mapping[str, Any] | None = None,
        timeout_seconds: float,
    ) -> LabKeyHttpResponse: ...

    def close(self) -> None: ...


class LabKeyJsonApiClient:
    """Versioned LabKey query API implementation behind the vendor SDK seam."""

    sdk_name = "labkey-json-api-reference"
    sdk_version = "0.3.1"
    api_version = "query-v1"

    def __init__(
        self,
        *,
        transport: LabKeyHttpTransport,
        authorization_header: Callable[[], str],
        container_path: str,
        schema_name: str,
        query_name: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        for name, value in (
            ("container_path", container_path),
            ("schema_name", schema_name),
            ("query_name", query_name),
        ):
            if not value.strip():
                raise ValueError(f"{name} requires a configured value")
        if timeout_seconds <= 0:
            raise ValueError("LabKey timeout requires a positive duration")
        self._transport = transport
        self._authorization_header = authorization_header
        self._container_path = container_path.strip("/")
        self._schema_name = schema_name
        self._query_name = query_name
        self._timeout_seconds = timeout_seconds

    def write_record(
        self,
        *,
        tenant_id: str,
        external_identity: str,
        expected_revision: int,
        payload: Mapping[str, Any],
        request_id: str,
    ) -> VendorSdkWrite:
        endpoint = "insertRows" if expected_revision == 0 else "updateRows"
        response = self._request(
            method="POST",
            action=endpoint,
            request_id=request_id,
            document={
                "schemaName": self._schema_name,
                "queryName": self._query_name,
                "auditBehavior": "DETAILED",
                "rows": [
                    {
                        "tenant_id": tenant_id,
                        "external_identity": external_identity,
                        "revision": expected_revision + 1,
                        "canonical_sha256": canonical_digest(dict(payload)),
                        "payload": dict(payload),
                    }
                ],
            },
        )
        if response.status_code in {429, 500, 502, 503, 504}:
            raise AmbiguousVendorWrite(
                "LabKey write requires authoritative readback by external identity"
            )
        if response.status_code == 409:
            raise VendorRevisionConflict(
                "LabKey record advanced; read authoritative state and replan"
            )
        self._require_success(response, operation="write")
        rows = response.document.get("rows")
        if not isinstance(rows, list) or len(rows) != 1:
            raise AmbiguousVendorWrite(
                "LabKey write response requires one attributable row"
            )
        row = rows[0]
        if not isinstance(row, Mapping):
            raise AmbiguousVendorWrite("LabKey write row requires an object")
        identity = row.get("external_identity")
        revision = row.get("revision")
        if identity != external_identity or revision != expected_revision + 1:
            raise AmbiguousVendorWrite(
                "LabKey write confirmation differs from the requested identity or revision"
            )
        trace_id = response.headers.get("X-Request-ID", request_id)
        return VendorSdkWrite(external_identity, revision, trace_id)

    def read_record(
        self,
        *,
        tenant_id: str,
        external_identity: str,
    ) -> ExternalRecord | None:
        response = self._select(
            tenant_id=tenant_id,
            external_identity=external_identity,
            offset=0,
            page_size=2,
        )
        rows = self._rows(response)
        if not rows:
            return None
        if len(rows) != 1:
            raise RuntimeError(
                "LabKey external identity requires one tenant-scoped record"
            )
        return self._decode_row(rows[0], tenant_id=tenant_id)

    def list_records_page(
        self,
        *,
        tenant_id: str,
        cursor: str | None,
        page_size: int,
    ) -> VendorRecordPage:
        try:
            offset = int(cursor) if cursor is not None else 0
        except ValueError as error:
            raise ValueError("LabKey cursor requires a nonnegative row offset") from error
        if offset < 0:
            raise ValueError("LabKey cursor requires a nonnegative row offset")
        response = self._select(
            tenant_id=tenant_id,
            external_identity=None,
            offset=offset,
            page_size=page_size,
        )
        rows = self._rows(response)
        records = tuple(self._decode_row(row, tenant_id=tenant_id) for row in rows)
        row_count = response.document.get("rowCount")
        if not isinstance(row_count, int) or row_count < len(rows):
            raise RuntimeError("LabKey pagination requires a valid rowCount")
        next_offset = offset + len(rows)
        return VendorRecordPage(
            records=records,
            next_cursor=str(next_offset) if next_offset < row_count else None,
        )

    def close(self) -> None:
        self._transport.close()

    def _select(
        self,
        *,
        tenant_id: str,
        external_identity: str | None,
        offset: int,
        page_size: int,
    ) -> LabKeyHttpResponse:
        query = {
            "schemaName": self._schema_name,
            "query.queryName": self._query_name,
            "query.tenant_id~eq": tenant_id,
            "query.offset": str(offset),
            "query.maxRows": str(page_size),
        }
        if external_identity is not None:
            query["query.external_identity~eq"] = external_identity
        response = self._request(
            method="GET",
            action="selectRows",
            request_id=None,
            query=query,
        )
        if response.status_code in {429, 500, 502, 503, 504}:
            raise RetryableVendorRead(
                "LabKey read can retry within the configured bounded policy"
            )
        self._require_success(response, operation="read")
        return response

    def _request(
        self,
        *,
        method: str,
        action: str,
        request_id: str | None,
        query: Mapping[str, str] | None = None,
        document: Mapping[str, Any] | None = None,
    ) -> LabKeyHttpResponse:
        authorization = self._authorization_header()
        if not authorization or "\n" in authorization or "\r" in authorization:
            raise PermissionError(
                "LabKey authorization requires a safe runtime header value"
            )
        headers = {
            "Authorization": authorization,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if request_id is not None:
            headers["X-Request-ID"] = request_id
        path = (
            f"/{quote(self._container_path, safe='/')}/query-"
            f"{action}.api"
        )
        return self._transport.request(
            method=method,
            path=path,
            headers=headers,
            query=query,
            document=document,
            timeout_seconds=self._timeout_seconds,
        )

    @staticmethod
    def _require_success(
        response: LabKeyHttpResponse,
        *,
        operation: str,
    ) -> None:
        if response.status_code in {401, 403}:
            raise PermissionError(
                f"LabKey {operation} requires an authorized workload identity"
            )
        if not 200 <= response.status_code < 300:
            raise RuntimeError(
                f"LabKey {operation} returned status {response.status_code}"
            )

    @staticmethod
    def _rows(response: LabKeyHttpResponse) -> list[Mapping[str, Any]]:
        rows = response.document.get("rows")
        if not isinstance(rows, list) or not all(
            isinstance(row, Mapping) for row in rows
        ):
            raise RuntimeError("LabKey response rows require an object list")
        return rows

    @staticmethod
    def _decode_row(
        row: Mapping[str, Any],
        *,
        tenant_id: str,
    ) -> ExternalRecord:
        observed_tenant = row.get("tenant_id")
        identity = row.get("external_identity")
        revision = row.get("revision")
        digest = row.get("canonical_sha256")
        payload = row.get("payload")
        if (
            observed_tenant != tenant_id
            or not isinstance(identity, str)
            or not isinstance(revision, int)
            or revision < 1
            or not isinstance(digest, str)
            or len(digest) != 64
            or not isinstance(payload, Mapping)
        ):
            raise RuntimeError(
                "LabKey row requires tenant, identity, revision, digest, and payload"
            )
        return ExternalRecord(
            tenant_id=tenant_id,
            external_identity=identity,
            revision=revision,
            canonical_digest=digest,
            payload=dict(payload),
        )
