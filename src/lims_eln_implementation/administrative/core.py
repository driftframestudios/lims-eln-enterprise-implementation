"""Immutable reference lookup and pure policy evaluation for synthetic studies.

Catalog preparation is expected O(N + A) plus text normalization; exact lookup
is expected O(1), alias lookup O(L + K). Policy preparation is O(P + V) and an
evaluation O(I log I + P + matched output), including the shared input ordering,
where P is predicates, V their values,
and I the admitted input values. Hash-table worst cases remain distinct.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from types import MappingProxyType
from typing import Annotated, Literal, Mapping
import unicodedata

from pydantic import Field, TypeAdapter, model_validator
from lims_eln_contracts import canonical_sha256
from lims_eln_contracts.administrative_study import StudyBinding, SyntheticStudySource
from lims_eln_contracts.external_administrative import (
    AdministrativeDecision, ClassificationDisposition, ClassificationState,
    ConflictBehavior, CoverageEnrollment, IdentifiedTerm, InsuranceClassification,
    MethodCoordinate, MethodKind, PolicyEvaluation, PolicyEvaluationState,
    PolicyInputAvailability, PolicyInputDigestMaterial, PolicyRule, PolicyRuleSet, PredicateOperator,
    VersionedArtifactRef, build_policy_input_digest_material,
)
from lims_eln_contracts.primitives import ContractModel, Identifier, NonEmptyText, SemanticVersion, UtcTimestamp


_UTC_TIMESTAMP = TypeAdapter(UtcTimestamp)


class AdministrativeBoundaryError(ValueError):
    """A fixed domain code suitable for public recovery summaries."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def normalize_alias(value: str) -> str:
    if type(value) is not str or len(value) > 2048:
        raise AdministrativeBoundaryError("alias_text_boundary")
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


class CatalogAlias(ContractModel):
    label: Annotated[str, Field(min_length=1, max_length=2048)]
    term_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=32)]


class ReferenceCode(ContractModel):
    system: Identifier
    release: SemanticVersion
    code: Annotated[str, Field(min_length=1, max_length=64)]
    reportability: Literal["category", "reportable", "unknown"]
    description: Annotated[str, Field(min_length=1, max_length=1024)]


class InsuranceCatalog(ContractModel):
    catalog_id: Identifier
    version: SemanticVersion
    source: SyntheticStudySource
    insurance_terms: Annotated[tuple[IdentifiedTerm, ...], Field(min_length=1, max_length=10000)]
    aliases: Annotated[tuple[CatalogAlias, ...], Field(max_length=20000)]
    diagnosis_codes: Annotated[tuple[ReferenceCode, ...], Field(max_length=10000)]

    @model_validator(mode="after")
    def complete_identity(self):
        ids = {term.term_id for term in self.insurance_terms}
        if len(ids) != len(self.insurance_terms):
            raise ValueError("catalog term identities are unique")
        keys = {(code.system, code.release, code.code) for code in self.diagnosis_codes}
        if len(keys) != len(self.diagnosis_codes):
            raise ValueError("reference code identities are unique")
        aliases = set()
        for alias in self.aliases:
            key = normalize_alias(alias.label)
            if not key or key in aliases:
                raise ValueError("normalized alias identities are nonempty and unique")
            aliases.add(key)
            if len(set(alias.term_ids)) != len(alias.term_ids) or not set(alias.term_ids) <= ids:
                raise ValueError("alias candidates resolve uniquely to catalog terms")
        return self


@dataclass(frozen=True, slots=True, init=False)
class CatalogSnapshot:
    """One owned immutable catalog; successor admission creates another instance."""

    document: InsuranceCatalog
    binding: StudyBinding
    _terms: Mapping[str, IdentifiedTerm]
    _aliases: Mapping[str, tuple[str, ...]]
    _codes: Mapping[tuple[str, str, str], ReferenceCode]

    def __init__(self, catalog: InsuranceCatalog):
        object.__setattr__(self, "document", catalog)
        object.__setattr__(self, "binding", StudyBinding(artifact_id=catalog.catalog_id, version=catalog.version, digest=canonical_sha256(catalog)))
        object.__setattr__(self, "_terms", MappingProxyType({term.term_id: term for term in catalog.insurance_terms}))
        object.__setattr__(self, "_aliases", MappingProxyType({normalize_alias(alias.label): tuple(alias.term_ids) for alias in catalog.aliases}))
        object.__setattr__(self, "_codes", MappingProxyType({(code.system, code.release, code.code): code for code in catalog.diagnosis_codes}))

    def lookup_code(self, system: str, release: str, code: str) -> ReferenceCode | None:
        """Exact source keys retain punctuation and reportability meaning."""
        for value in (system, release, code):
            if type(value) is not str or len(value) > 128:
                raise AdministrativeBoundaryError("code_key_boundary")
        return self._codes.get((system, release, code))

    def classify(self, raw_label: str | None, *, classification_id: str, context_ref: str) -> InsuranceClassification:
        key = normalize_alias(raw_label) if raw_label is not None else ""
        candidates = tuple(self._terms[item] for item in self._aliases.get(key, ()))
        state = ClassificationState.CLASSIFIED if len(candidates) == 1 else ClassificationState.AMBIGUOUS if candidates else ClassificationState.UNKNOWN
        # A whitespace-only source has no admitted raw-label content. Its exact
        # input remains in the study document; classification uses explicit absence.
        source_label = raw_label if key else None
        return InsuranceClassification(
            classification_id=classification_id,
            context_ref=context_ref,
            raw_label=source_label,
            raw_label_field="insurance_description",
            assigned_terms=candidates if len(candidates) == 1 else (),
            candidate_terms=candidates if len(candidates) > 1 else (),
            state=state,
            multiple=False,
            method=MethodCoordinate(method_id="exact-alias-classifier", method_version="1.0.0", kind=MethodKind.DETERMINISTIC_TRANSFORM, code=VersionedArtifactRef(artifact_id="enterprise-administrative-core", version="1.0.0", digest=canonical_sha256("NFC-casefold-whitespace-alias-v1"))),
            ambiguity=None if len(candidates) == 1 else "Several catalog terms match." if candidates else "The catalog supplies no exact candidate for the admitted value.",
            disposition=ClassificationDisposition.PROPOSED,
            provenance_refs=(self.document.source.review_ref,),
        )


@dataclass(frozen=True, slots=True)
class PreparedPredicate:
    input_id: str
    operator: PredicateOperator
    expected: frozenset[str]

    def matches(self, observed: frozenset[str] | None) -> bool:
        if observed is None:
            return False
        if self.operator is PredicateOperator.PRESENT:
            return True
        if self.operator is PredicateOperator.EQUALS:
            return observed == self.expected
        if self.operator is PredicateOperator.CONTAINS_ANY:
            return bool(observed & self.expected)
        return self.expected <= observed


@dataclass(frozen=True, slots=True)
class PolicyAssessment:
    evaluation: PolicyEvaluation
    reason: Literal["assigned", "missing_input", "conflict", "no_match"]


@dataclass(frozen=True, slots=True, init=False)
class PreparedPolicy:
    """Prepare one ruleset once; retain inclusive source date endpoints explicitly."""

    document: PolicyRuleSet
    _rules: tuple[tuple[PolicyRule, tuple[PreparedPredicate, ...]], ...]
    _rank: Mapping[str, int]

    def __init__(self, policy: PolicyRuleSet):
        if len(policy.rules) > 1000 or len(policy.input_requirements) > 64:
            raise AdministrativeBoundaryError("policy_size_boundary")
        for rule in policy.rules:
            if len(rule.when_all) > 64 or any(len(p.values) > 128 or any(len(v) > 2048 for v in p.values) for p in rule.when_all):
                raise AdministrativeBoundaryError("predicate_size_boundary")
        object.__setattr__(self, "document", policy)
        object.__setattr__(self, "_rules", tuple((rule, tuple(PreparedPredicate(p.input_id, p.operator, frozenset(p.values)) for p in rule.when_all)) for rule in policy.rules))
        object.__setattr__(self, "_rank", MappingProxyType({key: rank for rank, key in enumerate(policy.precedence)}))

    def bind_inputs(self, decision: AdministrativeDecision, classifications: Mapping[str, InsuranceClassification], enrollments: Mapping[str, CoverageEnrollment]) -> PolicyInputDigestMaterial:
        """Resolve owned keys and context before the shared review-aware projection."""
        if len(decision.classification_refs) > 64 or len(decision.enrollment_refs) > 64:
            raise AdministrativeBoundaryError("policy_source_boundary")
        if decision.policy_evaluation.policy_rule_set_ref != self.document.policy_id or decision.policy_evaluation.policy_digest != self.document.policy_digest:
            raise AdministrativeBoundaryError("policy_coordinate_mismatch")
        try:
            selected_classifications = {key: classifications[key] for key in decision.classification_refs}
            selected_enrollments = {key: enrollments[key] for key in decision.enrollment_refs}
            if any(key != item.classification_id or item.context_ref != decision.context_ref for key, item in selected_classifications.items()) or any(key != item.enrollment_id or item.context_ref != decision.context_ref for key, item in selected_enrollments.items()):
                raise AdministrativeBoundaryError("policy_input_identity_mismatch")
            if sum(len(item.assigned_terms) for item in selected_classifications.values()) > 8192:
                raise AdministrativeBoundaryError("policy_value_boundary")
            return build_policy_input_digest_material(decision, self.document, selected_classifications, selected_enrollments)
        except AdministrativeBoundaryError:
            raise
        except (KeyError, ValueError):
            raise AdministrativeBoundaryError("reviewed_policy_inputs_required") from None

    def evaluate(self, decision: AdministrativeDecision, classifications: Mapping[str, InsuranceClassification], enrollments: Mapping[str, CoverageEnrollment], *, service_day: date, evaluated_at: str) -> PolicyAssessment:
        if type(service_day) is not date:
            raise AdministrativeBoundaryError("service_date_boundary")
        try:
            evaluated_at = _UTC_TIMESTAMP.validate_python(evaluated_at, strict=True)
            evaluation_day = datetime.fromisoformat(evaluated_at).astimezone(timezone.utc).date().isoformat()
        except (TypeError, ValueError):
            raise AdministrativeBoundaryError("evaluation_timestamp_boundary") from None
        interval = self.document.effective_interval
        day = service_day.isoformat()
        for value, code in ((day, "service_date_outside_policy_interval"), (evaluation_day, "evaluation_time_outside_policy_interval")):
            if value < interval.starts_on or (interval.ends_on is not None and value > interval.ends_on):
                raise AdministrativeBoundaryError(code)
        material = self.bind_inputs(decision, classifications, enrollments)
        inputs = {item.input_id: None if item.availability is PolicyInputAvailability.MISSING else frozenset(value.match_value for value in item.values) for item in material.inputs}
        if sum(len(value) for value in inputs.values() if value is not None) > 8192:
            raise AdministrativeBoundaryError("policy_value_boundary")
        missing = tuple(requirement.input_id for requirement in self.document.input_requirements if requirement.required and inputs[requirement.input_id] is None)
        matched = tuple(rule for rule, predicates in self._rules if all(predicate.matches(inputs[predicate.input_id]) for predicate in predicates))
        conflicts = tuple(rule.rule_id for rule in matched) if len(matched) > 1 else ()
        selected = None
        state = PolicyEvaluationState.ABSTAINED
        reason = "no_match"
        if missing:
            reason = "missing_input"
            if self.document.missing_input_behavior.value == "require_review":
                state = PolicyEvaluationState.REVIEW_REQUIRED
        else:
            if matched:
                if conflicts and self.document.conflict_behavior is not ConflictBehavior.HIGHEST_PRECEDENCE:
                    reason = "conflict"
                    if self.document.conflict_behavior is ConflictBehavior.REQUIRE_REVIEW:
                        state = PolicyEvaluationState.REVIEW_REQUIRED
                else:
                    selected = min(matched, key=lambda rule: self._rank[rule.rule_id])
                    state, reason = PolicyEvaluationState.ASSIGNED, "assigned"
        digest = material.calculated_digest()
        identity = canonical_sha256((self.document.policy_digest, digest, day))[7:31]
        evaluation = PolicyEvaluation(evaluation_id="evaluation-" + identity, policy_rule_set_ref=self.document.policy_id, policy_digest=self.document.policy_digest, input_digest_profile=material.profile, input_material=material, input_digest=digest, matched_rule_refs=tuple(r.rule_id for r in matched), selected_rule_ref=selected.rule_id if selected else None, missing_input_ids=missing, conflicting_rule_refs=conflicts, state=state, outcome=selected.outcome if selected else None, evaluated_at=evaluated_at)
        return PolicyAssessment(evaluation, reason)
