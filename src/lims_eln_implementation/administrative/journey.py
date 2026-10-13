"""A finite synthetic journey with input-bound, process-local replay.

Preparation indexes the bounded fixture once. Run work is linear in serialized
input/output plus prepared policy evaluation. The ledger owns O(R + output)
retained space and expected O(1) key lookup; hash worst cases remain separate.
"""

from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
from typing import Callable, Protocol

from pydantic import ValidationError
from lims_eln_contracts import canonical_json_bytes, canonical_sha256, compare_administrative_study, load_independent_multilabel_policy_example
from lims_eln_contracts.administrative_study import AdministrativeStudy, StudyBinding, StudyExecution, StudyOutput, StudyRunObservation, StudyRunPlan, SyntheticStudySource, admit_administrative_study
from lims_eln_contracts.external_administrative import AdministrativeDecision, CoverageEnrollment, IdentifiedTerm, InsuranceClassification
from lims_eln_contracts.resources import load_administrative_study_example

from .core import AdministrativeBoundaryError, CatalogAlias, CatalogSnapshot, InsuranceCatalog, PolicyAssessment, PreparedPolicy, ReferenceCode


@dataclass(frozen=True, slots=True)
class Proposal:
    scientific_text: str
    administrative_text: str


class ProposalAbstained(Exception):
    """The adapter explicitly elects to abstain for this input."""


class ProposalPort(Protocol):
    @property
    def identity(self) -> StudyExecution: ...

    def propose(self, run: StudyRunPlan, assessment: PolicyAssessment) -> Proposal: ...


@dataclass(frozen=True, slots=True)
class OfflineProposal:
    """An authored control, deliberately sensitive in one declared scenario."""

    identity: StudyExecution

    def propose(self, run: StudyRunPlan, assessment: PolicyAssessment) -> Proposal:
        science = "Authored evidence summary."
        if run.scenario_id == "scenario-0" and run.arm == "b":
            science = "Deliberately changed evidence summary."
        return Proposal(science, "Reviewed fixture policy: " + assessment.reason)


@dataclass(frozen=True, slots=True)
class RunContext:
    decision: AdministrativeDecision
    classifications: tuple[InsuranceClassification, ...]
    enrollments: tuple[CoverageEnrollment, ...]
    service_day: date
    proposal: InsuranceClassification


@dataclass(frozen=True, slots=True)
class RunResult:
    observation: StudyRunObservation
    classification: InsuranceClassification
    assessment: PolicyAssessment


class OfflineReplayLedger:
    """Bounded, single-executor storage for complete results and unsettled attempts.

    Admission reserves capacity before adapter execution. An interrupted reservation
    holds that run for explicit recovery; completed and failed results replay intact.
    Durable restart and concurrent ownership belong to a receiving store.
    """

    def __init__(self, capacity: int = 512):
        if type(capacity) is not int or not 1 <= capacity <= 4096:
            raise AdministrativeBoundaryError("ledger_capacity_boundary")
        self._capacity = capacity
        self._records: dict[tuple[str, str], tuple[str, RunResult | None]] = {}

    def begin(self, tenant_id: str, run_id: str, fingerprint: str) -> RunResult | None:
        record = self._records.get((tenant_id, run_id))
        if record is not None:
            if record[0] != fingerprint:
                raise AdministrativeBoundaryError("replay_input_conflict")
            if record[1] is None:
                raise AdministrativeBoundaryError("replay_attempt_unsettled")
            return record[1]
        if len(self._records) >= self._capacity:
            raise AdministrativeBoundaryError("ledger_capacity_reached")
        self._records[(tenant_id, run_id)] = (fingerprint, None)
        return None

    def retain(self, tenant_id: str, run_id: str, fingerprint: str, result: RunResult) -> None:
        prior = self._records.get((tenant_id, run_id))
        if prior is None or prior[0] != fingerprint or result.observation.run_id != run_id:
            raise AdministrativeBoundaryError("replay_reservation_mismatch")
        if prior[1] is not None and prior[1] != result:
            raise AdministrativeBoundaryError("replay_observation_conflict")
        self._records[(tenant_id, run_id)] = (fingerprint, result)


def _timestamp(clock: Callable[[], datetime]) -> str:
    value = clock()
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise AdministrativeBoundaryError("clock_timezone_required")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _prepare() -> tuple[AdministrativeStudy, tuple[RunContext, ...], PreparedPolicy]:
    """Bind each run to declared source records, service date, and code metadata.

    Within each pair only diagnosis reportability changes. The two scenarios use
    different reviewed fixture contexts; fresh classification remains a proposal.
    """
    seed = load_administrative_study_example()
    bundle = load_independent_multilabel_policy_example()
    snapshot = CatalogSnapshot(example_catalog())
    decisions = {item.decision_id: item for item in bundle.administrative_decisions}
    choices = {"scenario-0": "DECISION-ADMIN-BASELINE-001", "scenario-1": "DECISION-ADMIN-COUNTERFACTUAL-001"}
    policies = {item.policy_id: item for item in bundle.policy_rule_sets}
    decision = decisions[choices["scenario-0"]]
    policy = policies[decision.policy_evaluation.policy_rule_set_ref]
    prepared = PreparedPolicy(policy)
    classifications = {item.classification_id: item for item in bundle.insurance_classifications}
    enrollments = {item.enrollment_id: item for item in bundle.coverage_enrollments}
    document = seed.model_dump(mode="json", by_alias=True)
    document["observations"] = []
    document["specification"]["max_attempts_per_run"] = 1
    document["specification"]["catalog"] = snapshot.binding.model_dump(mode="json")
    document["specification"]["policy"] = {"artifact_id": policy.policy_id, "version": policy.policy_version, "digest": policy.policy_digest}
    document["specification"]["source"]["artifact"] = {"artifact_id": "enterprise-offline-fixture-inputs", "version": "1.0.0", "digest": canonical_sha256((seed, bundle))}
    contexts = []
    for run in document["runs"]:
        decision = decisions[choices[run["scenario_id"]]]
        selected = tuple(classifications[key] for key in decision.classification_refs)
        enrolled = tuple(enrollments[key] for key in decision.enrollment_refs)
        material = prepared.bind_inputs(decision, classifications, enrollments)
        day = date.fromisoformat(policy.effective_interval.starts_on)
        raw_label = selected[0].raw_label
        reportability = next(factor for factor in run["factors"] if factor["name"] == "reportability")
        code_keys = {"category": "SYN-1", "reportable": "SYN-1-A"}
        if reportability["standing"] != "specified" or reportability["value"] not in code_keys:
            raise AdministrativeBoundaryError("fixture_reportability_boundary")
        code = snapshot.lookup_code("synthetic-diagnosis-codes", "1.0.0", code_keys[reportability["value"]])
        classified = snapshot.classify(raw_label, classification_id="classification-" + run["run_id"], context_ref=decision.context_ref)
        binding = {"insurance_label": raw_label, "decision_ref": decision.decision_id, "context_ref": decision.context_ref, "decision_digest": canonical_sha256(decision), "classification_digest": canonical_sha256(selected), "enrollment_digest": canonical_sha256(enrolled), "reviewed_policy_input_digest": material.calculated_digest(), "service_day": day.isoformat(), "diagnosis_code": code}
        run["administrative_input"] = canonical_json_bytes(binding).decode("utf-8")
        contexts.append(RunContext(decision, selected, enrolled, day, classified))
    return admit_administrative_study(json.dumps(document).encode()), tuple(contexts), prepared


def _output(text: str) -> StudyOutput:
    if type(text) is not str or not 1 <= len(text) <= 16384 or not text.strip():
        raise ValueError("bounded_output_text_required")
    return StudyOutput(text=text, digest=canonical_sha256(text), completeness="complete")


def _observe(run: StudyRunPlan, assessment: PolicyAssessment, adapter: ProposalPort, identity: StudyExecution, spec_digest: str, order: int, start: str, clock: Callable[[], datetime]) -> StudyRunObservation:
    """Retain one attempt's fixed-code outcome, including adapter exceptions."""
    scientific = administrative = None
    status, reason = "completed", None
    try:
        result = adapter.propose(run, assessment)
    except TimeoutError:
        status, reason = "timeout", "adapter_deadline"
    except CancelledError:
        status, reason = "cancelled", "adapter_cancelled"
    except ProposalAbstained:
        status, reason = "abstained", "adapter_abstained"
    except Exception:
        status, reason = "failed", "adapter_failure"
    else:
        try:
            if type(result) is not Proposal:
                raise ValueError("proposal_type_required")
            scientific, administrative = _output(result.scientific_text), _output(result.administrative_text)
        except (ValueError, TypeError, UnicodeError, ValidationError):
            status, reason = "invalid_response", "adapter_output_boundary"
            scientific = administrative = None
    finish = _timestamp(clock)
    return StudyRunObservation(observation_id="observation-" + run.run_id, run_id=run.run_id, attempt=1, specification_digest=spec_digest, input_digest=canonical_sha256(run), status=status, reason_code=reason, execution=identity, execution_order=order, started_at=start, finished_at=finish, scientific_output=scientific, administrative_output=administrative)


def run_offline_journey(*, tenant_id: str = "synthetic-tenant", ledger: OfflineReplayLedger | None = None, proposal: ProposalPort | None = None, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> dict:
    """Execute packaged fixtures with one attempt per run and no automatic retry.

    Local adapters may be injected for acceptance fixtures. The CLI selects the
    offline adapter. Receiving teams own authorization for any successor adapter.
    """
    if type(tenant_id) is not str or not tenant_id.startswith("synthetic-") or len(tenant_id) > 96:
        raise AdministrativeBoundaryError("offline_tenant_boundary")
    plan, contexts, prepared = _prepare()
    adapter = proposal if proposal is not None else OfflineProposal(plan.specification.expected_execution)
    identity = StudyExecution.model_validate_json(adapter.identity.model_dump_json(), strict=True)
    store = ledger if ledger is not None else OfflineReplayLedger()
    spec_digest = canonical_sha256(plan.specification)
    results = []
    for index, (run, context) in enumerate(zip(plan.runs, contexts, strict=True)):
        fingerprint = canonical_sha256((spec_digest, canonical_sha256(run), identity))
        result = store.begin(tenant_id, run.run_id, fingerprint)
        if result is None:
            start = _timestamp(clock)
            assessment = prepared.evaluate(context.decision, {item.classification_id: item for item in context.classifications}, {item.enrollment_id: item for item in context.enrollments}, service_day=context.service_day, evaluated_at=context.decision.policy_evaluation.evaluated_at)
            observation = _observe(run, assessment, adapter, identity, spec_digest, index, start, clock)
            result = RunResult(observation, context.proposal, assessment)
            store.retain(tenant_id, run.run_id, fingerprint, result)
        results.append(result)
    document = plan.model_dump(mode="json", by_alias=True)
    document["observations"] = [result.observation.model_dump(mode="json") for result in results]
    study = admit_administrative_study(json.dumps(document).encode())
    return {"study": study.model_dump(mode="json", by_alias=True), "comparison": compare_administrative_study(study).model_dump(mode="json", by_alias=True), "classification_proposals": [result.classification.model_dump(mode="json") for result in results], "reviewed_policy_evaluations": [{"reason": result.assessment.reason, "evaluation": result.assessment.evaluation.model_dump(mode="json")} for result in results], "scope": "packaged synthetic fixture; process-local replay; output identity comparison"}


def example_catalog() -> InsuranceCatalog:
    """Authored source data; separate vocabularies keep code status and plans distinct."""
    terms = tuple(IdentifiedTerm(term_id=key, label=label, vocabulary_id="synthetic-insurance-kinds", vocabulary_version="1.0.0") for key, label in (("employer-plan", "Employer plan"), ("individual-plan", "Individual plan")))
    aliases = (CatalogAlias(label="commercial", term_ids=("employer-plan",)), CatalogAlias(label="private", term_ids=("employer-plan", "individual-plan")))
    codes = (ReferenceCode(system="synthetic-diagnosis-codes", release="1.0.0", code="SYN-1", reportability="category", description="Authored category for equivalent supplied evidence."), ReferenceCode(system="synthetic-diagnosis-codes", release="1.0.0", code="SYN-1-A", reportability="reportable", description="Authored reportable code for equivalent supplied evidence."))
    digest = canonical_sha256((terms, aliases, codes))
    return InsuranceCatalog(catalog_id="synthetic-insurance-catalog", version="1.0.0", source=SyntheticStudySource(data_class="synthetic", construction="authored_fixture", artifact=StudyBinding(artifact_id="enterprise-authored-catalog", version="1.0.0", digest=digest), review_ref="enterprise-issues-36-37", purpose="Exercise exact lookup, ambiguity and independent code reportability."), insurance_terms=terms, aliases=aliases, diagnosis_codes=codes)
