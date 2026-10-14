"""Recovery categories retain fixed feedback and accepted-state ownership."""

from dataclasses import replace
from importlib.util import find_spec
import unittest
from unittest.mock import patch

if find_spec("lims_eln_contracts") is None:
    raise unittest.SkipTest("Program contracts are available through the contracts profile")

from pydantic import ValidationError
from lims_eln_contracts import canonical_sha256
from lims_eln_contracts.external_administrative import InsuranceClassification
from lims_eln_implementation.administrative import acceptance
from lims_eln_implementation.administrative.core import AdministrativeBoundaryError
from lims_eln_implementation.administrative.reviewed_journey import prepare_reviewed_journey


class ReviewErrorTests(unittest.TestCase):
    def setUp(self):
        self.prepared = prepare_reviewed_journey()
        self.case = self.prepared.cases[0]
        self.request = self.case.accepted.request

    def accept(self, request):
        return acceptance.accept_classification(self.case.proposal, self.case.context, self.prepared.catalog, request)

    def test_catalog_selects_recovery_types_with_stable_legacy_strings(self):
        for code, error_type, stage in (
            ("review_proposal_changed", acceptance.ReviewConflictError, "source_binding"),
            ("review_term_duplicate", acceptance.ReviewSelectionError, "term_selection"),
            ("evaluation_precedes_review", acceptance.ReviewEffectivityError, "evaluation_context"),
            ("review_contract_invalid", acceptance.ReviewValidationError, "accepted_contract"),
        ):
            with self.subTest(code=code):
                error = acceptance._review_error(code)
                self.assertIsInstance(error, error_type)
                self.assertIsInstance(error, AdministrativeBoundaryError)
                self.assertEqual((str(error), error.code, error.stage), (code, code, stage))
                self.assertTrue(error.message)
                self.assertTrue(error.recovery)
        with self.assertRaisesRegex(ValueError, "^review failure code requires a declared descriptor$"):
            acceptance._review_error("private-fixture-value")

    def test_source_conflict_retains_accepted_value_and_fixed_feedback(self):
        before = self.case.accepted.classification.model_dump_json()
        with self.assertRaises(acceptance.ReviewConflictError) as caught:
            self.accept(replace(self.request, proposal_digest=canonical_sha256("private-fixture-value")))
        self.assertEqual(caught.exception.code, "review_proposal_changed")
        self.assertEqual(caught.exception.message, "The proposal has changed since review preparation.")
        self.assertEqual(self.case.accepted.classification.model_dump_json(), before)

    def test_term_admission_precedes_hashing_and_sorting(self):
        review = self.request.review.model_copy(update={"disposition": "revise"})
        for ids in (("x" * 129,), ("",), tuple("term-" + str(i) for i in range(33)), (object(),), ["term"]):
            with self.subTest(shape=type(ids).__name__, count=len(ids)):
                request = replace(self.request, review=review, assigned_term_ids=ids)
                with patch.object(acceptance, "set", side_effect=AssertionError("hashing preceded admission"), create=True), patch.object(acceptance, "sorted", side_effect=AssertionError("sorting preceded admission"), create=True):
                    with self.assertRaises(acceptance.ReviewSelectionError) as caught:
                        self.accept(request)
                self.assertEqual(caught.exception.code, "review_term_budget")

    def test_admitted_length_reaches_catalog_resolution(self):
        review = self.request.review.model_copy(update={"disposition": "revise"})
        with self.assertRaises(acceptance.ReviewSelectionError) as caught:
            self.accept(replace(self.request, review=review, assigned_term_ids=("x" * 128,)))
        self.assertEqual(caught.exception.code, "review_term_unresolved")

    def test_expected_validation_translates_at_its_owned_operation(self):
        with self.assertRaises(ValidationError) as invalid:
            InsuranceClassification.model_validate_json('{"raw_label":"private-fixture-value"}')
        before = self.case.accepted.classification.model_dump_json()
        with patch.object(InsuranceClassification, "model_validate_json", side_effect=invalid.exception):
            with self.assertRaises(acceptance.ReviewValidationError) as caught:
                self.accept(self.request)
        error = caught.exception
        self.assertEqual((error.code, str(error)), ("review_contract_invalid", "review_contract_invalid"))
        self.assertEqual(error.message, "The proposed accepted value requires contract reconciliation.")
        self.assertTrue(error.__suppress_context__)
        self.assertEqual(self.case.accepted.classification.model_dump_json(), before)

    def test_programming_failure_and_interrupt_keep_their_identity(self):
        for error in (RuntimeError("fixture-programming-failure"), KeyboardInterrupt()):
            with self.subTest(error_type=type(error).__name__):
                with patch.object(InsuranceClassification, "model_validate_json", side_effect=error):
                    with self.assertRaises(type(error)) as caught:
                        self.accept(self.request)
                self.assertIs(caught.exception, error)
