"""Vendor SDK seams backed by qualified versions and Tenacity retry policy."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Protocol

from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from .ports import ExternalRecord, VendorGateway, WriteCertainty, WriteResult


class AdapterVersionError(RuntimeError):
    """A configured SDK is outside its qualified version band."""


class ResourceReleaseError(RuntimeError):
    """An adapter resource failed its explicit release contract."""


class RetryableVendorRead(RuntimeError):
    """A read failed before yielding an authoritative vendor response."""


class AmbiguousVendorWrite(RuntimeError):
    """A vendor write may have reached its material-effect boundary."""


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    initial_delay_seconds: float = 0.05
    maximum_delay_seconds: float = 1.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("retry policy requires at least one attempt")
        if (
            self.initial_delay_seconds < 0
            or self.maximum_delay_seconds < self.initial_delay_seconds
        ):
            raise ValueError("retry delays require an ordered nonnegative range")


class VendorRateGate(Protocol):
    def acquire(self, *, operation: str) -> None: ...


class OpenVendorRateGate:
    """Default gate when deployment infrastructure owns rate limiting."""

    def acquire(self, *, operation: str) -> None:
        if not operation:
            raise ValueError("rate-gate operation requires a name")


_RELEASED_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = _RELEASED_VERSION.fullmatch(value)
    if match is None:
        raise AdapterVersionError(
            f"version {value!r} requires a complete released major.minor.patch coordinate"
        )
    return tuple(int(part) for part in match.groups())


@dataclass(frozen=True, slots=True)
class VersionBand:
    component: str
    minimum_inclusive: str
    maximum_exclusive: str

    def require(self, observed: str) -> None:
        minimum = _version_tuple(self.minimum_inclusive)
        maximum = _version_tuple(self.maximum_exclusive)
        current = _version_tuple(observed)
        if not minimum <= current < maximum:
            raise AdapterVersionError(
                f"{self.component} {observed} is outside the qualified band "
                f"[{self.minimum_inclusive}, {self.maximum_exclusive})"
            )


@dataclass(frozen=True, slots=True)
class VendorSdkWrite:
    external_identity: str
    revision: int
    trace_id: str


class VendorSdkClient(Protocol):
    sdk_name: str
    sdk_version: str
    api_version: str

    def write_record(
        self,
        *,
        tenant_id: str,
        external_identity: str,
        expected_revision: int,
        payload: Mapping[str, Any],
        request_id: str,
    ) -> VendorSdkWrite: ...

    def read_record(
        self,
        *,
        tenant_id: str,
        external_identity: str,
    ) -> ExternalRecord | None: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class VendorRecordPage:
    records: tuple[ExternalRecord, ...]
    next_cursor: str | None


class PaginatedVendorSdkClient(VendorSdkClient, Protocol):
    def list_records_page(
        self,
        *,
        tenant_id: str,
        cursor: str | None,
        page_size: int,
    ) -> VendorRecordPage: ...


class VersionedVendorGatewayAdapter(VendorGateway):
    """Adapt an injected vendor SDK while keeping lifecycle versions visible."""

    def __init__(
        self,
        *,
        vendor_name: str,
        client_factory: Callable[[], VendorSdkClient],
        sdk_name: str,
        qualified_sdk_band: VersionBand,
        required_api_version: str,
        retry_policy: RetryPolicy | None = None,
        rate_gate: VendorRateGate | None = None,
        sleep: Callable[[float], None] = time.sleep,
        retryable_read_exceptions: tuple[type[Exception], ...] = (
            TimeoutError,
            RetryableVendorRead,
            ResourceReleaseError,
        ),
        ambiguous_write_exceptions: tuple[type[Exception], ...] = (
            TimeoutError,
            ResourceReleaseError,
            AmbiguousVendorWrite,
        ),
    ) -> None:
        if sdk_name != qualified_sdk_band.component:
            raise AdapterVersionError("vendor SDK identity requires the qualified component name")
        if not vendor_name.strip() or not required_api_version.strip():
            raise ValueError("vendor and API versions require non-empty values")
        self.vendor_name = vendor_name
        self.sdk_name = sdk_name
        self.required_api_version = required_api_version
        retry_policy = retry_policy or RetryPolicy()
        self._client_factory = client_factory
        self._qualified_sdk_band = qualified_sdk_band
        self._rate_gate = rate_gate or OpenVendorRateGate()
        self._ambiguous_write_exceptions = ambiguous_write_exceptions
        self._retrying = Retrying(
            stop=stop_after_attempt(retry_policy.max_attempts),
            wait=wait_exponential(
                multiplier=retry_policy.initial_delay_seconds,
                max=retry_policy.maximum_delay_seconds,
            ),
            retry=retry_if_exception_type(retryable_read_exceptions),
            sleep=sleep,
            reraise=True,
        )

    @contextmanager
    def _client(self) -> Iterator[VendorSdkClient]:
        client = self._client_factory()
        primary_error: BaseException | None = None
        try:
            if client.sdk_name != self.sdk_name:
                raise AdapterVersionError("vendor client identity differs from the configured SDK")
            self._qualified_sdk_band.require(client.sdk_version)
            if client.api_version != self.required_api_version:
                raise AdapterVersionError(
                    f"vendor API {client.api_version} differs from required "
                    f"{self.required_api_version}"
                )
            yield client
        except BaseException as error:
            primary_error = error
            raise
        finally:
            try:
                client.close()
            except Exception as error:
                if primary_error is None:
                    raise ResourceReleaseError(
                        "vendor SDK client requires successful release"
                    ) from error

    def write(
        self,
        *,
        tenant_id: str,
        external_identity: str,
        expected_revision: int,
        payload: Mapping[str, Any],
        request_id: str,
    ) -> WriteResult:
        try:
            with self._client() as client:
                self._rate_gate.acquire(operation="write")
                result = client.write_record(
                    tenant_id=tenant_id,
                    external_identity=external_identity,
                    expected_revision=expected_revision,
                    payload=dict(payload),
                    request_id=request_id,
                )
                if (
                    result.external_identity != external_identity
                    or result.revision <= expected_revision
                ):
                    return WriteResult(
                        certainty=WriteCertainty.AMBIGUOUS,
                        external_identity=external_identity,
                        revision=None,
                        trace_id=f"{self.vendor_name}:{request_id}:identity-or-revision",
                    )
        except self._ambiguous_write_exceptions:
            return WriteResult(
                certainty=WriteCertainty.AMBIGUOUS,
                external_identity=external_identity,
                revision=None,
                trace_id=f"{self.vendor_name}:{request_id}:ambiguous",
            )
        return WriteResult(
            certainty=WriteCertainty.CONFIRMED,
            external_identity=result.external_identity,
            revision=result.revision,
            trace_id=result.trace_id,
        )

    def read(self, *, tenant_id: str, external_identity: str) -> ExternalRecord | None:
        def read_once() -> ExternalRecord | None:
            with self._client() as client:
                self._rate_gate.acquire(operation="read")
                return client.read_record(
                    tenant_id=tenant_id,
                    external_identity=external_identity,
                )

        record = self._retrying(read_once)
        if record is not None and (
            record.tenant_id != tenant_id or record.external_identity != external_identity
        ):
            raise RuntimeError(
                "vendor readback requires the requested tenant and external identity"
            )
        return record

    def iter_records(
        self,
        *,
        tenant_id: str,
        page_size: int = 100,
        max_pages: int = 1_000,
    ) -> Iterator[ExternalRecord]:
        """Traverse a bounded cursor sequence with tenant verification."""

        if not 1 <= page_size <= 1_000 or max_pages < 1:
            raise ValueError("pagination requires bounded page and traversal limits")
        cursor: str | None = None
        observed_cursors: set[str] = set()
        for _ in range(max_pages):
            with self._client() as generic_client:
                if not hasattr(generic_client, "list_records_page"):
                    raise TypeError("configured vendor client requires list_records_page support")
                client = generic_client
                self._rate_gate.acquire(operation="list")
                page = client.list_records_page(  # type: ignore[attr-defined]
                    tenant_id=tenant_id,
                    cursor=cursor,
                    page_size=page_size,
                )
            for record in page.records:
                if record.tenant_id != tenant_id:
                    raise RuntimeError("vendor pagination requires the requested tenant identity")
                yield record
            if page.next_cursor is None:
                return
            if page.next_cursor in observed_cursors:
                raise RuntimeError("vendor pagination returned a repeated cursor")
            observed_cursors.add(page.next_cursor)
            cursor = page.next_cursor
        raise RuntimeError("vendor pagination exceeded its configured page bound")
