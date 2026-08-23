from __future__ import annotations

from importlib.util import find_spec
from datetime import datetime
import json
import unittest

from lims_eln_implementation.workbench.service import WorkbenchService


CONTRACT_PACKAGE_AVAILABLE = find_spec("lims_eln_contracts") is not None


@unittest.skipUnless(
    CONTRACT_PACKAGE_AVAILABLE,
    "integrated contract proof requires lims-eln-program-specification 0.3.1",
)
class SharedContractBindingTests(unittest.TestCase):
    def test_shared_scenario_and_observation_envelope_converge(self) -> None:
        from lims_eln_contracts import (
            ObservationEnvelope,
            __version__ as shared_package_version,
            load_golden_specimen_scenario,
            model_from_strict_json,
        )

        self.assertEqual(shared_package_version, "0.3.1")

        scenario = load_golden_specimen_scenario()
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
            ObservationEnvelope,
            json.dumps(result["observation"], separators=(",", ":")),
        )
        self.assertEqual(observation.scenario_id, scenario.scenario_id)
        self.assertEqual(observation.result["state"], "released")
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
