"""Pure, process-local review transitions over Program's portable contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
from types import MappingProxyType
from typing import Mapping

from pydantic import ValidationError

from lims_eln_contracts import canonical_sha256
from lims_eln_contracts.administrative_study import StudyBinding
from lims_eln_contracts.external_administrative import (
    AccountableReview, AdministrativeContext, AdministrativeDecision,
    CoverageEnrollment, InsuranceClassification,
)

from .core import AdministrativeBoundaryError, CatalogSnapshot, PolicyAssessment, PreparedPolicy, normalize_alias


class ReviewBoundaryError(AdministrativeBoundaryError):
    """Fixed public feedback; the original code remains the string contract."""

    stage = "review"
    recovery = "Keep the previous accepted value and reconcile the review request."

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code)
        self.message = message


class ReviewConflictError(ReviewBoundaryError):
    stage = "source_binding"
    recovery = "Refresh the displayed source and request a review bound to that snapshot."


class ReviewSelectionError(ReviewBoundaryError):
    stage = "term_selection"
    recovery = "Select distinct terms from the bound catalog and confirm an accept or revise action."


class ReviewEffectivityError(ReviewBoundaryError):
    stage = "evaluation_context"
    recovery = "Align the decision, jurisdiction, service date, and evaluation time with the accepted context."


class ReviewValidationError(ReviewBoundaryError):
    stage = "accepted_contract"
    recovery = "Reconcile the proposal and review against the classification contract before accepting."


@dataclass(frozen=True, slots=True)
class _ReviewFailure:
    error_type: type[ReviewBoundaryError]
    message: str


_REVIEW_FAILURES = MappingProxyType({
    "review_requires_proposal": _ReviewFailure(ReviewConflictError, "Review starts from a proposed classification."),
    "review_context_mismatch": _ReviewFailure(ReviewConflictError, "The proposal belongs to the displayed context."),
    "review_proposal_changed": _ReviewFailure(ReviewConflictError, "The proposal has changed since review preparation."),
    "review_context_changed": _ReviewFailure(ReviewConflictError, "The context has changed since review preparation."),
    "review_catalog_changed": _ReviewFailure(ReviewConflictError, "The catalog has changed since review preparation."),
    "review_term_changed": _ReviewFailure(ReviewConflictError, "A proposed term differs from the bound catalog."),
    "accepted_classification_changed": _ReviewFailure(ReviewConflictError, "The accepted value differs from its reproducible review transition."),
    "review_term_budget": _ReviewFailure(ReviewSelectionError, "Select one to 32 term identifiers, each containing one to 128 characters."),
    "review_term_duplicate": _ReviewFailure(ReviewSelectionError, "Each selected term has a distinct identifier."),
    "review_term_unresolved": _ReviewFailure(ReviewSelectionError, "Every selected term resolves in the bound catalog."),
    "review_disposition_requires_acceptance": _ReviewFailure(ReviewSelectionError, "Acceptance uses an accept action or a revision with selected terms."),
    "review_decision_context_mismatch": _ReviewFailure(ReviewEffectivityError, "The decision identifies the accepted classification and context."),
    "review_jurisdiction_mismatch": _ReviewFailure(ReviewEffectivityError, "The policy and accepted context share a jurisdiction."),
    "evaluation_precedes_review": _ReviewFailure(ReviewEffectivityError, "Evaluation follows the recorded review time."),
    "review_context_outside_effectivity": _ReviewFailure(ReviewEffectivityError, "Service and evaluation dates fall within context effectivity."),
    "review_contract_invalid": _ReviewFailure(ReviewValidationError, "The proposed accepted value requires contract reconciliation."),
})


def _review_error(code: str) -> ReviewBoundaryError:
    """Select a fixed descriptor in expected O(1); caller data stays separate."""
    failure = _REVIEW_FAILURES.get(code)
    if failure is None:
        raise ValueError("review failure code requires a declared descriptor")
    return failure.error_type(code, failure.message)


@dataclass(frozen=True)
class ClassificationReviewRequest:
    """An explicit reviewer action bound to the material presented for review."""

    proposal_digest: str
    context_digest: str
    catalog: StudyBinding
    review: AccountableReview
    assigned_term_ids: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ReviewedClassification:
    """Local transition value; Program owns the serialized classification."""

    request: ClassificationReviewRequest
    classification: InsuranceClassification
    normalized_lookup: str | None

    def lineage(self) -> dict[str, object]:
        return {
            "proposal_digest": self.request.proposal_digest,
            "context_digest": self.request.context_digest,
            "catalog": self.request.catalog.model_dump(mode="json"),
            "review_id": self.request.review.review_id,
            "accepted_digest": canonical_sha256(self.classification),
            "normalized_lookup": self.normalized_lookup,
        }


def accept_classification(
    proposal: InsuranceClassification,
    context: AdministrativeContext,
    catalog: CatalogSnapshot,
    request: ClassificationReviewRequest,
) -> ReviewedClassification:
    """Return a new accepted value; the caller retains earlier snapshots.

    Runtime is O(B + T log T), with O(B + T) auxiliary space, where B is
    serialized source size and T <= 32 selected terms of at most 128 characters.
    Catalog lookups use its existing index.
    This typed API receives local values; external byte admission remains
    with the Program contracts.
    """
    if proposal.disposition != "proposed" or proposal.review is not None:
        raise _review_error("review_requires_proposal")
    if proposal.context_ref != context.context_id:
        raise _review_error("review_context_mismatch")
    if request.proposal_digest != canonical_sha256(proposal):
        raise _review_error("review_proposal_changed")
    if request.context_digest != canonical_sha256(context):
        raise _review_error("review_context_changed")
    if request.catalog != catalog.binding:
        raise _review_error("review_catalog_changed")
    if len(proposal.assigned_terms) + len(proposal.candidate_terms) > 32:
        raise _review_error("review_term_budget")
    for term in (*proposal.assigned_terms, *proposal.candidate_terms):
        if catalog.lookup_term(term.term_id) != term:
            raise _review_error("review_term_changed")
    lookup = normalize_alias(proposal.raw_label) if proposal.raw_label is not None else None
    document = proposal.model_dump(mode="json")
    disposition = request.review.disposition
    if disposition == "accept" and request.assigned_term_ids is None:
        document["disposition"] = "accepted"
    elif disposition == "revise" and request.assigned_term_ids is not None:
        ids = request.assigned_term_ids
        if type(ids) is not tuple or not 1 <= len(ids) <= 32 or any(type(key) is not str or not 1 <= len(key) <= 128 for key in ids):
            raise _review_error("review_term_budget")
        if len(set(ids)) != len(ids):
            raise _review_error("review_term_duplicate")
        terms = tuple(catalog.lookup_term(key) for key in sorted(ids))
        if any(term is None for term in terms):
            raise _review_error("review_term_unresolved")
        document.update(
            disposition="revised", state="classified", candidate_terms=[],
            assigned_terms=[term.model_dump(mode="json") for term in terms],
            multiple=len(terms) > 1, ambiguity=None,
        )
    else:
        raise _review_error("review_disposition_requires_acceptance")
    document["review"] = request.review.model_dump(mode="json")
    try:
        accepted = InsuranceClassification.model_validate_json(json.dumps(document))
    except ValidationError:
        raise _review_error("review_contract_invalid") from None
    return ReviewedClassification(request, accepted, lookup)


def evaluate_reviewed_classification(
    accepted: ReviewedClassification,
    *,
    proposal: InsuranceClassification,
    context: AdministrativeContext,
    catalog: CatalogSnapshot,
    policy: PreparedPolicy,
    decision: AdministrativeDecision,
    enrollments: Mapping[str, CoverageEnrollment],
    service_day: date,
    evaluated_at: str,
) -> PolicyAssessment:
    """Rebind a transition before evaluating its selected policy inputs."""
    reproduced = accept_classification(proposal, context, catalog, accepted.request)
    if reproduced != accepted:
        raise _review_error("accepted_classification_changed")
    if decision.context_ref != context.context_id or decision.classification_refs != (accepted.classification.classification_id,):
        raise _review_error("review_decision_context_mismatch")
    if policy.document.jurisdiction != context.jurisdiction:
        raise _review_error("review_jurisdiction_mismatch")
    assessment = policy.evaluate(
        decision, {accepted.classification.classification_id: accepted.classification},
        dict(enrollments), service_day=service_day, evaluated_at=evaluated_at,
    )
    instant = datetime.fromisoformat(evaluated_at.removesuffix("Z") + "+00:00")
    review_at = datetime.fromisoformat(accepted.request.review.reviewed_at.removesuffix("Z") + "+00:00")
    if instant < review_at:
        raise _review_error("evaluation_precedes_review")
    interval = context.effective_interval
    for day in (service_day.isoformat(), instant.date().isoformat()):
        if day < interval.starts_on or (interval.ends_on is not None and day > interval.ends_on):
            raise _review_error("review_context_outside_effectivity")
    return assessment
