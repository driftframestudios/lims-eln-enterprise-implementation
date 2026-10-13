"""Independent examples for the offline administrative lookup boundary."""

from dataclasses import FrozenInstanceError
import json
import unittest

from pydantic import ValidationError

from lims_eln_contracts.external_administrative import PredicateOperator
from lims_eln_implementation.administrative.core import (
    AdministrativeBoundaryError,
    CatalogSnapshot,
    InsuranceCatalog,
    PreparedPredicate,
    normalize_alias,
)
from lims_eln_implementation.administrative.journey import example_catalog


class AdministrativeLookupTests(unittest.TestCase):
    def setUp(self):
        self.catalog = example_catalog()
        self.snapshot = CatalogSnapshot(self.catalog)

    def classify(self, raw):
        return self.snapshot.classify(
            raw, classification_id="classification-fixture", context_ref="context-fixture"
        )

    def test_normalization_has_one_explicit_lookup_form(self):
        for raw, expected in (
            ("  COMMERCIAL\t plan  ", "commercial plan"),
            ("Cafe\u0301", "caf\u00e9"),
            ("\t\n ", ""),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_alias(raw), expected)

    def test_normalization_enforces_its_input_boundary(self):
        for raw in (None, 1, True, ["commercial"], "x" * 2049):
            with self.subTest(kind=type(raw).__name__):
                with self.assertRaises(AdministrativeBoundaryError):
                    normalize_alias(raw)

    def test_exact_raw_label_survives_a_successful_lookup(self):
        raw = "  COMMERCIAL\t"
        observed = self.classify(raw)
        self.assertEqual(observed.raw_label, raw)
        self.assertEqual(observed.state.value, "classified")
        self.assertEqual(tuple(term.term_id for term in observed.assigned_terms), ("employer-plan",))
        self.assertEqual(observed.disposition.value, "proposed")
        self.assertIsNone(observed.review)
        self.assertFalse(observed.multiple)

    def test_alias_ambiguity_retains_candidates_for_review(self):
        observed = self.classify("private")
        self.assertEqual(observed.state.value, "ambiguous")
        self.assertEqual(observed.assigned_terms, ())
        self.assertEqual(
            {term.term_id for term in observed.candidate_terms},
            {"employer-plan", "individual-plan"},
        )
        self.assertTrue(observed.ambiguity)
        self.assertEqual(observed.disposition.value, "proposed")

    def test_unknown_and_empty_labels_keep_their_distinct_raw_state(self):
        for raw, retained in (("unmapped label", "unmapped label"), (" \t ", None)):
            with self.subTest(raw=raw):
                observed = self.classify(raw)
                self.assertEqual(observed.state.value, "unknown")
                self.assertEqual(observed.raw_label, retained)
                self.assertEqual(observed.assigned_terms, ())
                self.assertEqual(observed.candidate_terms, ())
                self.assertTrue(observed.ambiguity)

    def test_code_lookup_keeps_release_and_reportability_explicit(self):
        for code, reportability in (("SYN-1", "category"), ("SYN-1-A", "reportable")):
            with self.subTest(code=code):
                row = next(item for item in self.catalog.diagnosis_codes if item.code == code)
                observed = self.snapshot.lookup_code(row.system, row.release, code)
                self.assertEqual(observed, row)
                self.assertEqual(observed.reportability, reportability)
                self.assertIsNone(self.snapshot.lookup_code(row.system, "99.0.0", code))
                self.assertIsNone(self.snapshot.lookup_code(row.system, row.release, code.lower()))

    def test_catalog_rejects_collisions_and_dangling_aliases(self):
        original = self.catalog.model_dump(mode="json")
        for defect in ("term", "alias", "alias-reference", "code"):
            with self.subTest(defect=defect):
                candidate = json.loads(json.dumps(original))
                if defect == "term":
                    candidate["insurance_terms"].append(candidate["insurance_terms"][0])
                elif defect == "alias":
                    alias = dict(candidate["aliases"][0])
                    alias["label"] = "  " + alias["label"].upper() + "  "
                    candidate["aliases"].append(alias)
                elif defect == "alias-reference":
                    candidate["aliases"][0]["term_ids"] = ["missing-term"]
                else:
                    candidate["diagnosis_codes"].append(candidate["diagnosis_codes"][0])
                with self.assertRaises(ValidationError):
                    InsuranceCatalog.model_validate_json(json.dumps(candidate))

    def test_catalog_owns_immutable_values_after_admission(self):
        source = self.catalog.model_dump(mode="json")
        admitted = InsuranceCatalog.model_validate_json(json.dumps(source))
        original_label = admitted.insurance_terms[0].label
        source["insurance_terms"][0]["label"] = "Changed caller label"
        self.assertEqual(admitted.insurance_terms[0].label, original_label)
        with self.assertRaises(ValidationError):
            admitted.insurance_terms[0].label = "Changed model label"


class PreparedPredicateTests(unittest.TestCase):
    def test_operator_truth_table_includes_absence_and_extra_values(self):
        for operator, expected, observed, matches in (
            (PredicateOperator.EQUALS, {"a"}, {"a"}, True),
            (PredicateOperator.EQUALS, {"a"}, {"a", "b"}, False),
            (PredicateOperator.CONTAINS_ANY, {"a", "b"}, {"b", "c"}, True),
            (PredicateOperator.CONTAINS_ANY, {"a"}, {"c"}, False),
            (PredicateOperator.CONTAINS_ALL, {"a", "b"}, {"a", "b", "c"}, True),
            (PredicateOperator.CONTAINS_ALL, {"a", "b"}, {"a"}, False),
            (PredicateOperator.PRESENT, set(), {"a"}, True),
            (PredicateOperator.PRESENT, set(), None, False),
            (PredicateOperator.EQUALS, {"a"}, None, False),
        ):
            with self.subTest(operator=operator, expected=expected, observed=observed):
                predicate = PreparedPredicate("classification_term_ids", operator, frozenset(expected))
                values = None if observed is None else frozenset(observed)
                self.assertEqual(predicate.matches(values), matches)

    def test_prepared_predicate_is_immutable(self):
        predicate = PreparedPredicate("classification_term_ids", PredicateOperator.EQUALS, frozenset({"a"}))
        with self.assertRaises(FrozenInstanceError):
            predicate.operator = PredicateOperator.PRESENT


if __name__ == "__main__":
    unittest.main()
