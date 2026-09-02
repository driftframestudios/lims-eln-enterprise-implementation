"""Promotion lifecycle tests for the observed implementation release subject."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.validate_repository import (
    validate_promotion_candidate_schema,
    validate_promotion_lifecycle,
)


ROOT = Path(__file__).resolve().parents[1]


def load(relative_path: str) -> dict:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


class PromotionLifecycleTests(unittest.TestCase):
    def records(self) -> dict[str, dict]:
        return {
            "promotion": load("receipts/promotion-receipt.json"),
            "candidate": load("receipts/promotion-candidate.json"),
            "machine": load("machine-node.json"),
            "first_receipt": load("first-receipt.json"),
            "horizon": load("COORDINATION-HORIZON.json"),
            "release": load("release/repository-role.json"),
            "inspection_manifest": load("release/public-inspection-manifest.json"),
        }

    def test_patch_candidate_and_prior_release_are_internally_coherent(self) -> None:
        validate_promotion_lifecycle(**self.records())

    def test_candidate_schema_is_executable_and_material(self) -> None:
        candidate = self.records()["candidate"]
        validate_promotion_candidate_schema(candidate)

        changed_candidate = deepcopy(candidate)
        changed_candidate["undeclared_field"] = "visible schema drift"
        with self.assertRaisesRegex(
            AssertionError,
            "promotion candidate schema validation differs",
        ):
            validate_promotion_candidate_schema(changed_candidate)

        changed_schema = load("contracts/promotion-candidate.v1.schema.json")
        changed_schema["properties"]["target_release"]["const"] = "v9.9.9"
        with tempfile.TemporaryDirectory(prefix="promotion-schema-") as directory:
            schema_path = Path(directory) / "promotion-candidate.schema.json"
            schema_path.write_text(
                json.dumps(changed_schema),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                AssertionError,
                "promotion candidate schema validation differs",
            ):
                validate_promotion_candidate_schema(
                    candidate,
                    schema_path=schema_path,
                )

    def test_candidate_coordinate_drift_is_visible(self) -> None:
        records = self.records()
        records["candidate"] = deepcopy(records["candidate"])
        records["candidate"]["candidate_coordinate"][
            "selected_future_closure_digest"
        ] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(
            AssertionError,
            "schema validation differs|exact candidate coordinates",
        ):
            validate_promotion_lifecycle(**records)

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
        with self.assertRaisesRegex(AssertionError, "prior receipt closed"):
            validate_promotion_lifecycle(**records)

    def test_patch_candidate_requires_its_open_promotion_receipt(self) -> None:
        records = self.records()
        records["machine"] = deepcopy(records["machine"])
        records["first_receipt"] = deepcopy(records["first_receipt"])
        receipt_id = "RCP-IMPLEMENTATION-PROMOTION-004"
        records["machine"]["open_receipts"].remove(receipt_id)
        records["first_receipt"]["open_receipts"].remove(receipt_id)
        with self.assertRaisesRegex(AssertionError, "current receipt open"):
            validate_promotion_lifecycle(**records)

    def test_receipt_evidence_requires_typed_material_content(self) -> None:
        records = self.records()
        records["promotion"] = deepcopy(records["promotion"])
        records["promotion"]["required_evidence"] = [{}, 2, 3, 4]
        with self.assertRaisesRegex(AssertionError, "material evidence"):
            validate_promotion_lifecycle(**records)

    def test_candidate_orientation_uses_one_reconciliation_time(self) -> None:
        records = self.records()
        records["first_receipt"] = deepcopy(records["first_receipt"])
        records["first_receipt"]["as_of"] = "2026-09-02T01:59:47Z"
        with self.assertRaisesRegex(AssertionError, "one reconciliation time"):
            validate_promotion_lifecycle(**records)


if __name__ == "__main__":
    unittest.main()
