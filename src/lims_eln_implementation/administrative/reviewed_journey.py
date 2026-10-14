"""One finite authored example: proposal, review, policy, paired interpretation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from importlib.resources import files
import json
from typing import Callable

from lims_eln_contracts import (
    AdministrativeStudy, canonical_sha256, interpret_administrative_study,
    load_independent_multilabel_policy_example,
)
from lims_eln_contracts.resources import load_administrative_study_example
from lims_eln_contracts.administrative_study import StudyExecution, StudyRunPlan
from lims_eln_contracts.external_administrative import (
    AccountableReview, AdministrativeContext, AdministrativeDecision,
    CoverageEnrollment, InsuranceClassification,
)

from .acceptance import ClassificationReviewRequest, ReviewedClassification, accept_classification, evaluate_reviewed_classification
from .core import AdministrativeBoundaryError, CatalogSnapshot, InsuranceCatalog, PolicyAssessment, PreparedPolicy
from .journey import (
    OfflineReplayLedger, Proposal, ProposalPort, RunResult,
    _execution_identity, _observe, _require_execution_identity, _timestamp,
)


@dataclass(frozen=True)
class ReviewedCase:
    proposal: InsuranceClassification
    accepted: ReviewedClassification
    context: AdministrativeContext
    decision: AdministrativeDecision
    enrollments: tuple[CoverageEnrollment, ...]
    service_day: date


@dataclass(frozen=True)
class PreparedReviewedJourney:
    plan: AdministrativeStudy
    catalog: CatalogSnapshot
    policy: PreparedPolicy
    cases: tuple[ReviewedCase, ...]


def _reviewed_execution_identity() -> StudyExecution:
    """Bind the finite adapter to its four owned implementation modules.

    One bounded source pass costs O(S) time and space for S source bytes.
    Reading packaged resources preserves the same binding in an installed wheel.
    """
    root = files("lims_eln_implementation.administrative")
    sources = {
        name: "sha256:" + sha256(root.joinpath(name).read_bytes()).hexdigest()
        for name in ("acceptance.py", "core.py", "journey.py", "reviewed_journey.py")
    }
    return StudyExecution(
        provider_id="offline_fixture", model_id="reviewed-policy-output-fixture",
        adapter_version="1.0.0",
        prompt_digest=canonical_sha256({
            "scientific_text": "Shared authored scientific evidence.",
            "administrative_text": "Selected policy outcome term, or the assessment reason for an unassigned result.",
        }),
        configuration_digest=canonical_sha256(sources),
    )


def prepare_reviewed_journey() -> PreparedReviewedJourney:
    """Prepare the declared two-arm bundle once using indexed identities.

    Preparation is O(B + T + R), where B is the admitted bundle size, T its
    catalog terms and R policy predicates. Caller-defined bundle admission
    remains a separate intake; this entry loads the packaged synthetic bundle.
    """
    seed = load_administrative_study_example()
    bundle = load_independent_multilabel_policy_example()
    contexts = {item.context_id: item for item in bundle.administrative_contexts}
    decisions = {item.decision_id: item for item in bundle.administrative_decisions}
    classifications = {item.classification_id: item for item in bundle.insurance_classifications}
    enrollments = {item.enrollment_id: item for item in bundle.coverage_enrollments}
    policies = {item.policy_id: item for item in bundle.policy_rule_sets}
    decision = decisions["DECISION-ADMIN-BASELINE-001"]
    context = contexts[decision.context_ref]
    reviewed_fixture = classifications["CLASS-INSURANCE-MULTI-001"]
    policy = PreparedPolicy(policies[decision.policy_evaluation.policy_rule_set_ref])
    single = "insurance-category:commercial"
    multiple = (single, "insurance-category:supplemental")
    labels = ("Commercial", "Commercial + community support bridge")
    catalog = CatalogSnapshot(InsuranceCatalog.model_validate_json(json.dumps({
        "catalog_id": "reviewed-journey-catalog", "version": "1.0.0",
        "source": seed.specification.source.model_dump(mode="json"),
        "insurance_terms": [term.model_dump(mode="json") for term in reviewed_fixture.assigned_terms],
        "aliases": [{"label": labels[0], "term_ids": [single]}, {"label": labels[1], "term_ids": list(multiple)}],
        "diagnosis_codes": [],
    })))
    cases = []
    runs = []
    for index, run in enumerate(seed.runs[:2]):
        proposal = catalog.classify(labels[index], classification_id=decision.classification_refs[0], context_ref=context.context_id)
        review_document = reviewed_fixture.review.model_dump(mode="json")
        review_document.update(
            review_id=f"reviewed-journey-{run.run_id}",
            disposition="accept" if index == 0 else "revise",
            rationale="Authored review selects the named terms for this finite policy-mechanics example.",
        )
        review = AccountableReview.model_validate_json(json.dumps(review_document))
        request = ClassificationReviewRequest(
            canonical_sha256(proposal), canonical_sha256(context), catalog.binding,
            review, None if index == 0 else multiple,
        )
        accepted = accept_classification(proposal, context, catalog, request)
        selected_enrollments = tuple(enrollments[key] for key in decision.enrollment_refs)
        case = ReviewedCase(proposal, accepted, context, decision, selected_enrollments, date(2026, 10, 1))
        document = run.model_dump(mode="json")
        document["subject_id"] = context.subject.local_id
        document["episode_id"] = context.episode.local_id
        document["factors"] = [{"name": "insurance_description", "standing": "specified", "value": labels[index]}]
        document["administrative_input"] = json.dumps({
            "source_record": run.run_id, "raw_label": labels[index],
            "acceptance": accepted.lineage(), "accepted_classification": accepted.classification.model_dump(mode="json"),
            "decision_ref": decision.decision_id,
            "enrollments_digest": canonical_sha256([item.model_dump(mode="json") for item in selected_enrollments]),
            "service_day": case.service_day.isoformat(),
        }, sort_keys=True, separators=(",", ":"))
        runs.append(document)
        cases.append(case)
    document = seed.model_dump(mode="json")
    specification = document["specification"]
    specification.update(
        study_id="reviewed-classification-policy-journey",
        question="How does an explicitly reviewed insurance description change the declared policy route?",
        factor_names=["insurance_description"], controlled_factors=[],
        expected_execution=_reviewed_execution_identity().model_dump(mode="json"),
        catalog=catalog.binding.model_dump(mode="json"),
        policy={"artifact_id": policy.document.policy_id, "version": policy.document.policy_version, "digest": policy.document.policy_digest},
        stopping_rule="Complete the two authored arms once.",
    )
    specification["source"]["artifact"] = {
        "artifact_id": "reviewed-classification-fixture", "version": "1.0.0",
        "digest": canonical_sha256({"bundle": canonical_sha256(bundle), "seed": canonical_sha256(seed), "profile": "reviewed-classification-v1"}),
    }
    document.update(runs=runs, observations=[], expected_pairs=[])
    plan = AdministrativeStudy.model_validate_json(json.dumps(document))
    return PreparedReviewedJourney(plan, catalog, policy, tuple(cases))


class ReviewedOfflineProposal:
    """Return the actual policy result beside a constant authored science text."""

    def __init__(self, identity: StudyExecution):
        self.identity = identity

    def propose(self, run: StudyRunPlan, assessment: PolicyAssessment) -> Proposal:
        outcome = assessment.evaluation.outcome
        return Proposal("Shared authored scientific evidence.", outcome.term_id if outcome else assessment.reason)


def run_reviewed_journey(
    *, tenant_id: str = "synthetic-reviewed-administrative",
    adapter: ProposalPort | None = None, ledger: OfflineReplayLedger | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict[str, object]:
    """Execute the packaged pair with existing identity and replay boundaries."""
    if type(tenant_id) is not str or not tenant_id.startswith("synthetic-") or len(tenant_id) > 96:
        raise AdministrativeBoundaryError("synthetic_tenant_required")
    prepared = prepare_reviewed_journey()
    plan = prepared.plan
    spec_digest = canonical_sha256(plan.specification)
    adapter = adapter if adapter is not None else ReviewedOfflineProposal(plan.specification.expected_execution)
    ledger = ledger if ledger is not None else OfflineReplayLedger()
    identity = _execution_identity(adapter)
    results = []
    for order, (run, case) in enumerate(zip(plan.runs, prepared.cases, strict=True), 1):
        _require_execution_identity(adapter, identity)
        fingerprint = canonical_sha256({"specification": spec_digest, "run": run.model_dump(mode="json"), "execution": identity.model_dump(mode="json")})
        result = ledger.begin(tenant_id, run.run_id, fingerprint)
        if result is None:
            start = _timestamp(clock)
            _require_execution_identity(adapter, identity)
            assessment = evaluate_reviewed_classification(
                case.accepted, proposal=case.proposal, context=case.context,
                catalog=prepared.catalog, policy=prepared.policy, decision=case.decision,
                enrollments={item.enrollment_id: item for item in case.enrollments},
                service_day=case.service_day, evaluated_at=start,
            )
            observation = _observe(run, assessment, adapter, identity, spec_digest, order, start, clock)
            result = RunResult(observation, case.accepted.classification, assessment)
            ledger.retain(tenant_id, run.run_id, fingerprint, result)
        results.append(result)
    _require_execution_identity(adapter, identity)
    document = plan.model_dump(mode="json")
    document["observations"] = [result.observation.model_dump(mode="json") for result in results]
    study = AdministrativeStudy.model_validate_json(json.dumps(document))
    interpretation = interpret_administrative_study(study)
    return {
        "study": study.model_dump(mode="json"),
        "interpretation": interpretation.model_dump(mode="json"),
        "accepted_classifications": [result.classification.model_dump(mode="json") for result in results],
        "lineage": [case.accepted.lineage() for case in prepared.cases],
        "policy_evaluations": [result.assessment.evaluation.model_dump(mode="json") for result in results],
        "scope": "Two authored policy-routing arms; review records are fixtures. Population and payment conclusions require their own evidence.",
    }


if __name__ == "__main__":
    print(json.dumps(run_reviewed_journey(), indent=2, sort_keys=True))
