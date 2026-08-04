"""AWS runtime references resolved by Powertools Parameters."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SettingSource(StrEnum):
    PARAMETER_STORE = "parameter_store"
    SECRETS_MANAGER = "secrets_manager"


class SettingClassification(StrEnum):
    CONFIGURATION = "configuration"
    SECRET = "secret"


class SettingSpec(BaseModel):
    """Value-free reference to one AWS-managed runtime setting."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    logical_name: str = Field(min_length=1)
    classification: SettingClassification
    source: SettingSource
    resource_arn: str = Field(pattern=r"^arn:[^:]+:(ssm|secretsmanager):[^:]+:[0-9]{12}:.+$")
    cache_ttl_seconds: int = Field(ge=0, le=3600)
    parameter_version: int | None = Field(default=None, ge=1)
    secret_version_id: str | None = None
    secret_version_stage: str | None = None

    @model_validator(mode="after")
    def source_matches_classification(self) -> SettingSpec:
        if (
            self.classification is SettingClassification.SECRET
            and self.source is not SettingSource.SECRETS_MANAGER
        ):
            raise ValueError("secret settings require Secrets Manager")
        if (
            self.classification is SettingClassification.CONFIGURATION
            and self.source is not SettingSource.PARAMETER_STORE
        ):
            raise ValueError("configuration settings require Parameter Store")
        return self


class RuntimeSettingCatalog(BaseModel):
    """Typed catalog produced by infrastructure outputs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    aws_scope: Mapping[str, str]
    settings: tuple[SettingSpec, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> RuntimeSettingCatalog:
        return cls.model_validate(value)

    def require(self, logical_name: str) -> SettingSpec:
        matches = [item for item in self.settings if item.logical_name == logical_name]
        if len(matches) != 1:
            raise KeyError(f"runtime catalog requires one {logical_name!r} setting")
        return matches[0]


ParameterGetter = Callable[..., Any]


def _powertools_parameter(**kwargs: Any) -> Any:
    from aws_lambda_powertools.utilities import parameters

    return parameters.get_parameter(**kwargs)


def _powertools_secret(**kwargs: Any) -> Any:
    from aws_lambda_powertools.utilities import parameters

    return parameters.get_secret(**kwargs)


class AwsRuntimeSettings:
    """Delegate retrieval, caching, decryption, and provider errors to Powertools."""

    def __init__(
        self,
        *,
        get_parameter: ParameterGetter = _powertools_parameter,
        get_secret: ParameterGetter = _powertools_secret,
    ) -> None:
        self._get_parameter = get_parameter
        self._get_secret = get_secret

    def resolve(self, spec: SettingSpec) -> Any:
        if spec.source is SettingSource.PARAMETER_STORE:
            name = spec.resource_arn
            if spec.parameter_version is not None:
                name = f"{name}:{spec.parameter_version}"
            return self._get_parameter(
                name=name,
                max_age=spec.cache_ttl_seconds,
                decrypt=False,
            )

        sdk_options = {
            key: value
            for key, value in (
                ("VersionId", spec.secret_version_id),
                ("VersionStage", spec.secret_version_stage),
            )
            if value is not None
        }
        return self._get_secret(
            name=spec.resource_arn,
            max_age=spec.cache_ttl_seconds,
            **sdk_options,
        )
