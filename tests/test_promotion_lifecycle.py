"""Promotion lifecycle tests for the observed implementation release subject."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from scripts.validate_repository import validate_promotion_lifecycle


ROOT = Path(__file__).resolve().parents[1]


def load(relative_path: str) -> dict:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


class PromotionLifecycleTests(unittest.TestCase):
    def records(self) -> dict[str, dict]:
        return {
            "promotion": load("receipts/promotion-receipt.json"),
            "machine": load("machine-node.json"),
            "first_receipt": load("first-receipt.json"),
            "horizon": load("COORDINATION-HORIZON.json"),
            "release": load("release/repository-role.json"),
            "inspection_manifest": load("release/public-inspection-manifest.json"),
        }

    def test_observed_release_subject_is_internally_coherent(self) -> None:
        validate_promotion_lifecycle(**self.records())

    def test_review_boundary_drift_is_visible(self) -> None:
        records = self.records()
        records["promotion"] = deepcopy(records["promotion"])
        records["promotion"]["release_coordinate"]["codeowner_resolution"] = (
            "evidence://github/pull-requests/23/formal-review"
        )
        with self.assertRaisesRegex(AssertionError, "observed tag coordinate"):
            validate_promotion_lifecycle(**records)

    def test_promotion_receipt_cannot_return_to_the_open_set(self) -> None:
        records = self.records()
        records["machine"] = deepcopy(records["machine"])
        records["first_receipt"] = deepcopy(records["first_receipt"])
        receipt_id = "RCP-IMPLEMENTATION-PROMOTION-003"
        records["machine"]["open_receipts"].append(receipt_id)
        records["first_receipt"]["open_receipts"].append(receipt_id)
        with self.assertRaisesRegex(AssertionError, "closes the implementation"):
            validate_promotion_lifecycle(**records)

    def test_receipt_evidence_requires_typed_material_content(self) -> None:
        records = self.records()
        records["promotion"] = deepcopy(records["promotion"])
        records["promotion"]["required_evidence"] = [{}, 2, 3, 4]
        with self.assertRaisesRegex(AssertionError, "material evidence"):
            validate_promotion_lifecycle(**records)

    def test_orientation_time_follows_tag_promotion(self) -> None:
        records = self.records()
        records["first_receipt"] = deepcopy(records["first_receipt"])
        records["first_receipt"]["as_of"] = "2026-09-02T01:59:47Z"
        with self.assertRaisesRegex(AssertionError, "post-promotion coordinate"):
            validate_promotion_lifecycle(**records)


if __name__ == "__main__":
    unittest.main()
