from __future__ import annotations

import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from lims_eln_implementation.runtime_configuration import (
    AwsRuntimeSettings,
    RuntimeSettingCatalog,
    SettingSource,
)

ROOT = Path(__file__).resolve().parents[1]


class RecordingGetter:
    def __init__(self, value: object) -> None:
        self.value = value
        self.calls: list[dict[str, object]] = []

    def __call__(self, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        return self.value


class RuntimeConfigurationTests(unittest.TestCase):
    def catalog(self) -> RuntimeSettingCatalog:
        document = json.loads(
            (ROOT / "fixtures/synthetic/runtime-setting-catalog.v1.json").read_text(
                encoding="utf-8"
            )
        )
        return RuntimeSettingCatalog.from_mapping(document)

    def test_catalog_uses_pydantic_for_value_free_references(self) -> None:
        catalog = self.catalog()
        self.assertEqual(catalog.schema_version, "1.0.0")
        self.assertEqual(
            catalog.require("vendor.base_url").source,
            SettingSource.PARAMETER_STORE,
        )
        self.assertEqual(
            catalog.require("vendor.credentials").source,
            SettingSource.SECRETS_MANAGER,
        )

    def test_catalog_rejects_unknown_fields_and_source_mismatch(self) -> None:
        document = json.loads(
            (ROOT / "fixtures/synthetic/runtime-setting-catalog.v1.json").read_text(
                encoding="utf-8"
            )
        )
        document["settings"][0]["unexpected"] = "value"
        with self.assertRaises(ValidationError):
            RuntimeSettingCatalog.from_mapping(document)

        del document["settings"][0]["unexpected"]
        document["settings"][0]["classification"] = "secret"
        with self.assertRaises(ValidationError):
            RuntimeSettingCatalog.from_mapping(document)

    def test_powertools_owns_parameter_retrieval_and_cache(self) -> None:
        catalog = self.catalog()
        parameter = RecordingGetter("https://synthetic-vendor.invalid")
        secret = RecordingGetter("unused")
        settings = AwsRuntimeSettings(
            get_parameter=parameter,
            get_secret=secret,
        )

        value = settings.resolve(catalog.require("vendor.base_url"))

        self.assertEqual(value, "https://synthetic-vendor.invalid")
        self.assertEqual(
            parameter.calls,
            [
                {
                    "name": catalog.require("vendor.base_url").resource_arn + ":1",
                    "max_age": 900,
                    "decrypt": False,
                }
            ],
        )
        self.assertEqual(secret.calls, [])

    def test_powertools_receives_secret_stage_without_plaintext_metadata(self) -> None:
        catalog = self.catalog()
        parameter = RecordingGetter("unused")
        secret = RecordingGetter('{"client_id":"SYN-CLIENT-01"}')
        settings = AwsRuntimeSettings(
            get_parameter=parameter,
            get_secret=secret,
        )

        value = settings.resolve(catalog.require("vendor.credentials"))

        self.assertEqual(value, '{"client_id":"SYN-CLIENT-01"}')
        self.assertEqual(
            secret.calls,
            [
                {
                    "name": catalog.require("vendor.credentials").resource_arn,
                    "max_age": 300,
                    "VersionStage": "AWSCURRENT",
                }
            ],
        )
        self.assertEqual(parameter.calls, [])


if __name__ == "__main__":
    unittest.main()
