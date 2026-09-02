"""Production-facing persistence and vendor SDK seams with explicit version bands."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import re
import time
from typing import Any, Callable, Iterator, Mapping, Protocol
from uuid import uuid4

from .bounded_caller import (
    CallDenied,
    CallReceipt,
    InvocationReservation,
    InvocationState,
    StoredCallOutcome,
)
from .model import canonical_json, require_aware_utc
from .ports import ExternalRecord, VendorGateway, WriteCertainty, WriteResult
from .security import PostgresTenantBinding, TenantContextProvider


class AdapterVersionError(RuntimeError):
    """A configured driver or SDK is outside its qualified version band."""


class ResourceReleaseError(RuntimeError):
    """An adapter resource failed its explicit release contract."""


class DurableInvocationError(RuntimeError):
    """A durable invocation transition lost its expected database state."""


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

    def delay(self, completed_attempts: int) -> float:
        return min(
            self.maximum_delay_seconds,
            self.initial_delay_seconds * (2 ** max(completed_attempts - 1, 0)),
        )


class VendorRateGate(Protocol):
    def acquire(self, *, operation: str) -> None: ...


class OpenVendorRateGate:
    """Default gate for callers whose deployment limiter sits outside the adapter."""

    def acquire(self, *, operation: str) -> None:
        if not operation:
            raise ValueError("rate-gate operation requires a name")


_RELEASED_VERSION = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
)


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


class DbApiCursor(Protocol):
    def execute(self, operation: str, parameters: tuple[Any, ...]) -> Any: ...

    def fetchone(self) -> tuple[Any, ...] | None: ...

    def close(self) -> None: ...


class DbApiConnection(Protocol):
    def cursor(self) -> DbApiCursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...


@contextmanager
def _transaction(
    connection_factory: Callable[[], DbApiConnection],
) -> Iterator[DbApiCursor]:
    """Open one explicit DB-API transaction and release each owned resource."""
    connection = connection_factory()
    cursor: DbApiCursor | None = None
    primary_error: BaseException | None = None
    try:
        cursor = connection.cursor()
        yield cursor
        connection.commit()
    except BaseException as error:
        primary_error = error
        try:
            connection.rollback()
        except Exception:
            pass
        raise
    finally:
        release_errors: list[Exception] = []
        if cursor is not None:
            try:
                cursor.close()
            except Exception as error:
                release_errors.append(error)
        try:
            connection.close()
        except Exception as error:
            release_errors.append(error)
        if release_errors and primary_error is None:
            raise ResourceReleaseError(
                "database resources require successful cursor and connection release"
            ) from release_errors[0]


class DbApiInvocationLedger:
    """Persist exact replay ownership with lease-token and fencing-token CAS."""

    INSERT = """
        insert into bounded_call_invocation (
            tenant_id, call_id, invocation_sha256, operation_name,
            operation_version, operation_contract_sha256, state,
            lease_token, fencing_token, lease_expires_at_utc
        ) values (
            %s, %s, %s, %s,
            %s, %s, 'in_progress',
            %s::uuid, 1, %s
        )
        on conflict (tenant_id, call_id) do nothing
        returning lease_token::text, fencing_token
    """
    SELECT_FOR_UPDATE = """
        select
            invocation_sha256, operation_name, operation_version,
            operation_contract_sha256, state, lease_token::text,
            fencing_token, lease_expires_at_utc, output_document,
            result_sha256, recovery_reason
        from bounded_call_invocation
        where tenant_id = %s and call_id = %s
        for update
    """
    EXPIRE_TO_RECOVERY = """
        update bounded_call_invocation
        set state = 'recovery_required',
            recovery_reason = 'lease_expired_before_completion'
        where tenant_id = %s
          and call_id = %s
          and invocation_sha256 = %s
          and state = 'in_progress'
          and lease_expires_at_utc <= %s
          and lease_token = %s::uuid
          and fencing_token = %s
        returning recovery_reason
    """
    COMPLETE = """
        update bounded_call_invocation
        set state = 'completed',
            output_document = %s::jsonb,
            result_sha256 = %s,
            completed_at_utc = %s,
            recovery_reason = null
        where tenant_id = %s
          and call_id = %s
          and invocation_sha256 = %s
          and state = 'in_progress'
          and lease_expires_at_utc > %s
          and lease_token = %s::uuid
          and fencing_token = %s
        returning call_id
    """
    RELEASE = """
        delete from bounded_call_invocation
        where tenant_id = %s
          and call_id = %s
          and invocation_sha256 = %s
          and state = 'in_progress'
          and lease_expires_at_utc > %s
          and lease_token = %s::uuid
          and fencing_token = %s
        returning call_id
    """
    MARK_RECOVERY = """
        update bounded_call_invocation
        set state = 'recovery_required',
            recovery_reason = %s
        where tenant_id = %s
          and call_id = %s
          and invocation_sha256 = %s
          and state = 'in_progress'
          and lease_token = %s::uuid
          and fencing_token = %s
        returning recovery_reason
    """

    def __init__(
        self,
        connection_factory: Callable[[], DbApiConnection],
        *,
        driver_name: str,
        driver_version: str,
        qualified_band: VersionBand,
        tenant_context_provider: TenantContextProvider,
        clock: Callable[[], datetime],
        lease_duration: timedelta = timedelta(seconds=30),
        lease_token_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        if driver_name != qualified_band.component:
            raise AdapterVersionError(
                "database driver identity requires the qualified component name"
            )
        qualified_band.require(driver_version)
        if lease_duration <= timedelta(0):
            raise ValueError("invocation lease duration requires a positive interval")
        self.driver_name = driver_name
        self.driver_version = driver_version
        self._connection_factory = connection_factory
        self._tenant_context_provider = tenant_context_provider
        self._clock = clock
        self._lease_duration = lease_duration
        self._lease_token_factory = lease_token_factory

    def reserve(
        self,
        tenant_id: str,
        call_id: str,
        content_digest: str,
        *,
        operation_name: str,
        operation_version: str,
        operation_contract_digest: str,
        evaluated_at: datetime,
    ) -> InvocationReservation:
        evaluated_at = require_aware_utc(evaluated_at)
        lease_token = self._lease_token_factory()
        lease_expires_at = evaluated_at + self._lease_duration
        with _transaction(self._connection_factory) as cursor:
            PostgresTenantBinding(self._tenant_context_provider(tenant_id)).bind(
                cursor,
                expected_tenant_id=tenant_id,
            )
            cursor.execute(
                self.INSERT,
                (
                    tenant_id,
                    call_id,
                    content_digest,
                    operation_name,
                    operation_version,
                    operation_contract_digest,
                    lease_token,
                    lease_expires_at,
                ),
            )
            inserted = cursor.fetchone()
            if inserted is not None:
                return InvocationReservation(
                    InvocationState.ACQUIRED,
                    lease_token=str(inserted[0]),
                    fencing_token=int(inserted[1]),
                )

            cursor.execute(self.SELECT_FOR_UPDATE, (tenant_id, call_id))
            current = cursor.fetchone()
            if current is None:
                raise DurableInvocationError(
                    "invocation conflict requires a readable durable row"
                )
            (
                observed_digest,
                observed_name,
                observed_version,
                observed_contract,
                state,
                observed_lease,
                observed_fence,
                observed_expiry,
                output_document,
                result_digest,
                recovery_reason,
            ) = current
            if (
                str(observed_digest),
                str(observed_name),
                str(observed_version),
                str(observed_contract),
            ) != (
                content_digest,
                operation_name,
                operation_version,
                operation_contract_digest,
            ):
                raise CallDenied(
                    "idempotency_content_collision",
                    "call identity already binds to different semantic content",
                )
            if state == "completed":
                if not isinstance(output_document, Mapping) or result_digest is None:
                    raise DurableInvocationError(
                        "completed invocation requires output and result digest"
                    )
                output_json = canonical_json(dict(output_document))
                return InvocationReservation(
                    InvocationState.REPLAY,
                    StoredCallOutcome(
                        operation_version=operation_version,
                        operation_contract_digest=operation_contract_digest,
                        output_json=output_json,
                        result_digest=str(result_digest),
                    ),
                )
            if state == "recovery_required":
                return InvocationReservation(
                    InvocationState.RECOVERY_REQUIRED,
                    lease_token=str(observed_lease),
                    fencing_token=int(observed_fence),
                    recovery_reason=str(recovery_reason or "reconciliation_required"),
                )
            if state != "in_progress":
                raise DurableInvocationError(
                    f"invocation state {state!r} requires a released state"
                )
            if not isinstance(observed_expiry, datetime):
                raise DurableInvocationError(
                    "in-progress invocation requires a lease expiry"
                )
            observed_expiry = require_aware_utc(observed_expiry)
            if evaluated_at < observed_expiry:
                return InvocationReservation(InvocationState.IN_PROGRESS)
            cursor.execute(
                self.EXPIRE_TO_RECOVERY,
                (
                    tenant_id,
                    call_id,
                    content_digest,
                    evaluated_at,
                    str(observed_lease),
                    int(observed_fence),
                ),
            )
            transitioned = cursor.fetchone()
            if transitioned is None:
                raise DurableInvocationError(
                    "expired invocation recovery transition lost its fencing token"
                )
            return InvocationReservation(
                InvocationState.RECOVERY_REQUIRED,
                lease_token=str(observed_lease),
                fencing_token=int(observed_fence),
                recovery_reason=str(transitioned[0]),
            )

    def commit(
        self,
        tenant_id: str,
        call_id: str,
        content_digest: str,
        *,
        lease_token: str,
        fencing_token: int,
        outcome: StoredCallOutcome,
    ) -> None:
        completed_at = require_aware_utc(self._clock())
        with _transaction(self._connection_factory) as cursor:
            PostgresTenantBinding(self._tenant_context_provider(tenant_id)).bind(
                cursor,
                expected_tenant_id=tenant_id,
            )
            cursor.execute(
                self.COMPLETE,
                (
                    outcome.output_json,
                    outcome.result_digest,
                    completed_at,
                    tenant_id,
                    call_id,
                    content_digest,
                    completed_at,
                    lease_token,
                    fencing_token,
                ),
            )
            if cursor.fetchone() is None:
                raise DurableInvocationError(
                    "invocation completion lost its lease or fencing token"
                )

    def release(
        self,
        tenant_id: str,
        call_id: str,
        content_digest: str,
        *,
        lease_token: str,
        fencing_token: int,
    ) -> None:
        released_at = require_aware_utc(self._clock())
        with _transaction(self._connection_factory) as cursor:
            PostgresTenantBinding(self._tenant_context_provider(tenant_id)).bind(
                cursor,
                expected_tenant_id=tenant_id,
            )
            cursor.execute(
                self.RELEASE,
                (
                    tenant_id,
                    call_id,
                    content_digest,
                    released_at,
                    lease_token,
                    fencing_token,
                ),
            )
            if cursor.fetchone() is None:
                raise DurableInvocationError(
                    "invocation release lost its lease or fencing token"
                )

    def mark_recovery_required(
        self,
        tenant_id: str,
        call_id: str,
        content_digest: str,
        *,
        lease_token: str,
        fencing_token: int,
        reason_code: str,
    ) -> None:
        if not reason_code.strip():
            raise ValueError("recovery reason requires a stable code")
        with _transaction(self._connection_factory) as cursor:
            PostgresTenantBinding(self._tenant_context_provider(tenant_id)).bind(
                cursor,
                expected_tenant_id=tenant_id,
            )
            cursor.execute(
                self.MARK_RECOVERY,
                (
                    reason_code,
                    tenant_id,
                    call_id,
                    content_digest,
                    lease_token,
                    fencing_token,
                ),
            )
            if cursor.fetchone() is None:
                raise DurableInvocationError(
                    "invocation recovery transition lost its lease or fencing token"
                )


class DbApiCallReceiptStore:
    """Append call receipts through a fixed DB-API statement and tenant binding."""

    INSERT = """
        insert into bounded_call_receipt (
            receipt_id, call_id, caller_id, actor_id, tenant_id,
            operation_name, operation_version, operation_contract_sha256,
            effect_class, resource_ids, payload_sha256, invocation_sha256,
            decision, reason_code, grant_id, budget_window_id, approval_id,
            result_sha256, requested_at_utc, recorded_at_utc
        ) values (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s::jsonb,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s
        )
    """

    def __init__(
        self,
        connection_factory: Callable[[], DbApiConnection],
        *,
        driver_name: str,
        driver_version: str,
        qualified_band: VersionBand,
        tenant_context_provider: TenantContextProvider,
    ) -> None:
        if driver_name != qualified_band.component:
            raise AdapterVersionError(
                "database driver identity requires the qualified component name"
            )
        qualified_band.require(driver_version)
        self.driver_name = driver_name
        self.driver_version = driver_version
        self._connection_factory = connection_factory
        self._tenant_context_provider = tenant_context_provider

    def append(self, receipt: CallReceipt) -> None:
        connection = self._connection_factory()
        cursor: DbApiCursor | None = None
        primary_error: BaseException | None = None
        try:
            cursor = connection.cursor()
            PostgresTenantBinding(
                self._tenant_context_provider(receipt.tenant_id)
            ).bind(cursor, expected_tenant_id=receipt.tenant_id)
            cursor.execute(
                self.INSERT,
                (
                    receipt.receipt_id,
                    receipt.call_id,
                    receipt.caller_id,
                    receipt.actor_id,
                    receipt.tenant_id,
                    receipt.operation_name,
                    receipt.operation_version,
                    receipt.operation_contract_digest,
                    receipt.effect_class.value,
                    json.dumps(list(receipt.resource_ids), separators=(",", ":")),
                    receipt.payload_digest,
                    receipt.invocation_digest,
                    receipt.decision.value,
                    receipt.reason_code,
                    receipt.grant_id,
                    receipt.budget_window_id,
                    receipt.approval_id,
                    receipt.result_digest,
                    receipt.requested_at,
                    receipt.recorded_at,
                ),
            )
            connection.commit()
        except BaseException as error:
            primary_error = error
            try:
                connection.rollback()
            except Exception:
                pass
            raise
        finally:
            release_errors: list[Exception] = []
            if cursor is not None:
                try:
                    cursor.close()
                except Exception as error:
                    release_errors.append(error)
            try:
                connection.close()
            except Exception as error:
                release_errors.append(error)
            if release_errors and primary_error is None:
                raise ResourceReleaseError(
                    "database receipt resources require successful cursor and "
                    "connection release"
                ) from release_errors[0]


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
    """Adapt an injected vendor SDK while keeping lifecycle and versions visible."""

    def __init__(
        self,
        *,
        vendor_name: str,
        client_factory: Callable[[], VendorSdkClient],
        sdk_name: str,
        qualified_sdk_band: VersionBand,
        required_api_version: str,
        retry_policy: RetryPolicy = RetryPolicy(),
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
            raise AdapterVersionError(
                "vendor SDK identity requires the qualified component name"
            )
        if not vendor_name.strip() or not required_api_version.strip():
            raise ValueError("vendor and API versions require non-empty values")
        self.vendor_name = vendor_name
        self.sdk_name = sdk_name
        self.required_api_version = required_api_version
        self._client_factory = client_factory
        self._qualified_sdk_band = qualified_sdk_band
        self._retry_policy = retry_policy
        self._rate_gate = rate_gate or OpenVendorRateGate()
        self._sleep = sleep
        self._retryable_read_exceptions = retryable_read_exceptions
        self._ambiguous_write_exceptions = ambiguous_write_exceptions

    @contextmanager
    def _client(self) -> Iterator[VendorSdkClient]:
        client = self._client_factory()
        primary_error: BaseException | None = None
        try:
            if client.sdk_name != self.sdk_name:
                raise AdapterVersionError(
                    "vendor client identity differs from the configured SDK"
                )
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
        payload: Any,
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
        record: ExternalRecord | None = None
        for attempt in range(1, self._retry_policy.max_attempts + 1):
            try:
                with self._client() as client:
                    self._rate_gate.acquire(operation="read")
                    record = client.read_record(
                        tenant_id=tenant_id,
                        external_identity=external_identity,
                    )
                break
            except self._retryable_read_exceptions:
                if attempt >= self._retry_policy.max_attempts:
                    raise
                self._sleep(self._retry_policy.delay(attempt))
        if record is not None and (
            record.tenant_id != tenant_id
            or record.external_identity != external_identity
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
                    raise TypeError(
                        "configured vendor client requires list_records_page support"
                    )
                client = generic_client
                self._rate_gate.acquire(operation="list")
                page = client.list_records_page(  # type: ignore[attr-defined]
                    tenant_id=tenant_id,
                    cursor=cursor,
                    page_size=page_size,
                )
            for record in page.records:
                if record.tenant_id != tenant_id:
                    raise RuntimeError(
                        "vendor pagination requires the requested tenant identity"
                    )
                yield record
            if page.next_cursor is None:
                return
            if page.next_cursor in observed_cursors:
                raise RuntimeError("vendor pagination returned a repeated cursor")
            observed_cursors.add(page.next_cursor)
            cursor = page.next_cursor
        raise RuntimeError("vendor pagination exceeded its configured page bound")
