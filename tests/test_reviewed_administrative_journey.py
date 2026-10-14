"""Focused review-transition and actual policy-influence contracts."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from importlib.util import find_spec
from importlib.resources import files
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

if find_spec("lims_eln_contracts") is None:
    raise unittest.SkipTest("reviewed administrative journey requires the contracts profile")

from lims_eln_contracts import StudyInterpretation, canonical_sha256, load_independent_multilabel_policy_example
from lims_eln_contracts.external_administrative import InsuranceClassification
from lims_eln_contracts.resources import load_administrative_study_example
from lims_eln_implementation.administrative.acceptance import accept_classification, evaluate_reviewed_classification
from lims_eln_implementation.administrative.core import AdministrativeBoundaryError, CatalogSnapshot
from lims_eln_implementation.administrative.journey import OfflineProposal, OfflineReplayLedger
from lims_eln_implementation.administrative.reviewed_journey import _reviewed_execution_identity, prepare_reviewed_journey, run_reviewed_journey


INSTANT = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)


class ReviewedAdministrativeJourneyTests(unittest.TestCase):
    def test_run_identity_uses_the_reviewed_context(self):
        for run, case in zip(self.prepared.plan.runs, self.prepared.cases, strict=True):
            with self.subTest(run=run.run_id):
                self.assertEqual(run.subject_id, "SUBJECT-SYN-ADMIN-001")
                self.assertEqual(run.episode_id, "EPISODE-SYN-ADMIN-001")
                self.assertEqual((run.subject_id, run.episode_id), (case.context.subject.local_id, case.context.episode.local_id))
                self.assertEqual(case.accepted.request.context_digest, canonical_sha256(case.context))

    def test_execution_identity_binds_each_owned_source(self):
        original = _reviewed_execution_identity()
        self.assertEqual(original.model_id, "reviewed-policy-output-fixture")
        self.assertNotEqual(original, OfflineProposal(self.legacy_execution).identity)
        root = files("lims_eln_implementation.administrative")
        for changed in ("acceptance.py", "core.py", "journey.py", "reviewed_journey.py"):
            def selected(path):
                content = root.joinpath(path).read_bytes()
                return SimpleNamespace(read_bytes=lambda: content + (b"\n" if path == changed else b""))
            with self.subTest(source=changed), patch(
                "lims_eln_implementation.administrative.reviewed_journey.files",
                return_value=SimpleNamespace(joinpath=selected),
            ):
                self.assertNotEqual(_reviewed_execution_identity().configuration_digest, original.configuration_digest)

    def test_legacy_adapter_uses_its_own_execution_and_replay_identity(self):
        ledger = OfflineReplayLedger()
        accepted = run_reviewed_journey(ledger=ledger, clock=lambda: INSTANT)
        with self.assertRaisesRegex(AdministrativeBoundaryError, "replay_input_conflict"):
            run_reviewed_journey(adapter=OfflineProposal(self.legacy_execution), ledger=ledger, clock=lambda: INSTANT)
        self.assertEqual(run_reviewed_journey(ledger=ledger, clock=lambda: INSTANT), accepted)
        separate = run_reviewed_journey(adapter=OfflineProposal(self.legacy_execution), clock=lambda: INSTANT)
        self.assertEqual(separate["interpretation"]["eligible_pairs"], 0)
        self.assertEqual(separate["interpretation"]["pairs"][0]["execution"], "mismatched")
        self.assertNotEqual(separate["study"]["observations"], accepted["study"]["observations"])

    def setUp(self):
        self.prepared = prepare_reviewed_journey()
        self.case = self.prepared.cases[0]
        self.legacy_execution = load_administrative_study_example().specification.expected_execution

    def evaluate(self, case=None, **changes):
        case = self.case if case is None else case
        arguments = dict(
            proposal=case.proposal, context=case.context, catalog=self.prepared.catalog,
            policy=self.prepared.policy, decision=case.decision,
            enrollments={item.enrollment_id: item for item in case.enrollments},
            service_day=case.service_day, evaluated_at="2026-10-13T12:00:00Z",
        )
        arguments.update(changes)
        return evaluate_reviewed_classification(case.accepted, **arguments)

    def test_fresh_proposals_require_review_and_change_the_actual_policy_input(self):
        first, second = self.prepared.cases
        self.assertEqual(first.proposal.disposition, "proposed")
        self.assertEqual(second.proposal.state, "ambiguous")
        self.assertEqual(second.accepted.classification.disposition, "revised")
        self.assertTrue(second.accepted.classification.multiple)
        observed = [self.evaluate(case).evaluation for case in (first, second)]
        self.assertEqual([item.outcome.term_id for item in observed], ["policy-outcome:standard_processing", "policy-outcome:manual_review"])
        self.assertNotEqual(observed[0].input_digest, observed[1].input_digest)
        self.assertNotEqual(observed[0].evaluation_id, observed[1].evaluation_id)
        with self.assertRaises(AdministrativeBoundaryError):
            self.prepared.policy.bind_inputs(first.decision, {first.proposal.classification_id: first.proposal}, {item.enrollment_id: item for item in first.enrollments})

    def test_stale_material_preserves_the_previous_accepted_bytes(self):
        original = self.case.accepted.classification.model_dump_json()
        for field, value in (("raw_label", "Commercial "), ("raw_label_field", "source_insurance"), ("classification_id", "different-source-record")):
            with self.subTest(field=field):
                changed = self.case.proposal.model_copy(update={field: value})
                with self.assertRaisesRegex(AdministrativeBoundaryError, "review_proposal_changed"):
                    accept_classification(changed, self.case.context, self.prepared.catalog, self.case.accepted.request)
                self.assertEqual(self.case.accepted.classification.model_dump_json(), original)
        for field in ("subject", "episode", "jurisdiction"):
            target = getattr(self.case.context, field)
            key = "term_id" if field == "jurisdiction" else "local_id"
            context = self.case.context.model_copy(update={field: target.model_copy(update={key: "changed-identity"})})
            with self.subTest(context=field), self.assertRaisesRegex(AdministrativeBoundaryError, "review_context_changed"):
                self.evaluate(context=context)
        changed_catalog = CatalogSnapshot(self.prepared.catalog.document.model_copy(update={"version": "1.0.1"}))
        with self.assertRaisesRegex(AdministrativeBoundaryError, "review_catalog_changed"):
            self.evaluate(catalog=changed_catalog)

    def test_all_standings_roundtrip_without_inventing_assigned_terms(self):
        for state in ("unknown", "ambiguous", "abstained", "classified"):
            with self.subTest(state=state):
                source = self.prepared.cases[1].proposal if state == "ambiguous" else self.case.proposal
                document = source.model_dump(mode="json")
                document["state"] = state
                if state in {"unknown", "abstained"}:
                    document.update(assigned_terms=[], candidate_terms=[], multiple=False, ambiguity="Source evidence remains open.")
                proposal = InsuranceClassification.model_validate_json(json.dumps(document))
                request = replace(self.case.accepted.request, proposal_digest=canonical_sha256(proposal))
                accepted = accept_classification(proposal, self.case.context, self.prepared.catalog, request)
                recovered = InsuranceClassification.model_validate_json(accepted.classification.model_dump_json())
                self.assertEqual(recovered.state, state)
                self.assertEqual(recovered.assigned_terms, proposal.assigned_terms)
                self.assertEqual(recovered.candidate_terms, proposal.candidate_terms)
                assessment = self.evaluate(replace(self.case, proposal=proposal, accepted=accepted))
                self.assertEqual(assessment.evaluation.state, "assigned" if state in {"classified", "abstained"} else "abstained")

    def test_review_revision_resolves_exact_catalog_terms(self):
        case = self.prepared.cases[1]
        for ids, reason in (((), "review_term_budget"), (("absent-term",), "review_term_unresolved"), (("insurance-category:commercial",) * 2, "review_term_duplicate")):
            with self.subTest(ids=ids), self.assertRaisesRegex(AdministrativeBoundaryError, reason):
                accept_classification(case.proposal, case.context, self.prepared.catalog, replace(case.accepted.request, assigned_term_ids=ids))
        reordered = replace(case.accepted.request, assigned_term_ids=tuple(reversed(case.accepted.request.assigned_term_ids)))
        self.assertEqual(accept_classification(case.proposal, case.context, self.prepared.catalog, reordered).classification, case.accepted.classification)

    def test_changed_accepted_snapshot_is_rejected(self):
        changed = self.case.accepted.classification.model_copy(update={"raw_label": "Different"})
        with self.assertRaisesRegex(AdministrativeBoundaryError, "accepted_classification_changed"):
            self.evaluate(replace(self.case, accepted=replace(self.case.accepted, classification=changed)))

    def test_service_evaluation_and_review_times_remain_distinct(self):
        self.assertEqual(self.evaluate(service_day=date(2026, 12, 31)).reason, "assigned")
        for changes in (
            {"service_day": date(2027, 1, 1)},
            {"evaluated_at": "2027-01-01T00:00:00Z"},
            {"evaluated_at": "2026-10-01T13:59:59Z"},
        ):
            with self.subTest(changes=changes), self.assertRaises(AdministrativeBoundaryError):
                self.evaluate(**changes)
        later = self.evaluate(evaluated_at="2026-10-14T12:00:00Z").evaluation
        earlier = self.evaluate().evaluation
        self.assertEqual(later.evaluation_id, earlier.evaluation_id)
        self.assertNotEqual(later.evaluated_at, earlier.evaluated_at)

    def test_offline_pair_exports_usable_interpretation_and_exact_replay(self):
        ledger = OfflineReplayLedger()
        result = run_reviewed_journey(ledger=ledger, clock=lambda: INSTANT)
        replay = run_reviewed_journey(ledger=ledger, clock=lambda: self.fail("Replay retains original occurrence times"))
        self.assertEqual(replay, result)
        interpretation = StudyInterpretation.model_validate_json(json.dumps(result["interpretation"]))
        self.assertEqual((interpretation.planned_pairs, interpretation.eligible_pairs, interpretation.usable_runs), (1, 1, 2))
        self.assertEqual(interpretation.expected_pairs_available, 0)
        observations = result["study"]["observations"]
        self.assertEqual(observations[0]["scientific_output"], observations[1]["scientific_output"])
        self.assertEqual([item["administrative_output"]["text"] for item in observations], ["policy-outcome:standard_processing", "policy-outcome:manual_review"])

    def test_reordered_bundle_preserves_results(self):
        source = load_independent_multilabel_policy_example()
        changed = source.model_copy(update={name: tuple(reversed(getattr(source, name))) for name in ("administrative_contexts", "insurance_classifications", "coverage_enrollments", "policy_rule_sets", "administrative_decisions")})
        with patch("lims_eln_implementation.administrative.reviewed_journey.load_independent_multilabel_policy_example", return_value=changed):
            reordered = run_reviewed_journey(clock=lambda: INSTANT)
        original = run_reviewed_journey(clock=lambda: INSTANT)
        self.assertEqual(reordered["policy_evaluations"], original["policy_evaluations"])
        self.assertEqual(reordered["accepted_classifications"], original["accepted_classifications"])
        self.assertNotEqual(canonical_sha256(reordered["study"]["specification"]), canonical_sha256(original["study"]["specification"]))


if __name__ == "__main__":
    unittest.main()
