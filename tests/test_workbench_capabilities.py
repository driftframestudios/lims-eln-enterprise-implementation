"""Capability projection evidence, independent of a running database."""

import json
from hashlib import sha256
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from lims_eln_implementation.workbench.api import create_app
from lims_eln_implementation.workbench.capabilities import (
    CapabilityConfigurationError,
    describe_workbench,
)
from lims_eln_implementation.workbench.service import WorkbenchService
from lims_eln_implementation.workbench.shared_contracts import (
    EXPECTED_CONTRACT_VERSION,
    EXPECTED_PACKAGE_VERSION,
)


ROOT = Path(__file__).resolve().parents[1]


class WorkbenchCapabilitiesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.validator = Draft202012Validator(json.loads(
            (ROOT / "contracts/workbench-capabilities.v1.schema.json").read_text()
        ))

    def test_projection_conforms_for_each_adapter_and_package_posture(self) -> None:
        for adapter, lifetime in (("process_local", "process"), ("postgresql", "database")):
            for compatible in (False, True):
                with self.subTest(adapter=adapter, compatible=compatible):
                    record = describe_workbench(adapter, package_compatible=compatible)
                    self.validator.validate(record)
                    self.assertEqual(record["runtime"]["state_lifetime"], lifetime)
                    self.assertEqual(record["shared_contracts"], {
                        "expected_package_version": EXPECTED_PACKAGE_VERSION,
                        "expected_contract_version": EXPECTED_CONTRACT_VERSION,
                        "version_compatible": compatible,
                    })

    def test_invalid_adapter_and_truthy_compatibility_have_specific_errors(self) -> None:
        for adapter in (None, [], {}, 1, "sqlite", "postgresql\n"):
            with self.subTest(adapter=adapter):
                with self.assertRaisesRegex(CapabilityConfigurationError, "Select process_local or postgresql"):
                    describe_workbench(adapter, package_compatible=True)
        for compatible in (None, 0, 1, "true", [], {}):
            with self.subTest(compatible=compatible):
                with self.assertRaisesRegex(CapabilityConfigurationError, "explicit Boolean"):
                    describe_workbench("process_local", package_compatible=compatible)

    def test_each_projection_owns_its_nested_records(self) -> None:
        edited = describe_workbench("process_local", package_compatible=False)
        edited["runtime"]["state_adapter"] = "changed"
        edited["shared_contracts"]["expected_package_version"] = "changed"
        edited["operations"]["summary"]["path"] = "/changed"
        fresh = describe_workbench("process_local", package_compatible=False)
        self.assertEqual(fresh["runtime"]["state_adapter"], "process_local")
        self.assertEqual(fresh["shared_contracts"]["expected_package_version"], EXPECTED_PACKAGE_VERSION)
        self.assertEqual(fresh["operations"]["summary"]["path"], "/api/workbench/summary")

    def test_api_and_authored_page_describe_the_composed_adapter(self) -> None:
        for adapter, wording in (("process_local", "Process-local state"), ("postgresql", "PostgreSQL-backed state")):
            for compatible in (False, True):
                with self.subTest(adapter=adapter, compatible=compatible):
                    # The fixture declares composition only. Any database observation fails here.
                    service = WorkbenchService()
                    service.state_adapter = adapter
                    with patch.object(service, "check_ready", side_effect=AssertionError("readiness is separate")), patch(
                        "lims_eln_implementation.workbench.api.contract_available", return_value=compatible
                    ), TestClient(create_app(service)) as client:
                        response = client.get("/api/workbench/capabilities")
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.headers["cache-control"], "no-store")
                        self.validator.validate(response.json())
                        self.assertIs(response.json()["shared_contracts"]["version_compatible"], compatible)
                        page = client.get("/workbench")
                        self.assertEqual(page.status_code, 200)
                        self.assertEqual(page.headers["cache-control"], "no-store")
                        self.assertIn(wording, page.text)
                        self.assertIn(f'data-expected-package-version="{EXPECTED_PACKAGE_VERSION}"', page.text)
                        self.assertIn('href="/api/workbench/capabilities"', page.text)

    def test_each_declared_operation_corresponds_to_an_actual_route(self) -> None:
        app = create_app()
        routes = {(route.path, method) for route in app.routes
                  for method in (getattr(route, "methods", None) or ())}
        document = describe_workbench("process_local", package_compatible=False)
        self.assertEqual(set(document["operations"]), {
            "summary", "specimen", "observation", "golden_specimen", "instrument_recovery",
        })
        for name, operation in document["operations"].items():
            with self.subTest(operation=name):
                self.assertIn((operation["path"], operation["method"]), routes)

    def test_unknown_adapter_ends_composition(self) -> None:
        service = WorkbenchService()
        service.state_adapter = "unregistered"
        with self.assertRaises(CapabilityConfigurationError):
            create_app(service)

    def test_schema_copy_retains_its_declared_source_binding(self) -> None:
        binding = json.loads((ROOT / "contracts/workbench-capabilities.source.json").read_text())
        schema_bytes = (ROOT / "contracts/workbench-capabilities.v1.schema.json").read_bytes()
        self.assertEqual(binding["source_repository"], "driftframestudios/lims-eln-program-specification")
        self.assertRegex(binding["source_commit"], r"\A[0-9a-f]{40}\Z")
        self.assertEqual(binding["source_path"], "schemas/workbench-capabilities.v1.schema.json")
        self.assertEqual(binding["schema_sha256"], "sha256:" + sha256(schema_bytes).hexdigest())
        self.assertEqual(binding["contract_id"], json.loads(schema_bytes)["$id"])


if __name__ == "__main__":
    unittest.main()
