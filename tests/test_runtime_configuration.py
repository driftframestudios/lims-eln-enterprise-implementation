from __future__ import annotations

import json
import logging
from pathlib import Path
import sys
import unittest

from lims_eln_implementation.runtime_configuration import (
    AwsResourceScope,
    ConfigurationResolutionError,
    ResolutionCode,
    RuntimeConfigurationResolver,
    RuntimeSettingCatalog,
    RuntimeValueRedactionFilter,
    SettingClassification,
    SettingSource,
    SettingSpec,
)


ROOT = Path(__file__).resolve().parents[1]
PARAMETER_ARN = (
    "arn:aws:ssm:us-east-1:111122223333:"
    "parameter/example-laboratory/lims-eln-reference/sandbox/config/vendor-base-url"
)
SECRET_ARN = (
    "arn:aws:secretsmanager:us-east-1:111122223333:"
    "secret:example-laboratory/lims-eln-reference/sandbox/vendor-credentials-SYN001"
)


class ManualClock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeParameterStore:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.value = "https://synthetic-vendor.invalid"
        self.version = 7

    def get_parameter(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        name = kwargs["Name"]
        parameter: dict[str, object] = {
            "Name": PARAMETER_ARN,
            "Type": "String",
            "Value": self.value,
            "Version": self.version,
        }
        if name != PARAMETER_ARN:
            parameter["Selector"] = name
        return {
            "Parameter": parameter
        }


class FakeSecretsManager:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.value = json.dumps(
            {
                "client_id": "SYN-CLIENT-01",
                "credential": "SYN-RUNTIME-VALUE-01",
            }
        )
        self.version = "1" * 32
        self.failure: Exception | None = None

    def get_secret_value(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        if self.failure is not None:
            raise self.failure
        return {
            "ARN": SECRET_ARN,
            "SecretString": self.value,
            "VersionId": self.version,
            "VersionStages": ["AWSCURRENT"],
        }


class FakeProviderError(Exception):
    def __init__(self, code: str, protected_message: str) -> None:
        self.response = {
            "Error": {
                "Code": code,
                "Message": protected_message,
            }
        }
        super().__init__(protected_message)


def parameter_spec(**overrides: object) -> SettingSpec:
    values: dict[str, object] = {
        "logical_name": "vendor.base_url",
        "classification": SettingClassification.CONFIGURATION,
        "source": SettingSource.PARAMETER_STORE,
        "resource_arn": PARAMETER_ARN,
        "cache_ttl_seconds": 30,
    }
    values.update(overrides)
    return SettingSpec(**values)  # type: ignore[arg-type]


def secret_spec(**overrides: object) -> SettingSpec:
    values: dict[str, object] = {
        "logical_name": "vendor.credentials",
        "classification": SettingClassification.SECRET,
        "source": SettingSource.SECRETS_MANAGER,
        "resource_arn": SECRET_ARN,
        "cache_ttl_seconds": 10,
        "secret_version_stage": "AWSCURRENT",
    }
    values.update(overrides)
    return SettingSpec(**values)  # type: ignore[arg-type]


class RuntimeConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = ManualClock()
        self.parameters = FakeParameterStore()
        self.secrets = FakeSecretsManager()
        self.resolver = RuntimeConfigurationResolver(
            scope=AwsResourceScope("aws", "us-east-1", "111122223333"),
            parameter_store=self.parameters,
            secrets_manager=self.secrets,
            monotonic=self.clock,
        )

    def test_catalog_makes_configuration_and_secret_placement_explicit(self) -> None:
        document = json.loads(
            (
                ROOT / "fixtures" / "synthetic" / "runtime-setting-catalog.v1.json"
            ).read_text(encoding="utf-8")
        )
        catalog = RuntimeSettingCatalog.from_mapping(document)
        self.assertEqual(catalog.schema_version, "1.0.0")
        self.assertEqual(
            catalog.require("vendor.base_url").source,
            SettingSource.PARAMETER_STORE,
        )
        self.assertEqual(
            catalog.require("vendor.credentials").source,
            SettingSource.SECRETS_MANAGER,
        )

    def test_catalog_requires_released_version_and_bounded_selectors(self) -> None:
        document = json.loads(
            (
                ROOT / "fixtures" / "synthetic" / "runtime-setting-catalog.v1.json"
            ).read_text(encoding="utf-8")
        )
        document["schema_version"] = "latest"
        with self.assertRaisesRegex(ValueError, "released 1.0.0"):
            RuntimeSettingCatalog.from_mapping(document)

        with self.assertRaisesRegex(ValueError, "parameter_label"):
            parameter_spec(parameter_label="../candidate")
        with self.assertRaisesRegex(ValueError, "secret_version_id"):
            secret_spec(secret_version_id="short")
        with self.assertRaisesRegex(ValueError, "secret_version_stage"):
            secret_spec(secret_version_stage="AWSCURRENT;next")

    def test_parameter_version_and_decryption_posture_reach_provider(self) -> None:
        self.parameters.version = 4
        resolved = self.resolver.resolve(parameter_spec(parameter_version=4))
        self.assertEqual(resolved.reveal(), "https://synthetic-vendor.invalid")
        self.assertEqual(
            self.parameters.calls,
            [{"Name": f"{PARAMETER_ARN}:4", "WithDecryption": False}],
        )
        self.assertEqual(resolved.version, "4")
        self.assertIn("[REDACTED]", repr(resolved))
        self.assertNotIn(resolved.reveal(), repr(resolved))

    def test_secret_stage_and_id_reach_provider_as_explicit_selectors(self) -> None:
        version_id = "2" * 32
        self.secrets.version = version_id
        original = self.secrets.get_secret_value

        def previous_secret(**kwargs: object) -> dict[str, object]:
            response = original(**kwargs)
            response["VersionStages"] = ["AWSPREVIOUS"]
            return response

        self.secrets.get_secret_value = previous_secret  # type: ignore[method-assign]
        resolved = self.resolver.resolve(
            secret_spec(
                secret_version_id=version_id,
                secret_version_stage="AWSPREVIOUS",
            )
        )
        self.assertEqual(
            self.secrets.calls,
            [
                {
                    "SecretId": SECRET_ARN,
                    "VersionId": version_id,
                    "VersionStage": "AWSPREVIOUS",
                }
            ],
        )
        self.assertEqual(resolved.version, version_id)

    def test_secret_cache_refreshes_after_ttl_and_supports_rotation_refresh(self) -> None:
        spec = secret_spec()
        first = self.resolver.resolve(spec)
        second = self.resolver.resolve(spec)
        self.assertIs(first, second)
        self.assertEqual(len(self.secrets.calls), 1)

        self.secrets.version = "2" * 32
        refreshed = self.resolver.resolve(spec, force_refresh=True)
        self.assertEqual(refreshed.version, "2" * 32)
        self.assertEqual(len(self.secrets.calls), 2)

        self.clock.advance(11)
        self.secrets.version = "3" * 32
        after_expiry = self.resolver.resolve(spec)
        self.assertEqual(after_expiry.version, "3" * 32)
        self.assertEqual(len(self.secrets.calls), 3)

    def test_expired_value_returns_to_provider_and_provider_failure_surfaces(self) -> None:
        spec = secret_spec(cache_ttl_seconds=5)
        self.resolver.resolve(spec)
        self.clock.advance(6)
        protected_message = "provider included SYN-RUNTIME-VALUE-01"
        self.secrets.failure = FakeProviderError(
            "AccessDeniedException",
            protected_message,
        )
        with self.assertRaises(ConfigurationResolutionError) as captured:
            self.resolver.resolve(spec)
        self.assertEqual(captured.exception.code, ResolutionCode.ACCESS)
        self.assertFalse(captured.exception.retryable)
        self.assertNotIn(protected_message, str(captured.exception))
        self.assertNotIn(protected_message, json.dumps(captured.exception.safe_fields()))
        self.assertEqual(len(self.secrets.calls), 2)

    def test_scope_mismatch_stops_before_provider_call(self) -> None:
        foreign = secret_spec(
            resource_arn=SECRET_ARN.replace("111122223333", "999900001111")
        )
        with self.assertRaises(ConfigurationResolutionError) as captured:
            self.resolver.resolve(foreign)
        self.assertEqual(captured.exception.code, ResolutionCode.RESOURCE_SCOPE)
        self.assertEqual(self.secrets.calls, [])

    def test_secure_string_parameter_returns_to_catalog_classification(self) -> None:
        original = self.parameters.get_parameter

        def secure_parameter(**kwargs: object) -> dict[str, object]:
            response = original(**kwargs)
            parameter = response["Parameter"]
            assert isinstance(parameter, dict)
            parameter["Type"] = "SecureString"
            return response

        self.parameters.get_parameter = secure_parameter  # type: ignore[method-assign]
        with self.assertRaises(ConfigurationResolutionError) as captured:
            self.resolver.resolve(parameter_spec())
        self.assertEqual(captured.exception.code, ResolutionCode.CLASSIFICATION)

    def test_json_member_exposes_only_the_requested_member(self) -> None:
        member = self.resolver.resolve_json_member(
            secret_spec(),
            member="client_id",
        )
        self.assertEqual(member.reveal(), "SYN-CLIENT-01")
        self.assertIn("[REDACTED]", repr(member))

    def test_secret_json_member_rejects_ambiguous_json(self) -> None:
        for payload, provider_code in (
            ('{"client_id":"first","client_id":"second"}', "ValueError"),
            ('{"client_id":NaN}', "ValueError"),
        ):
            with self.subTest(payload=payload):
                self.secrets.value = payload
                with self.assertRaises(ConfigurationResolutionError) as captured:
                    self.resolver.resolve_json_member(
                        secret_spec(),
                        member="client_id",
                        force_refresh=True,
                    )
                self.assertEqual(captured.exception.code, ResolutionCode.PAYLOAD)
                self.assertEqual(captured.exception.provider_code, provider_code)

    def test_redaction_filter_replaces_registered_values_in_structured_logs(self) -> None:
        resolved = self.resolver.resolve(secret_spec())
        guard = RuntimeValueRedactionFilter()
        guard.register(resolved)
        record = logging.LogRecord(
            name="runtime-configuration-test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="credential payload=%s",
            args=(resolved.reveal(),),
            exc_info=None,
        )
        self.assertTrue(guard.filter(record))
        self.assertEqual(record.getMessage(), "credential payload=[REDACTED]")

    def test_redaction_filter_registers_a_derived_member_at_consumption(self) -> None:
        member = self.resolver.resolve_json_member(
            secret_spec(),
            member="client_id",
        )
        guard = RuntimeValueRedactionFilter()
        guard.register(member)
        record = logging.LogRecord(
            name="runtime-configuration-test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg={"client_id": member.reveal()},
            args=(),
            exc_info=None,
        )
        self.assertTrue(guard.filter(record))
        self.assertEqual(record.msg, {"client_id": "[REDACTED]"})

    def test_redaction_filter_scrubs_traceback_chain_stack_and_extras(self) -> None:
        resolved = self.resolver.resolve(secret_spec())
        protected = resolved.reveal()
        guard = RuntimeValueRedactionFilter()
        guard.register(resolved)
        try:
            try:
                raise FakeProviderError("AccessDeniedException", protected)
            except FakeProviderError as cause:
                raise RuntimeError(f"outer failure {protected}") from cause
        except RuntimeError:
            record = logging.LogRecord(
                name="runtime-configuration-test",
                level=logging.ERROR,
                pathname=__file__,
                lineno=1,
                msg="resolution failed",
                args=(),
                exc_info=sys.exc_info(),
            )
        record.stack_info = f"synthetic stack {protected}"
        record.provider_context = {"detail": protected}

        self.assertTrue(guard.filter(record))
        rendered = logging.Formatter(
            "%(message)s %(provider_context)s"
        ).format(record)

        self.assertNotIn(protected, rendered)
        self.assertNotIn(protected, record.stack_info)
        self.assertEqual(record.provider_context, {"detail": "[REDACTED]"})

    def test_parameter_and_secret_responses_bind_to_requested_identity(self) -> None:
        original_parameter = self.parameters.get_parameter

        def foreign_parameter(**kwargs: object) -> dict[str, object]:
            response = original_parameter(**kwargs)
            parameter = response["Parameter"]
            assert isinstance(parameter, dict)
            parameter["Name"] = PARAMETER_ARN.replace(
                "vendor-base-url", "foreign-value"
            )
            return response

        self.parameters.get_parameter = foreign_parameter  # type: ignore[method-assign]
        with self.assertRaises(ConfigurationResolutionError) as captured:
            self.resolver.resolve(parameter_spec())
        self.assertEqual(captured.exception.code, ResolutionCode.RESOURCE_SCOPE)

        self.parameters.get_parameter = original_parameter  # type: ignore[method-assign]
        original_secret = self.secrets.get_secret_value

        def foreign_secret(**kwargs: object) -> dict[str, object]:
            response = original_secret(**kwargs)
            response["ARN"] = SECRET_ARN.replace("SYN001", "OTHER1")
            return response

        self.secrets.get_secret_value = foreign_secret  # type: ignore[method-assign]
        with self.assertRaises(ConfigurationResolutionError) as captured:
            self.resolver.resolve(secret_spec(), force_refresh=True)
        self.assertEqual(captured.exception.code, ResolutionCode.RESOURCE_SCOPE)

    def test_requested_secret_stage_must_be_returned_by_provider(self) -> None:
        original = self.secrets.get_secret_value

        def stale_stage(**kwargs: object) -> dict[str, object]:
            response = original(**kwargs)
            response["VersionStages"] = ["AWSPREVIOUS"]
            return response

        self.secrets.get_secret_value = stale_stage  # type: ignore[method-assign]
        with self.assertRaises(ConfigurationResolutionError) as captured:
            self.resolver.resolve(secret_spec())
        self.assertEqual(captured.exception.provider_code, "SecretStageMismatch")

    def test_invalidation_removes_only_the_selected_logical_name(self) -> None:
        self.resolver.resolve(parameter_spec())
        self.resolver.resolve(secret_spec())
        self.assertEqual(self.resolver.invalidate("vendor.credentials"), 1)
        self.resolver.resolve(parameter_spec())
        self.resolver.resolve(secret_spec())
        self.assertEqual(len(self.parameters.calls), 1)
        self.assertEqual(len(self.secrets.calls), 2)

    def test_catalog_enforces_source_classification_pair(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires secret classification"):
            SettingSpec(
                logical_name="vendor.credentials",
                classification=SettingClassification.CONFIGURATION,
                source=SettingSource.SECRETS_MANAGER,
                resource_arn=SECRET_ARN,
                cache_ttl_seconds=10,
            )

    def test_secret_cache_ttl_has_security_bound(self) -> None:
        with self.assertRaisesRegex(ValueError, "0..900"):
            secret_spec(cache_ttl_seconds=901)


if __name__ == "__main__":
    unittest.main()
