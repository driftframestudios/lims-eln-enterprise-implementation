"""Offline behavior contracts for policy ownership and complete replay."""

from concurrent.futures import CancelledError
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta, timezone
from importlib.util import find_spec
import json
import unittest
from unittest.mock import patch

if find_spec("lims_eln_contracts") is None:
    raise unittest.SkipTest("administrative checks require the contracts extra")

from lims_eln_contracts import canonical_sha256, load_independent_multilabel_policy_example
from lims_eln_contracts.external_administrative import PolicyRuleSet
from lims_eln_contracts.resources import load_administrative_study_example
from lims_eln_implementation.administrative.core import AdministrativeBoundaryError, CatalogSnapshot, PreparedPolicy
from lims_eln_implementation.administrative.journey import (
    OfflineProposal, OfflineReplayLedger, Proposal, ProposalAbstained,
    example_catalog, run_offline_journey,
)


NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)


class CountingAdapter:
    def __init__(self, failure=None):
        self.identity = load_administrative_study_example().specification.expected_execution
        self.failure = failure
        self.calls = []

    def propose(self, run, assessment):
        self.calls.append(run.run_id)
        if len(self.calls) == 2 and self.failure is not None:
            if isinstance(self.failure, BaseException):
                raise self.failure
            return self.failure
        return OfflineProposal(self.identity).propose(run, assessment)


class IdentityChangingAdapter(CountingAdapter):
    def __init__(self, failure=None, *, change_after=1):
        super().__init__(failure)
        self.change_after = change_after

    def propose(self, run, assessment):
        try:
            return super().propose(run, assessment)
        finally:
            if len(self.calls) == self.change_after:
                self.identity = self.identity.model_copy(update={"model_id": "changed-local-model"})


class PreparedPolicyTests(unittest.TestCase):
    def setUp(self):
        self.bundle = load_independent_multilabel_policy_example()
        self.policy = self.bundle.policy_rule_sets[0]
        self.prepared = PreparedPolicy(self.policy)
        self.classifications = {item.classification_id: item for item in self.bundle.insurance_classifications}
        self.enrollments = {item.enrollment_id: item for item in self.bundle.coverage_enrollments}
        self.day = date.fromisoformat(self.policy.effective_interval.starts_on)

    def evaluate(self, decision, **changes):
        return self.prepared.evaluate(
            decision, changes.get("classifications", self.classifications),
            changes.get("enrollments", self.enrollments),
            service_day=changes.get("service_day", self.day), evaluated_at="2026-10-13T00:00:00Z",
        )

    def test_reviewed_fixture_cases_retain_independent_expected_outcomes(self):
        for decision, reason, state, outcome in zip(
            self.bundle.administrative_decisions,
            ("assigned", "assigned", "missing_input"),
            ("assigned", "assigned", "abstained"),
            ("policy-outcome:manual_review", "policy-outcome:evidence_request", None), strict=True,
        ):
            with self.subTest(decision=decision.decision_id):
                observed = self.evaluate(decision)
                self.assertEqual(observed.reason, reason)
                self.assertEqual(observed.evaluation.state.value, state)
                self.assertEqual(observed.evaluation.outcome.term_id if observed.evaluation.outcome else None, outcome)
                self.assertEqual(observed.evaluation.input_digest, decision.policy_evaluation.input_digest)
                self.assertEqual(observed.evaluation.policy_digest, self.policy.policy_digest)

    def test_source_interval_has_explicit_inclusive_endpoints(self):
        decision = self.bundle.administrative_decisions[0]
        self.assertEqual(self.evaluate(decision).reason, "assigned")
        with self.assertRaisesRegex(AdministrativeBoundaryError, "service_date_outside_policy_interval"):
            self.evaluate(decision, service_day=self.day - timedelta(days=1))
        if self.policy.effective_interval.ends_on:
            end = date.fromisoformat(self.policy.effective_interval.ends_on)
            self.assertEqual(self.evaluate(decision, service_day=end).reason, "assigned")
            with self.assertRaisesRegex(AdministrativeBoundaryError, "service_date_outside_policy_interval"):
                self.evaluate(decision, service_day=end + timedelta(days=1))

    def test_evaluation_time_uses_the_program_effectivity_boundary(self):
        for timestamp in ("2025-01-01T00:00:00Z", "2027-01-01T00:00:00Z"):
            with self.subTest(timestamp=timestamp), self.assertRaisesRegex(AdministrativeBoundaryError, "evaluation_time_outside_policy_interval"):
                self.prepared.evaluate(self.bundle.administrative_decisions[0], self.classifications, self.enrollments, service_day=self.day, evaluated_at=timestamp)

    def successor_policy(self, document):
        document["policy_digest"] = canonical_sha256({key: value for key, value in document.items() if key != "policy_digest"})
        policy = PolicyRuleSet.model_validate_json(json.dumps(document))
        original = self.bundle.administrative_decisions[0]
        decision = original.model_copy(update={"policy_evaluation": original.policy_evaluation.model_copy(update={"policy_digest": policy.policy_digest})})
        return PreparedPolicy(policy).evaluate(decision, self.classifications, self.enrollments, service_day=self.day, evaluated_at="2026-10-13T00:00:00Z")

    def test_equal_outcome_overlaps_retain_declared_conflict_behavior(self):
        for behavior, expected_state in (("require_review", "review_required"), ("abstain", "abstained"), ("highest_precedence", "assigned")):
            document = self.policy.model_dump(mode="json")
            document["conflict_behavior"] = behavior
            outcome = next(rule["outcome"] for rule in document["rules"] if rule["rule_id"] == "RULE-MULTILABEL-001")
            for rule in document["rules"]:
                if rule["rule_id"] == "RULE-COMMERCIAL-ACTIVE-FALLBACK-001":
                    rule["outcome"] = outcome
            with self.subTest(behavior=behavior):
                observed = self.successor_policy(document).evaluation
                self.assertEqual(observed.state.value, expected_state)
                self.assertEqual(observed.conflicting_rule_refs, ("RULE-MULTILABEL-001", "RULE-COMMERCIAL-ACTIVE-FALLBACK-001"))

    def test_declared_match_order_is_independent_of_winner_precedence(self):
        document = self.policy.model_dump(mode="json")
        document["rules"].reverse()
        observed = self.successor_policy(document).evaluation
        self.assertEqual(observed.matched_rule_refs, ("RULE-COMMERCIAL-ACTIVE-FALLBACK-001", "RULE-MULTILABEL-001"))
        self.assertEqual(observed.conflicting_rule_refs, observed.matched_rule_refs)
        self.assertEqual(observed.selected_rule_ref, "RULE-MULTILABEL-001")

    def test_prepared_document_and_rules_remain_one_immutable_snapshot(self):
        for name, replacement in (("document", self.policy), ("_rules", ())):
            with self.subTest(name=name), self.assertRaises(FrozenInstanceError):
                setattr(self.prepared, name, replacement)
        snapshot = CatalogSnapshot(example_catalog())
        with self.assertRaises(FrozenInstanceError):
            snapshot.document = example_catalog()
        with self.assertRaises(TypeError):
            snapshot._aliases["new"] = ("employer-plan",)

    def test_foreign_context_and_displaced_record_identity_are_rejected(self):
        decision = self.bundle.administrative_decisions[0]
        for collection, key, field, value in (
            ("classifications", decision.classification_refs[0], "context_ref", "foreign-context"),
            ("classifications", decision.classification_refs[0], "classification_id", "foreign-classification"),
            ("enrollments", decision.enrollment_refs[0], "context_ref", "foreign-context"),
            ("enrollments", decision.enrollment_refs[0], "enrollment_id", "foreign-enrollment"),
        ):
            source = dict(getattr(self, collection))
            document = source[key].model_dump(mode="json")
            document[field] = value
            source[key] = type(source[key]).model_validate_json(json.dumps(document))
            with self.subTest(collection=collection, field=field), self.assertRaisesRegex(AdministrativeBoundaryError, "policy_input_identity_mismatch"):
                self.evaluate(decision, **{collection: source})

    def test_policy_coordinates_and_source_presence_are_explicit(self):
        decision = self.bundle.administrative_decisions[0]
        evaluation = decision.policy_evaluation.model_copy(update={"policy_rule_set_ref": "another-policy"})
        foreign = decision.model_copy(update={"policy_evaluation": evaluation})
        with self.assertRaisesRegex(AdministrativeBoundaryError, "policy_coordinate_mismatch"):
            self.evaluate(foreign)
        with self.assertRaisesRegex(AdministrativeBoundaryError, "reviewed_policy_inputs_required"):
            self.evaluate(decision, classifications={})


class OfflineJourneyTests(unittest.TestCase):
    def run_journey(self, **options):
        return run_offline_journey(clock=lambda: NOW, **options)

    def test_complete_journey_binds_each_run_and_keeps_both_findings(self):
        result = self.run_journey()
        report = result["comparison"]
        self.assertEqual((report["planned"], report["attempted"], report["completed"]), (4, 4, 4))
        self.assertEqual([item["scientific_changed"] for item in report["comparisons"]], [True, False])
        self.assertEqual([item["administrative_changed"] for item in report["comparisons"]], [False, False])
        digests = []
        for run, classified, policy in zip(result["study"]["runs"], result["classification_proposals"], result["reviewed_policy_evaluations"], strict=True):
            context = json.loads(run["administrative_input"])
            self.assertEqual(classified["raw_label"], context["insurance_label"])
            self.assertEqual(classified["context_ref"], context["context_ref"])
            self.assertEqual(policy["evaluation"]["input_digest"], context["reviewed_policy_input_digest"])
            self.assertEqual(policy["evaluation"]["input_material"]["context_ref"], context["context_ref"])
            self.assertEqual(context["diagnosis_code"]["reportability"], "category" if run["arm"] == "a" else "reportable")
            digests.append(context["reviewed_policy_input_digest"])
        self.assertEqual(digests[0], digests[1])
        self.assertEqual(digests[2], digests[3])
        self.assertNotEqual(digests[0], digests[2])

    def test_replay_retains_the_complete_document_without_proposal_calls(self):
        ledger, adapter = OfflineReplayLedger(), CountingAdapter()
        first = self.run_journey(ledger=ledger, proposal=adapter)
        second = self.run_journey(ledger=ledger, proposal=adapter)
        self.assertEqual(first, second)
        self.assertEqual(len(adapter.calls), 4)
        self.assertEqual(len(second["classification_proposals"]), 4)
        self.assertEqual(len(second["reviewed_policy_evaluations"]), 4)
        self.assertTrue(all(
            observation["execution"] == adapter.identity.model_dump(mode="json")
            for observation in second["study"]["observations"]
        ))

    def test_identity_drift_during_proposal_holds_successful_output_for_recovery(self):
        ledger, adapter = OfflineReplayLedger(), IdentityChangingAdapter()
        with self.assertRaisesRegex(AdministrativeBoundaryError, "^proposal_identity_changed$"):
            self.run_journey(ledger=ledger, proposal=adapter)
        self.assertEqual(len(adapter.calls), 1)
        stable = CountingAdapter()
        with self.assertRaisesRegex(AdministrativeBoundaryError, "^replay_attempt_unsettled$"):
            self.run_journey(ledger=ledger, proposal=stable)
        self.assertEqual(stable.calls, [])

    def test_identity_drift_on_exception_keeps_the_attempt_unsettled(self):
        for failure in (
            TimeoutError("private identity failure"),
            CancelledError("private identity failure"),
            ProposalAbstained("private identity failure"),
            RuntimeError("private identity failure"),
        ):
            with self.subTest(failure=type(failure).__name__):
                ledger = OfflineReplayLedger()
                adapter = IdentityChangingAdapter(failure, change_after=2)
                with self.assertRaisesRegex(AdministrativeBoundaryError, "^proposal_identity_changed$"):
                    self.run_journey(ledger=ledger, proposal=adapter)
                self.assertEqual(len(adapter.calls), 2)
                stable = CountingAdapter()
                with self.assertRaisesRegex(AdministrativeBoundaryError, "^replay_attempt_unsettled$"):
                    self.run_journey(ledger=ledger, proposal=stable)
                self.assertEqual(stable.calls, [])

    def test_identity_drift_between_calls_stops_the_next_proposal(self):
        ledger, adapter = OfflineReplayLedger(), CountingAdapter()
        ticks = 0

        def clock():
            nonlocal ticks
            ticks += 1
            if ticks == 2:
                adapter.identity = adapter.identity.model_copy(update={"model_id": "changed-local-model"})
            return NOW

        with self.assertRaisesRegex(AdministrativeBoundaryError, "^proposal_identity_changed$"):
            run_offline_journey(clock=clock, ledger=ledger, proposal=adapter)
        self.assertEqual(len(adapter.calls), 1)
        stable = CountingAdapter()
        with self.assertRaisesRegex(AdministrativeBoundaryError, "^replay_attempt_unsettled$"):
            self.run_journey(ledger=ledger, proposal=stable)
        self.assertEqual(stable.calls, [])

    def test_invalid_initial_identity_has_a_bounded_error_before_execution(self):
        for identity in (None, CountingAdapter().identity.model_copy(update={"model_id": None})):
            with self.subTest(identity=type(identity).__name__):
                adapter = CountingAdapter()
                adapter.identity = identity
                with self.assertRaisesRegex(AdministrativeBoundaryError, "^proposal_identity_unavailable$"):
                    self.run_journey(proposal=adapter)
                self.assertEqual(adapter.calls, [])

    def test_failure_variants_replay_the_original_attempt(self):
        for failure, status in (
            (TimeoutError("private failure detail"), "timeout"),
            (CancelledError("private failure detail"), "cancelled"),
            (ProposalAbstained("private failure detail"), "abstained"),
            (RuntimeError("private failure detail"), "failed"),
            ({"unexpected": "shape"}, "invalid_response"),
            (Proposal("x" * 16385, "valid"), "invalid_response"),
        ):
            with self.subTest(status=status):
                ledger, adapter = OfflineReplayLedger(), CountingAdapter(failure)
                first = self.run_journey(ledger=ledger, proposal=adapter)
                second = self.run_journey(ledger=ledger, proposal=adapter)
                self.assertEqual(first, second)
                self.assertEqual(len(adapter.calls), 4)
                observation = first["study"]["observations"][1]
                self.assertEqual((observation["status"], observation["attempt"]), (status, 1))
                self.assertEqual(first["comparison"]["completed"], 3)
                self.assertEqual(first["comparison"]["comparisons"][0]["standing"], "incomplete")
                self.assertNotIn("private failure detail", json.dumps(first))

    def test_changed_adapter_configuration_holds_existing_run_identity(self):
        ledger, adapter = OfflineReplayLedger(), CountingAdapter()
        self.run_journey(ledger=ledger, proposal=adapter)
        adapter.identity = adapter.identity.model_copy(update={"configuration_digest": canonical_sha256("new configuration")})
        with self.assertRaisesRegex(AdministrativeBoundaryError, "replay_input_conflict"):
            self.run_journey(ledger=ledger, proposal=adapter)
        self.assertEqual(len(adapter.calls), 4)

    def test_changed_reviewed_source_holds_existing_run_identity(self):
        ledger, adapter = OfflineReplayLedger(), CountingAdapter()
        self.run_journey(ledger=ledger, proposal=adapter)
        bundle = load_independent_multilabel_policy_example()
        first = bundle.insurance_classifications[0]
        changed = first.model_copy(update={"raw_label": "Changed authored label"})
        successor = bundle.model_copy(update={"insurance_classifications": (changed,) + bundle.insurance_classifications[1:]})
        with patch("lims_eln_implementation.administrative.journey.load_independent_multilabel_policy_example", return_value=successor):
            with self.assertRaisesRegex(AdministrativeBoundaryError, "replay_input_conflict"):
                self.run_journey(ledger=ledger, proposal=adapter)
        self.assertEqual(len(adapter.calls), 4)

    def test_capacity_is_reserved_before_the_next_adapter_call(self):
        ledger, adapter = OfflineReplayLedger(capacity=1), CountingAdapter()
        for _ in range(2):
            with self.assertRaisesRegex(AdministrativeBoundaryError, "ledger_capacity_reached"):
                self.run_journey(ledger=ledger, proposal=adapter)
        self.assertEqual(len(adapter.calls), 1)

    def test_interrupted_attempt_holds_replay_for_explicit_recovery(self):
        ledger, adapter = OfflineReplayLedger(), CountingAdapter(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.run_journey(ledger=ledger, proposal=adapter)
        with self.assertRaisesRegex(AdministrativeBoundaryError, "replay_attempt_unsettled"):
            self.run_journey(ledger=ledger, proposal=adapter)
        self.assertEqual(len(adapter.calls), 2)

    def test_tenant_scopes_have_separate_results(self):
        ledger, adapter = OfflineReplayLedger(), CountingAdapter()
        first = self.run_journey(tenant_id="synthetic-one", ledger=ledger, proposal=adapter)
        second = self.run_journey(tenant_id="synthetic-two", ledger=ledger, proposal=adapter)
        self.assertEqual(first, second)
        self.assertEqual(len(adapter.calls), 8)

    def test_historical_policy_replay_keeps_current_execution_time_distinct(self):
        future = datetime(2027, 1, 1, tzinfo=timezone.utc)
        result = run_offline_journey(clock=lambda: future)
        self.assertTrue(all(item["started_at"].startswith("2027-01-01") for item in result["study"]["observations"]))
        self.assertTrue(all(item["evaluation"]["evaluated_at"].startswith("2026-10-01") for item in result["reviewed_policy_evaluations"]))

    def test_code_selection_follows_the_declared_factor(self):
        seed = load_administrative_study_example()
        document = seed.model_dump(mode="json", by_alias=True)
        factor = next(item for item in document["runs"][1]["factors"] if item["name"] == "reportability")
        factor["value"] = "category"
        plans = {item["run_id"]: item for item in document["runs"]}
        for observation in document["observations"]:
            observation["input_digest"] = canonical_sha256(plans[observation["run_id"]])
        changed = type(seed).model_validate_json(json.dumps(document))
        with patch("lims_eln_implementation.administrative.journey.load_administrative_study_example", return_value=changed):
            result = self.run_journey()
        context = json.loads(result["study"]["runs"][1]["administrative_input"])
        self.assertEqual((context["diagnosis_code"]["code"], context["diagnosis_code"]["reportability"]), ("SYN-1", "category"))


if __name__ == "__main__":
    unittest.main()
