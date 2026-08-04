"""Bounded application entry point for the inspectable specimen journey."""

from __future__ import annotations

from base64 import b64decode, b64encode
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping

from .bounded_caller import (
    BoundedCaller,
    BudgetPolicy,
    CallRequest,
    CallerGrant,
    EffectClass,
    InMemoryApprovalStore,
    InMemoryBudgetLedger,
    InMemoryCallerGrantStore,
    InMemoryCallReceiptStore,
    InMemoryInvocationLedger,
    OperationContext,
    OperationDefinition,
    OperationInputError,
    OperationRegistry,
)
from .bounded_examples import specimen_resource
from .custody import CustodyService
from .instrument import IngressDisposition, InstrumentEnvelope, InstrumentIngress
from .lifecycle import LifecycleService
from .model import (
    Command,
    DomainEvent,
    SpecimenAggregate,
    SpecimenState,
    canonical_digest,
    require_aware_utc,
)
from .vendors import ProjectionOutcome, VendorProjectionService


_OPERATION_NAME = "specimen.golden_journey.execute"
_OPERATION_VERSION = "1.0.0"
_CAPABILITY = "specimen.golden_journey.execute"


@dataclass(frozen=True, slots=True)
class GoldenSpecimenOutcome:
    aggregate: SpecimenAggregate
    instrument_digest: str
    projection: ProjectionOutcome
    custody_location: str
    call_receipt_id: str
    call_decision: str


@dataclass(frozen=True, slots=True)
class _GoldenSpecimenInput:
    specimen_id: str
    raw_instrument_json: bytes
    vendor_payload: Mapping[str, Any]

    @classmethod
    def decode(cls, payload: Mapping[str, Any]) -> _GoldenSpecimenInput:
        expected = {"specimen_id", "raw_instrument_base64", "vendor_payload"}
        if set(payload) != expected:
            raise OperationInputError(
                "golden specimen input requires specimen identity, instrument bytes, "
                "and vendor payload"
            )
        specimen_id = payload["specimen_id"]
        encoded = payload["raw_instrument_base64"]
        vendor_payload = payload["vendor_payload"]
        if not isinstance(specimen_id, str) or not specimen_id.strip():
            raise OperationInputError("specimen_id requires a populated identity")
        if not isinstance(encoded, str) or not encoded:
            raise OperationInputError("raw instrument content requires base64 text")
        if not isinstance(vendor_payload, Mapping):
            raise OperationInputError("vendor_payload requires an object")
        try:
            raw = b64decode(encoded, validate=True)
        except ValueError as error:
            raise OperationInputError(
                "raw instrument content requires canonical base64"
            ) from error
        if not raw or len(raw) > 1_048_576:
            raise OperationInputError(
                "raw instrument content requires 1..1048576 bytes"
            )
        return cls(specimen_id, raw, dict(vendor_payload))


class _GoldenSpecimenWorkflow:
    """Internal operation implementation reachable through ``BoundedCaller``."""

    def __init__(
        self,
        *,
        lifecycle: LifecycleService,
        custody: CustodyService,
        ingress: InstrumentIngress,
        projection: VendorProjectionService,
    ) -> None:
        self._lifecycle = lifecycle
        self._custody = custody
        self._ingress = ingress
        self._projection = projection

    def execute(
        self,
        context: OperationContext,
        value: _GoldenSpecimenInput,
    ) -> GoldenSpecimenOutcome:
        aggregate = self._lifecycle.register(
            _command(
                context=context,
                specimen_id=value.specimen_id,
                suffix="register",
                action="register",
                expected_version=0,
                payload={"specimen_type": "synthetic_plasma"},
            )
        )
        aggregate = self._lifecycle.transition(
            _command(
                context=context,
                specimen_id=value.specimen_id,
                suffix="accession",
                action="accession",
                expected_version=aggregate.version,
            )
        )
        position = self._custody.place(
            tenant_id=context.tenant_id,
            specimen_id=value.specimen_id,
            location="SYN-LAB-A/RECEIVING",
            custodian_id=context.actor_id,
            expected_version=0,
            transfer_id=f"{context.call_id}:custody",
            occurred_at=context.requested_at,
        )
        ingress = self._ingress.ingest(
            InstrumentEnvelope(
                tenant_id=context.tenant_id,
                message_id=f"{context.call_id}:instrument",
                instrument_id="SYN-INSTRUMENT-01",
                specimen_id=value.specimen_id,
                captured_at=context.requested_at,
                media_type="application/json",
                raw_bytes=value.raw_instrument_json,
            )
        )
        if ingress.disposition is not IngressDisposition.ACCEPTED:
            raise RuntimeError(f"instrument review required: {ingress.reason_code}")
        assert ingress.normalized_digest is not None
        projection = self._projection.project(
            tenant_id=context.tenant_id,
            request_id=f"{context.call_id}:vendor",
            external_identity=value.specimen_id,
            expected_revision=0,
            payload={
                **dict(value.vendor_payload),
                "instrument_digest": ingress.normalized_digest,
            },
        )
        return GoldenSpecimenOutcome(
            aggregate=aggregate,
            instrument_digest=ingress.normalized_digest,
            projection=projection,
            custody_location=position.location,
            call_receipt_id="pending",
            call_decision="pending",
        )


class GoldenSpecimenApplication:
    """Public boundary that can execute the journey only through bounded authority."""

    def __init__(self, *, caller: BoundedCaller, caller_id: str) -> None:
        if not caller_id.strip():
            raise ValueError("caller_id requires a workload identity")
        self._caller = caller
        self._caller_id = caller_id

    def process(
        self,
        *,
        call_id: str,
        tenant_id: str,
        specimen_id: str,
        actor_id: str,
        occurred_at: datetime,
        raw_instrument_json: bytes,
        vendor_payload: Mapping[str, Any],
    ) -> GoldenSpecimenOutcome:
        result = self._caller.invoke(
            CallRequest(
                call_id=call_id,
                caller_id=self._caller_id,
                actor_id=actor_id,
                tenant_id=tenant_id,
                operation_name=_OPERATION_NAME,
                resource_ids=(specimen_resource(specimen_id),),
                payload={
                    "specimen_id": specimen_id,
                    "raw_instrument_base64": b64encode(raw_instrument_json).decode(
                        "ascii"
                    ),
                    "vendor_payload": dict(vendor_payload),
                },
                requested_at=require_aware_utc(occurred_at),
            )
        )
        outcome = _decode_outcome(result.output)
        return GoldenSpecimenOutcome(
            aggregate=outcome.aggregate,
            instrument_digest=outcome.instrument_digest,
            projection=outcome.projection,
            custody_location=outcome.custody_location,
            call_receipt_id=result.receipt.receipt_id,
            call_decision=result.receipt.decision.value,
        )


def register_golden_specimen_operation(
    registry: OperationRegistry,
    *,
    lifecycle: LifecycleService,
    custody: CustodyService,
    ingress: InstrumentIngress,
    projection: VendorProjectionService,
) -> None:
    """Register the only public path to the composed specimen workflow."""

    workflow = _GoldenSpecimenWorkflow(
        lifecycle=lifecycle,
        custody=custody,
        ingress=ingress,
        projection=projection,
    )
    contract_digest = canonical_digest(
        {
            "name": _OPERATION_NAME,
            "version": _OPERATION_VERSION,
            "effect_class": EffectClass.IDEMPOTENT_NARROW_WRITE.value,
            "capability": _CAPABILITY,
            "fields": [
                "raw_instrument_base64",
                "specimen_id",
                "vendor_payload",
            ],
        }
    )
    registry.register(
        OperationDefinition[
            _GoldenSpecimenInput,
            GoldenSpecimenOutcome,
        ](
            name=_OPERATION_NAME,
            version=_OPERATION_VERSION,
            contract_digest=contract_digest,
            effect_class=EffectClass.IDEMPOTENT_NARROW_WRITE,
            capability=_CAPABILITY,
            decode=_GoldenSpecimenInput.decode,
            resources=lambda value: (specimen_resource(value.specimen_id),),
            execute=workflow.execute,
            encode=_encode_outcome,
        )
    )


def build_reference_golden_specimen_application(
    *,
    lifecycle: LifecycleService,
    custody: CustodyService,
    ingress: InstrumentIngress,
    projection: VendorProjectionService,
    tenant_id: str,
    caller_id: str,
    actor_ids: frozenset[str],
    clock: Callable[[], datetime],
) -> GoldenSpecimenApplication:
    """Compose a complete local proof with explicit, bounded authority stores.

    Production composition supplies durable grant, budget, invocation, and
    receipt stores to ``BoundedCaller`` while preserving this public boundary.
    """

    registry = OperationRegistry()
    register_golden_specimen_operation(
        registry,
        lifecycle=lifecycle,
        custody=custody,
        ingress=ingress,
        projection=projection,
    )
    now = require_aware_utc(clock())
    caller = BoundedCaller(
        registry=registry,
        grants=InMemoryCallerGrantStore(
            (
                CallerGrant(
                    grant_id=f"reference:{caller_id}",
                    caller_id=caller_id,
                    actor_ids=actor_ids,
                    tenant_id=tenant_id,
                    capabilities=frozenset({_CAPABILITY}),
                    resource_prefixes=("specimen:SYN-",),
                    expires_at=now + timedelta(hours=1),
                ),
            )
        ),
        approvals=InMemoryApprovalStore(),
        budgets=InMemoryBudgetLedger(
            BudgetPolicy(
                window_id="reference-hour",
                caller_call_limits={caller_id: 100},
                tenant_call_limits={tenant_id: 500},
                max_resources_per_call=1,
                max_payload_bytes=1_400_000,
            )
        ),
        receipts=InMemoryCallReceiptStore(),
        invocations=InMemoryInvocationLedger(),
        clock=clock,
    )
    return GoldenSpecimenApplication(caller=caller, caller_id=caller_id)


def _command(
    *,
    context: OperationContext,
    specimen_id: str,
    suffix: str,
    action: str,
    expected_version: int,
    payload: Mapping[str, Any] | None = None,
) -> Command:
    return Command(
        command_id=f"{context.call_id}:{suffix}",
        tenant_id=context.tenant_id,
        specimen_id=specimen_id,
        actor_id=context.actor_id,
        action=action,
        expected_version=expected_version,
        occurred_at=context.requested_at,
        payload=dict(payload or {}),
    )


def _encode_event(event: DomainEvent) -> Mapping[str, Any]:
    return {
        "event_id": event.event_id,
        "tenant_id": event.tenant_id,
        "specimen_id": event.specimen_id,
        "aggregate_version": event.aggregate_version,
        "event_type": event.event_type,
        "actor_id": event.actor_id,
        "command_id": event.command_id,
        "command_digest": event.command_digest,
        "occurred_at": event.occurred_at.isoformat(),
        "payload": dict(event.payload),
        "reason_code": event.reason_code,
    }


def _encode_outcome(outcome: GoldenSpecimenOutcome) -> Mapping[str, Any]:
    return {
        "aggregate": {
            "tenant_id": outcome.aggregate.tenant_id,
            "specimen_id": outcome.aggregate.specimen_id,
            "state": outcome.aggregate.state.value,
            "version": outcome.aggregate.version,
            "attributes": dict(outcome.aggregate.attributes),
            "events": [_encode_event(event) for event in outcome.aggregate.events],
        },
        "instrument_digest": outcome.instrument_digest,
        "projection": {
            "vendor_name": outcome.projection.vendor_name,
            "external_identity": outcome.projection.external_identity,
            "revision": outcome.projection.revision,
            "canonical_digest": outcome.projection.canonical_digest,
            "reconciled": outcome.projection.reconciled,
            "trace_id": outcome.projection.trace_id,
        },
        "custody_location": outcome.custody_location,
    }


def _decode_outcome(value: Mapping[str, Any]) -> GoldenSpecimenOutcome:
    aggregate_value = value["aggregate"]
    projection_value = value["projection"]
    assert isinstance(aggregate_value, Mapping)
    assert isinstance(projection_value, Mapping)
    events = tuple(
        DomainEvent(
            event_id=str(event["event_id"]),
            tenant_id=str(event["tenant_id"]),
            specimen_id=str(event["specimen_id"]),
            aggregate_version=int(event["aggregate_version"]),
            event_type=str(event["event_type"]),
            actor_id=str(event["actor_id"]),
            command_id=str(event["command_id"]),
            command_digest=str(event["command_digest"]),
            occurred_at=datetime.fromisoformat(str(event["occurred_at"])),
            payload=dict(event["payload"]),
            reason_code=(
                None if event["reason_code"] is None else str(event["reason_code"])
            ),
        )
        for event in aggregate_value["events"]
    )
    aggregate = SpecimenAggregate(
        tenant_id=str(aggregate_value["tenant_id"]),
        specimen_id=str(aggregate_value["specimen_id"]),
        state=SpecimenState(str(aggregate_value["state"])),
        version=int(aggregate_value["version"]),
        attributes=dict(aggregate_value["attributes"]),
        events=events,
    )
    projection = ProjectionOutcome(
        vendor_name=str(projection_value["vendor_name"]),
        external_identity=str(projection_value["external_identity"]),
        revision=int(projection_value["revision"]),
        canonical_digest=str(projection_value["canonical_digest"]),
        reconciled=bool(projection_value["reconciled"]),
        trace_id=str(projection_value["trace_id"]),
    )
    return GoldenSpecimenOutcome(
        aggregate=aggregate,
        instrument_digest=str(value["instrument_digest"]),
        projection=projection,
        custody_location=str(value["custody_location"]),
        call_receipt_id="decoded-before-receipt",
        call_decision="decoded-before-receipt",
    )
