"""Typed read, narrow-write, and broad-write specimen operation examples."""

from __future__ import annotations

from dataclasses import dataclass, replace
from threading import Lock
from typing import Any, Mapping, Protocol

from .bounded_caller import (
    EffectClass,
    OperationContext,
    OperationDefinition,
    OperationInputError,
    OperationRegistry,
)
from .model import RevisionConflict, canonical_digest


def _exact_fields(
    payload: Mapping[str, Any],
    *,
    required: frozenset[str],
) -> None:
    observed = frozenset(payload)
    if observed != required:
        missing = sorted(required - observed)
        extra = sorted(observed - required)
        raise OperationInputError(
            f"operation payload requires exact fields; missing={missing}; extra={extra}"
        )


def _bounded_text(value: Any, *, field: str, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise OperationInputError(f"{field} requires 1..{maximum} text characters")
    if any(ord(character) < 32 for character in value):
        raise OperationInputError(f"{field} requires printable text")
    return value


def _nonnegative_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise OperationInputError(f"{field} requires zero or a positive integer")
    return value


def specimen_resource(specimen_id: str) -> str:
    return f"specimen:{specimen_id}"


def _operation_contract_digest(
    *,
    name: str,
    version: str,
    effect_class: EffectClass,
    capability: str,
    input_fields: tuple[str, ...],
) -> str:
    return canonical_digest(
        {
            "name": name,
            "version": version,
            "effect_class": effect_class.value,
            "capability": capability,
            "input_fields": list(input_fields),
        }
    )


@dataclass(frozen=True, slots=True)
class SpecimenRecord:
    tenant_id: str
    specimen_id: str
    version: int
    lifecycle_state: str
    review_flag: str


class SpecimenOperationBackend(Protocol):
    """Durable implementation seam for the bounded operation examples."""

    def read(self, *, tenant_id: str, specimen_id: str) -> SpecimenRecord: ...

    def set_review_flag(
        self,
        *,
        tenant_id: str,
        specimen_id: str,
        expected_version: int,
        review_flag: str,
        call_id: str,
    ) -> SpecimenRecord: ...

    def quarantine_many(
        self,
        *,
        tenant_id: str,
        specimen_ids: tuple[str, ...],
        reason_code: str,
        call_id: str,
    ) -> tuple[SpecimenRecord, ...]: ...


class InMemorySpecimenOperationBackend:
    """Atomic conformance double for a durable specimen-operation adapter."""

    def __init__(self, records: tuple[SpecimenRecord, ...]) -> None:
        self._records = {
            (record.tenant_id, record.specimen_id): record for record in records
        }
        self._outcomes: dict[tuple[str, str], object] = {}
        self._lock = Lock()

    def read(self, *, tenant_id: str, specimen_id: str) -> SpecimenRecord:
        try:
            return self._records[(tenant_id, specimen_id)]
        except KeyError as error:
            raise LookupError(
                f"specimen {specimen_id} requires an existing tenant-scoped record"
            ) from error

    def set_review_flag(
        self,
        *,
        tenant_id: str,
        specimen_id: str,
        expected_version: int,
        review_flag: str,
        call_id: str,
    ) -> SpecimenRecord:
        identity = (tenant_id, call_id)
        with self._lock:
            replay = self._outcomes.get(identity)
            if isinstance(replay, SpecimenRecord):
                return replay
            current = self.read(tenant_id=tenant_id, specimen_id=specimen_id)
            if current.version != expected_version:
                raise RevisionConflict(
                    f"specimen {specimen_id} is revision {current.version}; "
                    "reload and plan from the stored revision"
                )
            result = replace(
                current,
                version=current.version + 1,
                review_flag=review_flag,
            )
            self._records[(tenant_id, specimen_id)] = result
            self._outcomes[identity] = result
            return result

    def quarantine_many(
        self,
        *,
        tenant_id: str,
        specimen_ids: tuple[str, ...],
        reason_code: str,
        call_id: str,
    ) -> tuple[SpecimenRecord, ...]:
        identity = (tenant_id, call_id)
        with self._lock:
            replay = self._outcomes.get(identity)
            if isinstance(replay, tuple):
                return replay
            current = tuple(
                self.read(tenant_id=tenant_id, specimen_id=specimen_id)
                for specimen_id in specimen_ids
            )
            result = tuple(
                replace(
                    record,
                    version=record.version + 1,
                    lifecycle_state="quarantined",
                    review_flag=reason_code,
                )
                for record in current
            )
            for record in result:
                self._records[(tenant_id, record.specimen_id)] = record
            self._outcomes[identity] = result
            return result


@dataclass(frozen=True, slots=True)
class ReadSpecimenInput:
    specimen_id: str

    @classmethod
    def decode(cls, payload: Mapping[str, Any]) -> ReadSpecimenInput:
        _exact_fields(payload, required=frozenset({"specimen_id"}))
        return cls(_bounded_text(payload["specimen_id"], field="specimen_id"))


@dataclass(frozen=True, slots=True)
class SetReviewFlagInput:
    specimen_id: str
    expected_version: int
    review_flag: str

    @classmethod
    def decode(cls, payload: Mapping[str, Any]) -> SetReviewFlagInput:
        _exact_fields(
            payload,
            required=frozenset({"specimen_id", "expected_version", "review_flag"}),
        )
        return cls(
            specimen_id=_bounded_text(payload["specimen_id"], field="specimen_id"),
            expected_version=_nonnegative_int(
                payload["expected_version"],
                field="expected_version",
            ),
            review_flag=_bounded_text(
                payload["review_flag"],
                field="review_flag",
            ),
        )


@dataclass(frozen=True, slots=True)
class BulkQuarantineInput:
    specimen_ids: tuple[str, ...]
    reason_code: str

    @classmethod
    def decode(cls, payload: Mapping[str, Any]) -> BulkQuarantineInput:
        _exact_fields(
            payload,
            required=frozenset({"specimen_ids", "reason_code"}),
        )
        raw_ids = payload["specimen_ids"]
        if (
            not isinstance(raw_ids, list)
            or not raw_ids
            or len(raw_ids) > 25
            or not all(isinstance(value, str) for value in raw_ids)
            or len(set(raw_ids)) != len(raw_ids)
        ):
            raise OperationInputError(
                "specimen_ids requires 1..25 unique specimen identities"
            )
        specimen_ids = tuple(
            _bounded_text(value, field="specimen_id") for value in raw_ids
        )
        return cls(
            specimen_ids=specimen_ids,
            reason_code=_bounded_text(
                payload["reason_code"],
                field="reason_code",
            ),
        )


def _encode_record(record: SpecimenRecord) -> Mapping[str, Any]:
    return {
        "tenant_id": record.tenant_id,
        "specimen_id": record.specimen_id,
        "version": record.version,
        "lifecycle_state": record.lifecycle_state,
        "review_flag": record.review_flag,
    }


def register_specimen_operations(
    registry: OperationRegistry,
    backend: SpecimenOperationBackend,
) -> None:
    """Register three operation classes without exposing backend query text."""

    def read(context: OperationContext, value: ReadSpecimenInput) -> SpecimenRecord:
        return backend.read(
            tenant_id=context.tenant_id,
            specimen_id=value.specimen_id,
        )

    def set_review_flag(
        context: OperationContext,
        value: SetReviewFlagInput,
    ) -> SpecimenRecord:
        return backend.set_review_flag(
            tenant_id=context.tenant_id,
            specimen_id=value.specimen_id,
            expected_version=value.expected_version,
            review_flag=value.review_flag,
            call_id=context.call_id,
        )

    def quarantine(
        context: OperationContext,
        value: BulkQuarantineInput,
    ) -> tuple[SpecimenRecord, ...]:
        return backend.quarantine_many(
            tenant_id=context.tenant_id,
            specimen_ids=value.specimen_ids,
            reason_code=value.reason_code,
            call_id=context.call_id,
        )

    registry.register(
        OperationDefinition[
            ReadSpecimenInput,
            SpecimenRecord,
        ](
            name="specimen.read",
            version="1.0.0",
            contract_digest=_operation_contract_digest(
                name="specimen.read",
                version="1.0.0",
                effect_class=EffectClass.READ,
                capability="specimen.read",
                input_fields=("specimen_id",),
            ),
            effect_class=EffectClass.READ,
            capability="specimen.read",
            decode=ReadSpecimenInput.decode,
            resources=lambda value: (specimen_resource(value.specimen_id),),
            execute=read,
            encode=_encode_record,
        )
    )
    registry.register(
        OperationDefinition[
            SetReviewFlagInput,
            SpecimenRecord,
        ](
            name="specimen.review_flag.set",
            version="1.0.0",
            contract_digest=_operation_contract_digest(
                name="specimen.review_flag.set",
                version="1.0.0",
                effect_class=EffectClass.IDEMPOTENT_NARROW_WRITE,
                capability="specimen.review_flag.write",
                input_fields=("expected_version", "review_flag", "specimen_id"),
            ),
            effect_class=EffectClass.IDEMPOTENT_NARROW_WRITE,
            capability="specimen.review_flag.write",
            decode=SetReviewFlagInput.decode,
            resources=lambda value: (specimen_resource(value.specimen_id),),
            execute=set_review_flag,
            encode=_encode_record,
        )
    )
    registry.register(
        OperationDefinition[
            BulkQuarantineInput,
            tuple[SpecimenRecord, ...],
        ](
            name="specimen.quarantine.bulk",
            version="1.0.0",
            contract_digest=_operation_contract_digest(
                name="specimen.quarantine.bulk",
                version="1.0.0",
                effect_class=EffectClass.APPROVAL_GATED_BROAD_WRITE,
                capability="specimen.quarantine.bulk",
                input_fields=("reason_code", "specimen_ids"),
            ),
            effect_class=EffectClass.APPROVAL_GATED_BROAD_WRITE,
            capability="specimen.quarantine.bulk",
            decode=BulkQuarantineInput.decode,
            resources=lambda value: tuple(
                specimen_resource(specimen_id) for specimen_id in value.specimen_ids
            ),
            execute=quarantine,
            encode=lambda records: {
                "records": [_encode_record(record) for record in records],
                "affected_count": len(records),
            },
        )
    )
