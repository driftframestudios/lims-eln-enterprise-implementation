"""Tool-neutral operation authority with exact approvals and attributable receipts."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
import json
import re
from threading import Lock
from types import MappingProxyType
from typing import Any, Callable, Generic, Mapping, Protocol, TypeVar
from uuid import uuid4

from .model import DomainError, canonical_digest, canonical_json, require_aware_utc


InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


def _immutable_json(value: Any) -> Any:
    """Return a recursively immutable view of canonical JSON content."""
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _immutable_json(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_immutable_json(item) for item in value)
    return value


class EffectClass(StrEnum):
    """Effect classes that select replay and approval policy."""

    UNCLASSIFIED = "unclassified"
    READ = "read"
    IDEMPOTENT_NARROW_WRITE = "idempotent_narrow_write"
    APPROVAL_GATED_BROAD_WRITE = "approval_gated_broad_write"

    @property
    def requires_approval(self) -> bool:
        return self is EffectClass.APPROVAL_GATED_BROAD_WRITE


class CallDecision(StrEnum):
    AUTHORIZED = "authorized"
    SUCCEEDED = "succeeded"
    REPLAYED = "replayed"
    DENIED = "denied"
    FAILED = "failed"


class CallDenied(PermissionError):
    """A call remains outside its declared authority or budget."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class CallInProgress(CallDenied):
    """A matching call already owns the invocation reservation."""


class CallRecoveryRequired(CallDenied):
    """A prior write attempt requires authoritative reconciliation."""


class OperationInputError(DomainError):
    """An operation payload failed its typed boundary contract."""


class OperationRegistrationError(ValueError):
    """An operation registry entry conflicts with the existing contract."""


@dataclass(frozen=True, slots=True)
class CallRequest:
    call_id: str
    caller_id: str
    actor_id: str
    tenant_id: str
    operation_name: str
    resource_ids: tuple[str, ...]
    payload: Mapping[str, Any]
    requested_at: datetime
    approval_id: str | None = None
    _payload_json: str = field(init=False, repr=False)
    _payload_digest: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("call_id", self.call_id),
            ("caller_id", self.caller_id),
            ("actor_id", self.actor_id),
            ("tenant_id", self.tenant_id),
            ("operation_name", self.operation_name),
        ):
            if not value.strip():
                raise OperationInputError(f"{name} requires a non-empty value")
        require_aware_utc(self.requested_at)
        resource_ids = tuple(self.resource_ids)
        object.__setattr__(self, "resource_ids", resource_ids)
        if not resource_ids:
            raise OperationInputError("resource_ids requires at least one bounded resource")
        if not all(isinstance(value, str) for value in resource_ids):
            raise OperationInputError("resource_ids requires text identities")
        if len(set(resource_ids)) != len(resource_ids):
            raise OperationInputError("resource_ids requires unique bounded resources")
        if any(not value.strip() for value in resource_ids):
            raise OperationInputError("resource_ids requires non-empty values")
        if any(
            len(value) > 256
            or ":" not in value
            or any(ord(character) < 33 for character in value)
            for value in resource_ids
        ):
            raise OperationInputError(
                "resource_ids require printable namespace-qualified values"
            )
        payload_json = canonical_json(dict(self.payload))
        payload_snapshot = json.loads(payload_json)
        assert isinstance(payload_snapshot, dict)
        object.__setattr__(self, "payload", _immutable_json(payload_snapshot))
        object.__setattr__(self, "_payload_json", payload_json)
        object.__setattr__(
            self,
            "_payload_digest",
            canonical_digest(payload_snapshot),
        )

    @property
    def payload_digest(self) -> str:
        return self._payload_digest

    def invocation_digest(
        self,
        *,
        operation_version: str,
        operation_contract_digest: str,
    ) -> str:
        return canonical_digest(
            {
                "caller_id": self.caller_id,
                "actor_id": self.actor_id,
                "tenant_id": self.tenant_id,
                "operation_name": self.operation_name,
                "operation_version": operation_version,
                "operation_contract_digest": operation_contract_digest,
                "resource_ids": list(self.resource_ids),
                "payload_digest": self.payload_digest,
            }
        )

    @property
    def payload_size_bytes(self) -> int:
        return len(self._payload_json.encode("utf-8"))

    def decoded_payload(self) -> dict[str, Any]:
        """Return a fresh value from the canonical ingress snapshot."""
        value = json.loads(self._payload_json)
        assert isinstance(value, dict)
        return value


@dataclass(frozen=True, slots=True)
class CallerGrant:
    grant_id: str
    caller_id: str
    actor_ids: frozenset[str]
    tenant_id: str
    capabilities: frozenset[str]
    resource_prefixes: tuple[str, ...]
    expires_at: datetime
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        actor_ids = frozenset(self.actor_ids)
        capabilities = frozenset(self.capabilities)
        resource_prefixes = tuple(self.resource_prefixes)
        object.__setattr__(self, "actor_ids", actor_ids)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "resource_prefixes", resource_prefixes)
        for name, value in (
            ("grant_id", self.grant_id),
            ("caller_id", self.caller_id),
            ("tenant_id", self.tenant_id),
        ):
            if not value.strip():
                raise OperationInputError(f"{name} requires a non-empty value")
        require_aware_utc(self.expires_at)
        if self.revoked_at is not None:
            require_aware_utc(self.revoked_at)
        if not actor_ids or not capabilities or not resource_prefixes:
            raise OperationInputError(
                "caller grant requires actors, capabilities, and resource prefixes"
            )
        if not all(isinstance(value, str) for value in actor_ids | capabilities):
            raise OperationInputError(
                "caller grant actors and capabilities require text identities"
            )
        if not all(isinstance(prefix, str) for prefix in resource_prefixes):
            raise OperationInputError("caller grant resource prefixes require text")
        if len(set(resource_prefixes)) != len(resource_prefixes):
            raise OperationInputError("caller grant resource prefixes require uniqueness")
        if any(
            len(prefix) > 256
            or ":" not in prefix
            or prefix[-1] not in {":", "-", "/"}
            or any(ord(character) < 33 for character in prefix)
            for prefix in resource_prefixes
        ):
            raise OperationInputError(
                "caller grant prefixes require printable namespace boundaries "
                "ending in ':', '-', or '/'"
            )

    def authorize(
        self,
        request: CallRequest,
        *,
        capability: str,
        evaluated_at: datetime,
    ) -> None:
        if evaluated_at > self.expires_at:
            raise CallDenied(
                "caller_grant_expired",
                "caller authority has expired; renew the task-scoped grant",
            )
        if self.revoked_at is not None and evaluated_at >= self.revoked_at:
            raise CallDenied(
                "caller_grant_revoked",
                "caller authority was revoked; obtain a newly issued task-scoped grant",
            )
        if request.caller_id != self.caller_id:
            raise CallDenied(
                "caller_identity_mismatch",
                "caller authority belongs to a different workload identity",
            )
        if request.actor_id not in self.actor_ids:
            raise CallDenied(
                "actor_outside_grant",
                "the accountable actor remains outside this caller grant",
            )
        if request.tenant_id != self.tenant_id:
            raise CallDenied(
                "tenant_outside_grant",
                "the call remains outside the grant's tenant boundary",
            )
        if capability not in self.capabilities:
            raise CallDenied(
                "capability_outside_grant",
                "the operation requires a capability assigned by the accountable owner",
            )
        outside = [
            resource
            for resource in request.resource_ids
            if not any(resource.startswith(prefix) for prefix in self.resource_prefixes)
        ]
        if outside:
            raise CallDenied(
                "resource_outside_grant",
                "every resource requires an allowed task-scoped prefix",
            )


class CallerGrantStore(Protocol):
    def get(self, caller_id: str) -> CallerGrant | None: ...


class InMemoryCallerGrantStore:
    def __init__(self, grants: tuple[CallerGrant, ...] = ()) -> None:
        self._grants = {grant.caller_id: grant for grant in grants}

    def put(self, grant: CallerGrant) -> None:
        self._grants[grant.caller_id] = grant

    def revoke(self, caller_id: str, *, revoked_at: datetime) -> None:
        grant = self._grants.get(caller_id)
        if grant is None:
            raise OperationRegistrationError(
                f"caller grant {caller_id} requires an existing identity"
            )
        if grant.revoked_at is not None:
            raise OperationRegistrationError(
                f"caller grant {caller_id} already has a revocation decision"
            )
        self._grants[caller_id] = replace(
            grant,
            revoked_at=require_aware_utc(revoked_at),
        )

    def get(self, caller_id: str) -> CallerGrant | None:
        return self._grants.get(caller_id)


@dataclass(frozen=True, slots=True)
class OperationApproval:
    approval_id: str
    call_id: str
    caller_id: str
    actor_id: str
    tenant_id: str
    operation_name: str
    operation_version: str
    operation_contract_digest: str
    effect_class: EffectClass
    resource_ids: tuple[str, ...]
    payload_digest: str
    approved_by: str
    approved_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        resource_ids = tuple(self.resource_ids)
        object.__setattr__(self, "resource_ids", resource_ids)
        for name, value in (
            ("approval_id", self.approval_id),
            ("call_id", self.call_id),
            ("caller_id", self.caller_id),
            ("actor_id", self.actor_id),
            ("tenant_id", self.tenant_id),
            ("operation_name", self.operation_name),
            ("operation_version", self.operation_version),
            ("operation_contract_digest", self.operation_contract_digest),
            ("payload_digest", self.payload_digest),
            ("approved_by", self.approved_by),
        ):
            if not value.strip():
                raise OperationInputError(f"{name} requires a non-empty value")
        require_aware_utc(self.approved_at)
        require_aware_utc(self.expires_at)
        if self.revoked_at is not None:
            require_aware_utc(self.revoked_at)
            if self.revoked_at < self.approved_at:
                raise OperationInputError(
                    "approval revocation requires time at or after approval"
                )
        if self.approved_at >= self.expires_at:
            raise OperationInputError("approval expiry requires time after approval")
        if self.approved_by == self.actor_id:
            raise OperationInputError(
                "broad-write approval requires an independent accountable identity"
            )
        if not resource_ids:
            raise OperationInputError("approval requires an explicit resource scope")
        if not all(isinstance(value, str) for value in resource_ids):
            raise OperationInputError("approval resources require text identities")
        if re.fullmatch(r"[a-f0-9]{64}", self.operation_contract_digest) is None:
            raise OperationInputError(
                "approval operation contract requires a lowercase SHA-256 digest"
            )

    @classmethod
    def for_request(
        cls,
        *,
        approval_id: str,
        request: CallRequest,
        operation_version: str,
        operation_contract_digest: str,
        effect_class: EffectClass,
        approved_by: str,
        approved_at: datetime,
        expires_at: datetime,
        revoked_at: datetime | None = None,
    ) -> OperationApproval:
        return cls(
            approval_id=approval_id,
            call_id=request.call_id,
            caller_id=request.caller_id,
            actor_id=request.actor_id,
            tenant_id=request.tenant_id,
            operation_name=request.operation_name,
            operation_version=operation_version,
            operation_contract_digest=operation_contract_digest,
            effect_class=effect_class,
            resource_ids=request.resource_ids,
            payload_digest=request.payload_digest,
            approved_by=approved_by,
            approved_at=approved_at,
            expires_at=expires_at,
            revoked_at=revoked_at,
        )

    def authorize(
        self,
        request: CallRequest,
        *,
        operation_version: str,
        operation_contract_digest: str,
        effect_class: EffectClass,
        evaluated_at: datetime,
    ) -> None:
        if request.approval_id != self.approval_id:
            raise CallDenied(
                "approval_identity_mismatch",
                "the call requires its exact approval identity",
            )
        if evaluated_at < self.approved_at or evaluated_at > self.expires_at:
            raise CallDenied(
                "approval_outside_time_window",
                "the call requires an active approval window",
            )
        if self.revoked_at is not None and evaluated_at >= self.revoked_at:
            raise CallDenied(
                "approval_revoked",
                "the approval was revoked; obtain a new scoped decision",
            )
        expected = (
            self.call_id,
            self.caller_id,
            self.actor_id,
            self.tenant_id,
            self.operation_name,
            self.operation_version,
            self.operation_contract_digest,
            self.effect_class,
            self.resource_ids,
            self.payload_digest,
        )
        observed = (
            request.call_id,
            request.caller_id,
            request.actor_id,
            request.tenant_id,
            request.operation_name,
            operation_version,
            operation_contract_digest,
            effect_class,
            request.resource_ids,
            request.payload_digest,
        )
        if observed != expected:
            raise CallDenied(
                "approval_scope_mismatch",
                "approval binds the exact caller, actor, tenant, operation, resources, "
                "effect class, and payload digest",
            )


class ApprovalStore(Protocol):
    def get(self, approval_id: str) -> OperationApproval | None: ...


class InMemoryApprovalStore:
    def __init__(self, approvals: tuple[OperationApproval, ...] = ()) -> None:
        self._approvals = {approval.approval_id: approval for approval in approvals}

    def put(self, approval: OperationApproval) -> None:
        if approval.approval_id in self._approvals:
            raise OperationRegistrationError(
                f"approval {approval.approval_id} already exists; preserve its original scope"
            )
        self._approvals[approval.approval_id] = approval

    def revoke(self, approval_id: str, *, revoked_at: datetime) -> None:
        approval = self._approvals.get(approval_id)
        if approval is None:
            raise OperationRegistrationError(
                f"approval {approval_id} requires an existing decision"
            )
        if approval.revoked_at is not None:
            raise OperationRegistrationError(
                f"approval {approval_id} already has a revocation decision"
            )
        self._approvals[approval_id] = replace(
            approval,
            revoked_at=require_aware_utc(revoked_at),
        )

    def get(self, approval_id: str) -> OperationApproval | None:
        return self._approvals.get(approval_id)


@dataclass(frozen=True, slots=True)
class BudgetPolicy:
    window_id: str
    caller_call_limits: Mapping[str, int]
    tenant_call_limits: Mapping[str, int]
    max_resources_per_call: int
    max_payload_bytes: int

    def __post_init__(self) -> None:
        caller_call_limits = MappingProxyType(dict(self.caller_call_limits))
        tenant_call_limits = MappingProxyType(dict(self.tenant_call_limits))
        object.__setattr__(self, "caller_call_limits", caller_call_limits)
        object.__setattr__(self, "tenant_call_limits", tenant_call_limits)
        if not self.window_id.strip():
            raise OperationInputError("budget window requires a stable identity")
        if self.max_resources_per_call < 1 or self.max_payload_bytes < 2:
            raise OperationInputError("budget bounds require positive usable limits")
        if any(
            not isinstance(key, str)
            or not key.strip()
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value < 1
            for key, value in caller_call_limits.items()
        ):
            raise OperationInputError("caller call limits require positive integers")
        if any(
            not isinstance(key, str)
            or not key.strip()
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value < 1
            for key, value in tenant_call_limits.items()
        ):
            raise OperationInputError("tenant call limits require positive integers")


class BudgetLedger(Protocol):
    @property
    def window_id(self) -> str: ...

    def reserve(self, request: CallRequest) -> None: ...


class InMemoryBudgetLedger:
    """Atomically reserve caller and tenant call budgets for one declared window."""

    def __init__(self, policy: BudgetPolicy) -> None:
        self.policy = policy
        self._caller_counts: dict[str, int] = {}
        self._tenant_counts: dict[str, int] = {}
        self._lock = Lock()

    @property
    def window_id(self) -> str:
        return self.policy.window_id

    def reserve(self, request: CallRequest) -> None:
        if len(request.resource_ids) > self.policy.max_resources_per_call:
            raise CallDenied(
                "resource_budget_exceeded",
                "the operation exceeds its bounded resource count",
            )
        if request.payload_size_bytes > self.policy.max_payload_bytes:
            raise CallDenied(
                "payload_budget_exceeded",
                "the operation exceeds its bounded payload size",
            )
        caller_limit = self.policy.caller_call_limits.get(request.caller_id)
        tenant_limit = self.policy.tenant_call_limits.get(request.tenant_id)
        if caller_limit is None:
            raise CallDenied(
                "caller_budget_missing",
                "the caller requires an assigned call budget",
            )
        if tenant_limit is None:
            raise CallDenied(
                "tenant_budget_missing",
                "the tenant requires an assigned call budget",
            )
        with self._lock:
            caller_count = self._caller_counts.get(request.caller_id, 0)
            tenant_count = self._tenant_counts.get(request.tenant_id, 0)
            if caller_count >= caller_limit:
                raise CallDenied(
                    "caller_budget_exhausted",
                    "the caller has reached its call budget for this window",
                )
            if tenant_count >= tenant_limit:
                raise CallDenied(
                    "tenant_budget_exhausted",
                    "the tenant has reached its call budget for this window",
                )
            self._caller_counts[request.caller_id] = caller_count + 1
            self._tenant_counts[request.tenant_id] = tenant_count + 1

    def snapshot(self) -> Mapping[str, Mapping[str, int]]:
        with self._lock:
            return {
                "caller": dict(self._caller_counts),
                "tenant": dict(self._tenant_counts),
            }


@dataclass(frozen=True, slots=True)
class OperationContext:
    call_id: str
    caller_id: str
    actor_id: str
    tenant_id: str
    resource_ids: tuple[str, ...]
    requested_at: datetime
    approval_id: str | None


@dataclass(frozen=True, slots=True)
class OperationDefinition(Generic[InputT, OutputT]):
    name: str
    version: str
    contract_digest: str
    effect_class: EffectClass
    capability: str
    decode: Callable[[Mapping[str, Any]], InputT]
    resources: Callable[[InputT], tuple[str, ...]]
    execute: Callable[[OperationContext, InputT], OutputT]
    encode: Callable[[OutputT], Mapping[str, Any]]

    def __post_init__(self) -> None:
        for name, value in (
            ("name", self.name),
            ("version", self.version),
            ("contract_digest", self.contract_digest),
            ("capability", self.capability),
        ):
            if not value.strip():
                raise OperationRegistrationError(f"operation {name} requires a value")
        if re.fullmatch(r"[a-f0-9]{64}", self.contract_digest) is None:
            raise OperationRegistrationError(
                "operation contract_digest requires a lowercase SHA-256 digest"
            )
        if self.effect_class is EffectClass.UNCLASSIFIED:
            raise OperationRegistrationError(
                "registered operations require a classified effect"
            )


class OperationRegistry:
    def __init__(self) -> None:
        self._operations: dict[str, OperationDefinition[Any, Any]] = {}

    def register(self, operation: OperationDefinition[Any, Any]) -> None:
        if operation.name in self._operations:
            raise OperationRegistrationError(
                f"operation {operation.name} already has a registered contract"
            )
        self._operations[operation.name] = operation

    def get(self, name: str) -> OperationDefinition[Any, Any] | None:
        return self._operations.get(name)

    def inventory(self) -> tuple[OperationDefinition[Any, Any], ...]:
        return tuple(self._operations[name] for name in sorted(self._operations))


@dataclass(frozen=True, slots=True)
class CallReceipt:
    receipt_id: str
    call_id: str
    caller_id: str
    actor_id: str
    tenant_id: str
    operation_name: str
    operation_version: str
    operation_contract_digest: str | None
    effect_class: EffectClass
    resource_ids: tuple[str, ...]
    payload_digest: str
    invocation_digest: str | None
    decision: CallDecision
    reason_code: str
    grant_id: str | None
    budget_window_id: str | None
    approval_id: str | None
    result_digest: str | None
    requested_at: datetime
    recorded_at: datetime

    def __post_init__(self) -> None:
        resource_ids = tuple(self.resource_ids)
        object.__setattr__(self, "resource_ids", resource_ids)
        require_aware_utc(self.requested_at)
        require_aware_utc(self.recorded_at)
        for name, value in (
            ("receipt_id", self.receipt_id),
            ("call_id", self.call_id),
            ("caller_id", self.caller_id),
            ("actor_id", self.actor_id),
            ("tenant_id", self.tenant_id),
            ("operation_name", self.operation_name),
            ("operation_version", self.operation_version),
            ("reason_code", self.reason_code),
        ):
            if not value.strip():
                raise OperationInputError(f"receipt {name} requires a non-empty value")
        for name, value in (
            ("operation_contract_digest", self.operation_contract_digest),
            ("payload_digest", self.payload_digest),
            ("invocation_digest", self.invocation_digest),
            ("result_digest", self.result_digest),
        ):
            if value is not None and re.fullmatch(r"[a-f0-9]{64}", value) is None:
                raise OperationInputError(
                    f"receipt {name} requires a lowercase SHA-256 digest"
                )
        for name, value in (
            ("grant_id", self.grant_id),
            ("budget_window_id", self.budget_window_id),
            ("approval_id", self.approval_id),
        ):
            if value is not None and not value.strip():
                raise OperationInputError(
                    f"receipt {name} requires a non-empty value when present"
                )
        if (
            self.decision in {CallDecision.SUCCEEDED, CallDecision.REPLAYED}
            and self.result_digest is None
        ):
            raise OperationInputError(
                "successful and replayed receipts require a result digest"
            )
        if self.decision in {
            CallDecision.AUTHORIZED,
            CallDecision.SUCCEEDED,
            CallDecision.REPLAYED,
            CallDecision.FAILED,
        } and any(
            value is None
            for value in (
                self.operation_contract_digest,
                self.invocation_digest,
                self.grant_id,
                self.budget_window_id,
            )
        ):
            raise OperationInputError(
                "executed call receipts require operation, invocation, grant, "
                "and budget provenance"
            )
        if (
            self.effect_class is EffectClass.APPROVAL_GATED_BROAD_WRITE
            and self.decision
            in {
                CallDecision.AUTHORIZED,
                CallDecision.SUCCEEDED,
                CallDecision.REPLAYED,
            }
            and self.approval_id is None
        ):
            raise OperationInputError(
                "authorized broad-write receipts require an approval identity"
            )


class CallReceiptStore(Protocol):
    def append(self, receipt: CallReceipt) -> None: ...


class InMemoryCallReceiptStore:
    def __init__(self) -> None:
        self._receipts: list[CallReceipt] = []
        self._ids: set[str] = set()
        self._lock = Lock()

    def append(self, receipt: CallReceipt) -> None:
        with self._lock:
            if receipt.receipt_id in self._ids:
                raise OperationRegistrationError(
                    f"receipt {receipt.receipt_id} already exists; append a new event"
                )
            self._ids.add(receipt.receipt_id)
            self._receipts.append(receipt)

    def for_call(self, call_id: str) -> tuple[CallReceipt, ...]:
        with self._lock:
            return tuple(item for item in self._receipts if item.call_id == call_id)

    def all(self) -> tuple[CallReceipt, ...]:
        with self._lock:
            return tuple(self._receipts)


class InvocationState(StrEnum):
    ACQUIRED = "acquired"
    REPLAY = "replay"
    IN_PROGRESS = "in_progress"
    RECOVERY_REQUIRED = "recovery_required"


@dataclass(frozen=True, slots=True)
class StoredCallOutcome:
    operation_version: str
    operation_contract_digest: str
    output_json: str
    result_digest: str

    def decoded_output(self) -> dict[str, Any]:
        value = json.loads(self.output_json)
        assert isinstance(value, dict)
        return value


@dataclass(frozen=True, slots=True)
class InvocationReservation:
    state: InvocationState
    outcome: StoredCallOutcome | None = None
    lease_token: str | None = None
    fencing_token: int | None = None
    recovery_reason: str | None = None


@dataclass(slots=True)
class _InvocationEntry:
    content_digest: str
    operation_name: str
    operation_version: str
    operation_contract_digest: str
    lease_token: str
    fencing_token: int
    outcome: StoredCallOutcome | None = None
    recovery_reason: str | None = None


class InvocationLedger(Protocol):
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
    ) -> InvocationReservation: ...

    def commit(
        self,
        tenant_id: str,
        call_id: str,
        content_digest: str,
        *,
        lease_token: str,
        fencing_token: int,
        outcome: StoredCallOutcome,
    ) -> None: ...

    def release(
        self,
        tenant_id: str,
        call_id: str,
        content_digest: str,
        *,
        lease_token: str,
        fencing_token: int,
    ) -> None: ...

    def mark_recovery_required(
        self,
        tenant_id: str,
        call_id: str,
        content_digest: str,
        *,
        lease_token: str,
        fencing_token: int,
        reason_code: str,
    ) -> None: ...


class InMemoryInvocationLedger:
    """A deterministic conformance ledger for exact replay and recovery."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], _InvocationEntry] = {}
        self._lock = Lock()

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
        require_aware_utc(evaluated_at)
        identity = (tenant_id, call_id)
        with self._lock:
            current = self._entries.get(identity)
            if current is None:
                lease_token = str(uuid4())
                current = _InvocationEntry(
                    content_digest=content_digest,
                    operation_name=operation_name,
                    operation_version=operation_version,
                    operation_contract_digest=operation_contract_digest,
                    lease_token=lease_token,
                    fencing_token=1,
                )
                self._entries[identity] = current
                return InvocationReservation(
                    InvocationState.ACQUIRED,
                    lease_token=lease_token,
                    fencing_token=1,
                )
            if current.content_digest != content_digest:
                raise CallDenied(
                    "idempotency_content_collision",
                    "call identity already binds to different semantic content",
                )
            if current.outcome is not None:
                return InvocationReservation(InvocationState.REPLAY, current.outcome)
            if current.recovery_reason is not None:
                return InvocationReservation(
                    InvocationState.RECOVERY_REQUIRED,
                    lease_token=current.lease_token,
                    fencing_token=current.fencing_token,
                    recovery_reason=current.recovery_reason,
                )
            return InvocationReservation(InvocationState.IN_PROGRESS)

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
        with self._lock:
            current = self._owned_entry(
                tenant_id,
                call_id,
                content_digest,
                lease_token=lease_token,
                fencing_token=fencing_token,
            )
            if current.recovery_reason is not None:
                raise CallRecoveryRequired(
                    "invocation_recovery_required",
                    "the invocation requires authoritative reconciliation",
                )
            current.outcome = outcome

    def release(
        self,
        tenant_id: str,
        call_id: str,
        content_digest: str,
        *,
        lease_token: str,
        fencing_token: int,
    ) -> None:
        identity = (tenant_id, call_id)
        with self._lock:
            current = self._owned_entry(
                tenant_id,
                call_id,
                content_digest,
                lease_token=lease_token,
                fencing_token=fencing_token,
            )
            if current.outcome is not None or current.recovery_reason is not None:
                raise CallDenied(
                    "invocation_state_conflict",
                    "the invocation state requires replay or recovery",
                )
            del self._entries[identity]

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
            raise OperationInputError("recovery reason requires a stable code")
        with self._lock:
            current = self._owned_entry(
                tenant_id,
                call_id,
                content_digest,
                lease_token=lease_token,
                fencing_token=fencing_token,
            )
            if current.outcome is not None:
                raise CallDenied(
                    "invocation_state_conflict",
                    "a completed invocation remains available for exact replay",
                )
            current.recovery_reason = reason_code

    def _owned_entry(
        self,
        tenant_id: str,
        call_id: str,
        content_digest: str,
        *,
        lease_token: str,
        fencing_token: int,
    ) -> _InvocationEntry:
        current = self._entries.get((tenant_id, call_id))
        if (
            current is None
            or current.content_digest != content_digest
            or current.lease_token != lease_token
            or current.fencing_token != fencing_token
        ):
            raise CallDenied(
                "invocation_lease_lost",
                "the invocation requires its current lease and fencing token",
            )
        return current


@dataclass(frozen=True, slots=True)
class CallResult:
    output: Mapping[str, Any]
    receipt: CallReceipt


class BoundedCaller:
    """Invoke registered operations through one auditable authority boundary."""

    def __init__(
        self,
        *,
        registry: OperationRegistry,
        grants: CallerGrantStore,
        approvals: ApprovalStore,
        budgets: BudgetLedger,
        receipts: CallReceiptStore,
        invocations: InvocationLedger,
        clock: Callable[[], datetime],
        receipt_id_factory: Callable[[], str] = lambda: str(uuid4()),
        max_request_age: timedelta = timedelta(minutes=5),
        max_future_clock_skew: timedelta = timedelta(minutes=1),
    ) -> None:
        if max_request_age <= timedelta(0) or max_future_clock_skew < timedelta(0):
            raise OperationInputError(
                "request-time bounds require a positive age and nonnegative future skew"
            )
        self._registry = registry
        self._grants = grants
        self._approvals = approvals
        self._budgets = budgets
        self._receipts = receipts
        self._invocations = invocations
        self._clock = clock
        self._receipt_id_factory = receipt_id_factory
        self._max_request_age = max_request_age
        self._max_future_clock_skew = max_future_clock_skew

    def invoke(self, request: CallRequest) -> CallResult:
        evaluated_at = require_aware_utc(self._clock())
        operation = self._registry.get(request.operation_name)
        if operation is None:
            self._deny(
                request,
                operation_version="unregistered",
                effect_class=EffectClass.UNCLASSIFIED,
                reason_code="operation_unregistered",
                message="the caller may invoke only named registered operations",
            )
        assert operation is not None
        invocation_digest = request.invocation_digest(
            operation_version=operation.version,
            operation_contract_digest=operation.contract_digest,
        )
        grant = self._grants.get(request.caller_id)
        if grant is None:
            self._deny(
                request,
                operation_version=operation.version,
                operation_contract_digest=operation.contract_digest,
                invocation_digest=invocation_digest,
                budget_window_id=self._budgets.window_id,
                effect_class=operation.effect_class,
                reason_code="caller_grant_missing",
                message="the caller requires a task-scoped grant",
            )
        assert grant is not None
        try:
            self._authorize_request_time(request, evaluated_at=evaluated_at)
            grant.authorize(
                request,
                capability=operation.capability,
                evaluated_at=evaluated_at,
            )
            typed_input = operation.decode(request.decoded_payload())
            declared_resources = operation.resources(typed_input)
            if declared_resources != request.resource_ids:
                raise CallDenied(
                    "resource_scope_mismatch",
                    "typed operation resources must equal the declared call scope",
                )
            self._authorize_approval(
                request,
                operation,
                evaluated_at=evaluated_at,
            )
            reservation = self._invocations.reserve(
                request.tenant_id,
                request.call_id,
                invocation_digest,
                operation_name=operation.name,
                operation_version=operation.version,
                operation_contract_digest=operation.contract_digest,
                evaluated_at=evaluated_at,
            )
            if reservation.state is InvocationState.REPLAY:
                assert reservation.outcome is not None
                receipt = self._record(
                    request,
                    operation=operation,
                    grant=grant,
                    invocation_digest=invocation_digest,
                    decision=CallDecision.REPLAYED,
                    reason_code="exact_replay",
                    result_digest=reservation.outcome.result_digest,
                )
                return CallResult(reservation.outcome.decoded_output(), receipt)
            if reservation.state is InvocationState.IN_PROGRESS:
                raise CallInProgress(
                    "call_in_progress",
                    "a matching call already owns the execution reservation",
                )
            if reservation.state is InvocationState.RECOVERY_REQUIRED:
                raise CallRecoveryRequired(
                    "invocation_recovery_required",
                    "a prior write attempt requires authoritative reconciliation; "
                    f"reason={reservation.recovery_reason or 'unspecified'}",
                )
            assert reservation.lease_token is not None
            assert reservation.fencing_token is not None
            try:
                self._budgets.reserve(request)
            except CallDenied:
                self._invocations.release(
                    request.tenant_id,
                    request.call_id,
                    invocation_digest,
                    lease_token=reservation.lease_token,
                    fencing_token=reservation.fencing_token,
                )
                raise
        except OperationInputError as error:
            self._deny(
                request,
                operation_version=operation.version,
                operation_contract_digest=operation.contract_digest,
                invocation_digest=invocation_digest,
                grant_id=grant.grant_id,
                budget_window_id=self._budgets.window_id,
                effect_class=operation.effect_class,
                reason_code="operation_input_invalid",
                message=str(error),
            )
        except CallDenied as error:
            self._deny(
                request,
                operation_version=operation.version,
                operation_contract_digest=operation.contract_digest,
                invocation_digest=invocation_digest,
                grant_id=grant.grant_id,
                budget_window_id=self._budgets.window_id,
                effect_class=operation.effect_class,
                reason_code=error.reason_code,
                message=str(error),
            )
        try:
            self._record(
                request,
                operation=operation,
                grant=grant,
                invocation_digest=invocation_digest,
                decision=CallDecision.AUTHORIZED,
                reason_code="authority_and_budget_reserved",
            )
        except BaseException as receipt_error:
            try:
                self._invocations.release(
                    request.tenant_id,
                    request.call_id,
                    invocation_digest,
                    lease_token=reservation.lease_token,
                    fencing_token=reservation.fencing_token,
                )
            except Exception as recovery_error:
                raise CallRecoveryRequired(
                    "authorization_receipt_recovery_required",
                    "authorization receipt persistence and invocation release "
                    "require reconciliation",
                ) from recovery_error
            raise receipt_error
        context = OperationContext(
            call_id=request.call_id,
            caller_id=request.caller_id,
            actor_id=request.actor_id,
            tenant_id=request.tenant_id,
            resource_ids=request.resource_ids,
            requested_at=request.requested_at,
            approval_id=request.approval_id,
        )
        try:
            output = dict(operation.encode(operation.execute(context, typed_input)))
            output_json = canonical_json(output)
            result_digest = canonical_digest(json.loads(output_json))
        except Exception as error:
            if operation.effect_class is EffectClass.READ:
                self._invocations.release(
                    request.tenant_id,
                    request.call_id,
                    invocation_digest,
                    lease_token=reservation.lease_token,
                    fencing_token=reservation.fencing_token,
                )
            else:
                self._invocations.mark_recovery_required(
                    request.tenant_id,
                    request.call_id,
                    invocation_digest,
                    lease_token=reservation.lease_token,
                    fencing_token=reservation.fencing_token,
                    reason_code=f"ambiguous_{type(error).__name__}",
                )
            self._record(
                request,
                operation=operation,
                grant=grant,
                invocation_digest=invocation_digest,
                decision=CallDecision.FAILED,
                reason_code=type(error).__name__,
            )
            raise
        stored = StoredCallOutcome(
            operation_version=operation.version,
            operation_contract_digest=operation.contract_digest,
            output_json=output_json,
            result_digest=result_digest,
        )
        try:
            self._invocations.commit(
                request.tenant_id,
                request.call_id,
                invocation_digest,
                lease_token=reservation.lease_token,
                fencing_token=reservation.fencing_token,
                outcome=stored,
            )
        except Exception as error:
            try:
                self._invocations.mark_recovery_required(
                    request.tenant_id,
                    request.call_id,
                    invocation_digest,
                    lease_token=reservation.lease_token,
                    fencing_token=reservation.fencing_token,
                    reason_code=f"completion_{type(error).__name__}",
                )
            except Exception:
                pass
            raise
        receipt = self._record(
            request,
            operation=operation,
            grant=grant,
            invocation_digest=invocation_digest,
            decision=CallDecision.SUCCEEDED,
            reason_code="operation_completed",
            result_digest=result_digest,
        )
        return CallResult(stored.decoded_output(), receipt)

    def _authorize_request_time(
        self,
        request: CallRequest,
        *,
        evaluated_at: datetime,
    ) -> None:
        if request.requested_at < evaluated_at - self._max_request_age:
            raise CallDenied(
                "request_time_stale",
                "the request requires a fresh service-evaluated time window",
            )
        if request.requested_at > evaluated_at + self._max_future_clock_skew:
            raise CallDenied(
                "request_time_future",
                "the request time exceeds the permitted service clock skew",
            )

    def _authorize_approval(
        self,
        request: CallRequest,
        operation: OperationDefinition[Any, Any],
        *,
        evaluated_at: datetime,
    ) -> None:
        if not operation.effect_class.requires_approval:
            return
        if request.approval_id is None:
            raise CallDenied(
                "approval_required",
                "broad writes require an exact, active approval",
            )
        approval = self._approvals.get(request.approval_id)
        if approval is None:
            raise CallDenied(
                "approval_missing",
                "the requested approval identity is absent",
            )
        approval.authorize(
            request,
            operation_version=operation.version,
            operation_contract_digest=operation.contract_digest,
            effect_class=operation.effect_class,
            evaluated_at=evaluated_at,
        )

    def _record(
        self,
        request: CallRequest,
        *,
        operation: OperationDefinition[Any, Any],
        grant: CallerGrant,
        invocation_digest: str,
        decision: CallDecision,
        reason_code: str,
        result_digest: str | None = None,
    ) -> CallReceipt:
        return self._append_receipt(
            request,
            operation_version=operation.version,
            operation_contract_digest=operation.contract_digest,
            invocation_digest=invocation_digest,
            grant_id=grant.grant_id,
            budget_window_id=self._budgets.window_id,
            effect_class=operation.effect_class,
            decision=decision,
            reason_code=reason_code,
            result_digest=result_digest,
        )

    def _append_receipt(
        self,
        request: CallRequest,
        *,
        operation_version: str,
        operation_contract_digest: str | None = None,
        invocation_digest: str | None = None,
        grant_id: str | None = None,
        budget_window_id: str | None = None,
        effect_class: EffectClass,
        decision: CallDecision,
        reason_code: str,
        result_digest: str | None = None,
    ) -> CallReceipt:
        receipt = CallReceipt(
            receipt_id=self._receipt_id_factory(),
            call_id=request.call_id,
            caller_id=request.caller_id,
            actor_id=request.actor_id,
            tenant_id=request.tenant_id,
            operation_name=request.operation_name,
            operation_version=operation_version,
            operation_contract_digest=operation_contract_digest,
            effect_class=effect_class,
            resource_ids=request.resource_ids,
            payload_digest=request.payload_digest,
            invocation_digest=invocation_digest,
            decision=decision,
            reason_code=reason_code,
            grant_id=grant_id,
            budget_window_id=budget_window_id,
            approval_id=request.approval_id,
            result_digest=result_digest,
            requested_at=request.requested_at,
            recorded_at=require_aware_utc(self._clock()),
        )
        self._receipts.append(receipt)
        return receipt

    def _deny(
        self,
        request: CallRequest,
        *,
        operation_version: str,
        operation_contract_digest: str | None = None,
        invocation_digest: str | None = None,
        grant_id: str | None = None,
        budget_window_id: str | None = None,
        effect_class: EffectClass,
        reason_code: str,
        message: str,
    ) -> None:
        self._append_receipt(
            request,
            operation_version=operation_version,
            operation_contract_digest=operation_contract_digest,
            invocation_digest=invocation_digest,
            grant_id=grant_id,
            budget_window_id=budget_window_id,
            effect_class=effect_class,
            decision=CallDecision.DENIED,
            reason_code=reason_code,
        )
        raise CallDenied(reason_code, message)
