from __future__ import annotations

from hashlib import sha256
from importlib.util import find_spec
from importlib.metadata import version as distribution_version
from datetime import datetime
import json
import unittest

from lims_eln_implementation.workbench.service import WorkbenchService


CONTRACT_PACKAGE_AVAILABLE = find_spec("lims_eln_contracts") is not None


@unittest.skipUnless(
    CONTRACT_PACKAGE_AVAILABLE,
    "integrated contract proof requires lims-eln-program-specification 0.6.0",
)
class SharedContractBindingTests(unittest.TestCase):
    def test_shared_scenario_and_observation_envelope_converge(self) -> None:
        from lims_eln_contracts import (
            CONTRACT_VERSION,
            GoldenSpecimenObservation,
            SCHEMA_RESOURCE_NAMES,
            __version__ as shared_package_version,
            canonical_sha256,
            load_generated_schema,
            load_golden_specimen_observation_example,
            load_golden_specimen_scenario,
            load_operation_catalog,
            model_from_strict_json,
        )

        self.assertEqual(
            distribution_version("lims-eln-program-specification"), "0.6.0"
        )
        self.assertEqual(shared_package_version, "0.6.0")
        self.assertEqual(CONTRACT_VERSION, "1.0.0")

        operation_catalog = load_operation_catalog()
        self.assertGreater(len(operation_catalog.operations), 0)
        scenario = load_golden_specimen_scenario()
        for producer in ("implementation", "simulation"):
            with self.subTest(producer=producer):
                observation_example = load_golden_specimen_observation_example(producer)
                self.assertEqual(observation_example.scenario_id, scenario.scenario_id)
        for schema_name in SCHEMA_RESOURCE_NAMES:
            with self.subTest(schema=schema_name):
                self.assertIsInstance(load_generated_schema(schema_name), dict)
        scientific_result = scenario.instrument_message.raw_document["result"]
        self.assertEqual(scientific_result["unit"], "copies")
        # The shared scenario binds journey identity and expected state. The
        # implementation keeps its released concentration profile explicit
        # until an accountable mapping defines how source copies become UCUM.
        raw_document = {
            "analyte": "synthetic-dna",
            "value": "12.5",
            "unit": "ng/uL",
        }
        occurred_at = datetime.fromisoformat(
            scenario.commands[0].occurred_at.removesuffix("Z") + "+00:00"
        )
        service = WorkbenchService(
            tenant_id=scenario.specimen.tenant_id,
            actor_ids=frozenset(
                {
                    scenario.commands[0].actor_id,
                    scenario.commands[-2].actor_id,
                    scenario.commands[-1].actor_id,
                }
            ),
            clock=lambda: occurred_at,
        )
        result = service.run_golden_specimen(
            run_id="RUN-SHARED-GOLDEN-001",
            tenant_id=scenario.specimen.tenant_id,
            specimen_id=scenario.specimen.specimen_id,
            actor_id=scenario.commands[0].actor_id,
            scientist_id=scenario.commands[-2].actor_id,
            quality_actor_id=scenario.commands[-1].actor_id,
            occurred_at=occurred_at,
            raw_instrument_json=json.dumps(
                raw_document,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8"),
            vendor_payload={"status": scenario.expected_state.lifecycle_state},
        )

        self.assertEqual(
            result["specimen"]["state"],
            scenario.expected_state.lifecycle_state,
        )
        self.assertEqual(
            result["specimen"]["version"],
            scenario.expected_state.aggregate_version,
        )
        self.assertEqual(
            result["specimen"]["custody"]["location"],
            scenario.expected_state.custody_location,
        )
        observation = model_from_strict_json(
            GoldenSpecimenObservation,
            json.dumps(result["observation"], separators=(",", ":")),
        )
        self.assertEqual(
            observation.scenario_coordinate(),
            (
                scenario.scenario_id,
                scenario.scenario_version,
                canonical_sha256(scenario),
            ),
        )
        projection = observation.result.projection
        receipt = result["specimen"]["instrument_receipts"][0]
        review_event = result["specimen"]["events"][3]
        release_event = result["specimen"]["events"][4]
        self.assertEqual(projection.tenant_id, result["specimen"]["tenant_id"])
        self.assertEqual(projection.specimen_id, result["specimen"]["specimen_id"])
        self.assertEqual(projection.lifecycle.state, result["specimen"]["state"])
        self.assertEqual(
            projection.lifecycle.aggregate_version,
            result["specimen"]["version"],
        )
        self.assertEqual(
            projection.custody.current_location,
            result["specimen"]["custody"]["location"],
        )
        self.assertEqual(
            projection.measurement.analyte,
            receipt["normalized_observation"]["analyte"],
        )
        self.assertEqual(
            projection.measurement.value,
            float(receipt["normalized_observation"]["value"]),
        )
        self.assertEqual(
            projection.measurement.unit,
            receipt["normalized_observation"]["unit"],
        )
        self.assertEqual(projection.measurement.quality_flag.value, "pass")
        self.assertEqual(review_event["payload"]["decision"], "accepted")
        self.assertEqual(review_event["payload"]["quality_flag"], "pass")
        self.assertEqual(
            projection.review_resolution.review_id,
            review_event["payload"]["review_id"],
        )
        self.assertEqual(projection.review_resolution.decision, "accepted")
        self.assertEqual(
            projection.release.approval_receipt_id,
            release_event["payload"]["approval_receipt_id"],
        )
        configuration = observation.result.producer_detail["configuration"]
        self.assertEqual(configuration["state_adapter"], "process_local")
        self.assertEqual(
            observation.source.configuration_digest,
            canonical_sha256(configuration),
        )
        self.assertEqual(
            observation.provenance.raw_artifact_digest,
            "sha256:" + receipt["raw_sha256"],
        )
        self.assertEqual(observation.provenance.performed_by, scenario.commands[0].actor_id)
        self.assertEqual(
            observation.provenance.reviewed_by,
            scenario.commands[-2].actor_id,
        )
        self.assertNotEqual(
            observation.provenance.performed_by,
            observation.provenance.reviewed_by,
        )
        self.assertEqual(
            observation.provenance.governed_locator,
            "memory://workbench/RUN-SHARED-GOLDEN-001",
        )
        expected_suffix = sha256(b"RUN-SHARED-GOLDEN-001").hexdigest()[:16].upper()
        self.assertEqual(
            observation.observation_id,
            f"OBS-WORKBENCH-{expected_suffix}",
        )
        self.assertEqual(
            service.observation(scenario.specimen.tenant_id, "RUN-SHARED-GOLDEN-001"),
            result["observation"],
        )

        from fastapi.testclient import TestClient

        from lims_eln_implementation.workbench.api import create_app

        response = TestClient(create_app(service)).get(
            "/api/workbench/observations/RUN-SHARED-GOLDEN-001",
            headers={"X-Tenant-ID": scenario.specimen.tenant_id},
            params={"tenant_id": scenario.specimen.tenant_id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), result["observation"])


if __name__ == "__main__":
    unittest.main()
