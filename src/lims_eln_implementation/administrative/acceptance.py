"""Pure, process-local review transitions over Program's portable contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
from typing import Mapping

from lims_eln_contracts import canonical_sha256
from lims_eln_contracts.administrative_study import StudyBinding
from lims_eln_contracts.external_administrative import (
    AccountableReview, AdministrativeContext, AdministrativeDecision,
    CoverageEnrollment, InsuranceClassification,
)

from .core import AdministrativeBoundaryError, CatalogSnapshot, PolicyAssessment, PreparedPolicy, normalize_alias


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

    Runtime and auxiliary space are O(B + T), where B is serialized source
    size and T <= 32 selected terms. Catalog lookups use its existing index.
    This typed API receives local values; external byte admission remains
    with the Program contracts.
    """
    if proposal.disposition != "proposed" or proposal.review is not None:
        raise AdministrativeBoundaryError("review_requires_proposal")
    if proposal.context_ref != context.context_id:
        raise AdministrativeBoundaryError("review_context_mismatch")
    if request.proposal_digest != canonical_sha256(proposal):
        raise AdministrativeBoundaryError("review_proposal_changed")
    if request.context_digest != canonical_sha256(context):
        raise AdministrativeBoundaryError("review_context_changed")
    if request.catalog != catalog.binding:
        raise AdministrativeBoundaryError("review_catalog_changed")
    if len(proposal.assigned_terms) + len(proposal.candidate_terms) > 32:
        raise AdministrativeBoundaryError("review_term_budget")
    for term in (*proposal.assigned_terms, *proposal.candidate_terms):
        if catalog.lookup_term(term.term_id) != term:
            raise AdministrativeBoundaryError("review_term_changed")
    lookup = normalize_alias(proposal.raw_label) if proposal.raw_label is not None else None
    document = proposal.model_dump(mode="json")
    disposition = request.review.disposition
    if disposition == "accept" and request.assigned_term_ids is None:
        document["disposition"] = "accepted"
    elif disposition == "revise" and request.assigned_term_ids is not None:
        ids = request.assigned_term_ids
        if type(ids) is not tuple or not 1 <= len(ids) <= 32 or any(type(key) is not str for key in ids):
            raise AdministrativeBoundaryError("review_term_budget")
        if len(set(ids)) != len(ids):
            raise AdministrativeBoundaryError("review_term_duplicate")
        terms = tuple(catalog.lookup_term(key) for key in sorted(ids))
        if any(term is None for term in terms):
            raise AdministrativeBoundaryError("review_term_unresolved")
        document.update(
            disposition="revised", state="classified", candidate_terms=[],
            assigned_terms=[term.model_dump(mode="json") for term in terms],
            multiple=len(terms) > 1, ambiguity=None,
        )
    else:
        raise AdministrativeBoundaryError("review_disposition_requires_acceptance")
    document["review"] = request.review.model_dump(mode="json")
    accepted = InsuranceClassification.model_validate_json(json.dumps(document))
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
        raise AdministrativeBoundaryError("accepted_classification_changed")
    if decision.context_ref != context.context_id or decision.classification_refs != (accepted.classification.classification_id,):
        raise AdministrativeBoundaryError("review_decision_context_mismatch")
    if policy.document.jurisdiction != context.jurisdiction:
        raise AdministrativeBoundaryError("review_jurisdiction_mismatch")
    assessment = policy.evaluate(
        decision, {accepted.classification.classification_id: accepted.classification},
        dict(enrollments), service_day=service_day, evaluated_at=evaluated_at,
    )
    instant = datetime.fromisoformat(evaluated_at.removesuffix("Z") + "+00:00")
    review_at = datetime.fromisoformat(accepted.request.review.reviewed_at.removesuffix("Z") + "+00:00")
    if instant < review_at:
        raise AdministrativeBoundaryError("evaluation_precedes_review")
    interval = context.effective_interval
    for day in (service_day.isoformat(), instant.date().isoformat()):
        if day < interval.starts_on or (interval.ends_on is not None and day > interval.ends_on):
            raise AdministrativeBoundaryError("review_context_outside_effectivity")
    return assessment
