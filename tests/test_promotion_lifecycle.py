"""Promotion lifecycle tests for the observed implementation release subject."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from scripts.validate_repository import (
    classify_hosted_postgresql_receipt_binding,
    validate_promotion_candidate_schema,
    validate_promotion_lifecycle,
    validate_promotion_observation_schema,
)


ROOT = Path(__file__).resolve().parents[1]


def load(relative_path: str) -> dict:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


class PromotionLifecycleTests(unittest.TestCase):
    def records(self) -> dict[str, dict]:
        return {
            "promotion": load("receipts/promotion-receipt.json"),
            "candidate": load("receipts/promotion-candidate.json"),
            "observation": load("receipts/promotion-observation-v0.3.2.json"),
            "machine": load("machine-node.json"),
            "first_receipt": load("first-receipt.json"),
            "horizon": load("COORDINATION-HORIZON.json"),
            "release": load("release/repository-role.json"),
            "inspection_manifest": load("release/public-inspection-manifest.json"),
        }

    def test_observed_patch_and_retained_receipts_are_internally_coherent(self) -> None:
        validate_promotion_lifecycle(**self.records())

    def test_candidate_schema_remains_executable_and_material(self) -> None:
        candidate = self.records()["candidate"]
        validate_promotion_candidate_schema(candidate)

        changed_candidate = deepcopy(candidate)
        changed_candidate["undeclared_field"] = "visible schema drift"
        with self.assertRaisesRegex(
            AssertionError,
            "promotion candidate schema validation differs",
        ):
            validate_promotion_candidate_schema(changed_candidate)

    def test_observation_schema_is_executable_and_material(self) -> None:
        observation = self.records()["observation"]
        validate_promotion_observation_schema(observation)

        changed_observation = deepcopy(observation)
        changed_observation["undeclared_field"] = "visible schema drift"
        with self.assertRaisesRegex(
            AssertionError,
            "promotion observation schema validation differs",
        ):
            validate_promotion_observation_schema(changed_observation)

        changed_schema = load("contracts/promotion-observation.v1.schema.json")
        changed_schema["properties"]["target_release"]["const"] = "v9.9.9"
        with tempfile.TemporaryDirectory(prefix="promotion-schema-") as directory:
            schema_path = Path(directory) / "promotion-observation.schema.json"
            schema_path.write_text(json.dumps(changed_schema), encoding="utf-8")
            with self.assertRaisesRegex(
                AssertionError,
                "promotion observation schema validation differs",
            ):
                validate_promotion_observation_schema(
                    observation,
                    schema_path=schema_path,
                )

    def test_historical_carriers_retain_their_exact_bytes(self) -> None:
        expected = {
            "receipts/promotion-receipt.json": (
                "edabf3209d8f227b73e2cd7b4948638133c78e16c0dabf09ce59f7c6d46f9c8f"
            ),
            "receipts/promotion-candidate.json": (
                "c78f16df5832f6c7b39ea1b0d9a61316b26d90cd1552fd8b2c39043436a94340"
            ),
        }
        for relative_path, digest in expected.items():
            with self.subTest(path=relative_path):
                self.assertEqual(
                    digest,
                    sha256((ROOT / relative_path).read_bytes()).hexdigest(),
                )

    def test_hosted_receipt_version_and_commit_stay_bound(self) -> None:
        hosted = load("receipts/hosted-postgresql-proof.json")["version_bindings"]
        self.assertEqual(
            "accepted_prior",
            classify_hosted_postgresql_receipt_binding(hosted),
        )

        changed_commit = deepcopy(hosted)
        changed_commit["repository_commit"] = "1" * 40
        with self.assertRaisesRegex(AssertionError, "exact observed commit"):
            classify_hosted_postgresql_receipt_binding(changed_commit)

        changed_release = deepcopy(hosted)
        changed_release["repository"] = "9.9.9"
        with self.assertRaisesRegex(AssertionError, "exact retained observation"):
            classify_hosted_postgresql_receipt_binding(changed_release)

        correlated_drift = deepcopy(hosted)
        correlated_drift["repository"] = "0.3.2"
        correlated_drift["repository_commit"] = "2" * 40
        with self.assertRaisesRegex(AssertionError, "exact retained observation"):
            classify_hosted_postgresql_receipt_binding(correlated_drift)

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

    def test_observed_release_coordinate_drift_is_visible(self) -> None:
        records = self.records()
        records["observation"] = deepcopy(records["observation"])
        records["observation"]["release_coordinate"]["commit_oid"] = "1" * 40
        with self.assertRaisesRegex(
            AssertionError,
            "schema validation differs|exact v0.3.2 subject",
        ):
            validate_promotion_lifecycle(**records)

    def test_review_record_stays_distinct_from_merge_admission(self) -> None:
        records = self.records()
        records["observation"] = deepcopy(records["observation"])
        records["observation"]["release_coordinate"]["review_observation"][
            "github_review_record"
        ] = "formal_review_submitted"
        with self.assertRaisesRegex(
            AssertionError,
            "schema validation differs|exact v0.3.2 subject",
        ):
            validate_promotion_lifecycle(**records)

    def test_settled_promotion_receipts_stay_out_of_the_open_set(self) -> None:
        for receipt_id in (
            "RCP-IMPLEMENTATION-PROMOTION-003",
            "RCP-IMPLEMENTATION-PROMOTION-004",
        ):
            records = self.records()
            records["machine"] = deepcopy(records["machine"])
            records["first_receipt"] = deepcopy(records["first_receipt"])
            records["machine"]["open_receipts"].append(receipt_id)
            records["first_receipt"]["open_receipts"].append(receipt_id)
            with self.assertRaisesRegex(AssertionError, "promotion receipts closed"):
                validate_promotion_lifecycle(**records)

    def test_observation_evidence_requires_typed_material_content(self) -> None:
        records = self.records()
        records["observation"] = deepcopy(records["observation"])
        records["observation"]["required_evidence"] = [{}]
        with self.assertRaisesRegex(
            AssertionError,
            "schema validation differs|material evidence",
        ):
            validate_promotion_lifecycle(**records)

    def test_observed_orientation_uses_one_reconciliation_time(self) -> None:
        records = self.records()
        records["first_receipt"] = deepcopy(records["first_receipt"])
        records["first_receipt"]["as_of"] = "2026-09-02T01:59:47Z"
        with self.assertRaisesRegex(AssertionError, "one reconciliation time"):
            validate_promotion_lifecycle(**records)


if __name__ == "__main__":
    unittest.main()
