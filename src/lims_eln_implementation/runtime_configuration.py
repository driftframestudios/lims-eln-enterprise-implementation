"""Account-scoped runtime configuration and secret retrieval.

The module presents a small port over AWS SDK-shaped clients. Production
composition can inject boto3 clients while tests and local proofs use standard
library fakes.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
import json
import logging
import re
from threading import RLock
import time
from typing import Any, Protocol


class SettingSource(StrEnum):
    PARAMETER_STORE = "parameter_store"
    SECRETS_MANAGER = "secrets_manager"


class SettingClassification(StrEnum):
    CONFIGURATION = "configuration"
    SECRET = "secret"


class ResolutionCode(StrEnum):
    RESOURCE_SCOPE = "resource_scope"
    CLASSIFICATION = "classification"
    ACCESS = "access"
    MISSING = "missing"
    THROTTLED = "throttled"
    PAYLOAD = "payload"
    PROVIDER = "provider"


_PARTITION = re.compile(r"^aws(?:-us-gov|-cn)?$")
_REGION = re.compile(r"^[a-z]{2}(?:-gov)?-[a-z]+-\d$")
_ACCOUNT = re.compile(r"^\d{12}$")
_LOGICAL_NAME = re.compile(r"^[a-z][a-z0-9_.-]{2,127}$")
_PARAMETER_LABEL = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_SECRET_VERSION_ID = re.compile(r"^[A-Za-z0-9-]{32,64}$")
_SECRET_VERSION_STAGE = re.compile(r"^[A-Za-z0-9/_+=.@-]{1,256}$")
_PARAMETER_ARN = re.compile(
    r"^arn:(?P<partition>aws(?:-us-gov|-cn)?):ssm:"
    r"(?P<region>[^:]+):(?P<account>\d{12}):parameter/(?P<name>.+)$"
)
_SECRET_ARN = re.compile(
    r"^arn:(?P<partition>aws(?:-us-gov|-cn)?):secretsmanager:"
    r"(?P<region>[^:]+):(?P<account>\d{12}):secret:(?P<name>.+)$"
)


@dataclass(frozen=True, slots=True)
class AwsResourceScope:
    """AWS identity boundary applied before every provider request."""

    partition: str
    region: str
    account_id: str

    def __post_init__(self) -> None:
        if _PARTITION.fullmatch(self.partition) is None:
            raise ValueError("partition requires a supported AWS partition")
        if _REGION.fullmatch(self.region) is None:
            raise ValueError("region requires an explicit AWS region")
        if _ACCOUNT.fullmatch(self.account_id) is None:
            raise ValueError("account_id requires a 12-digit AWS account identifier")

    def validate(self, *, resource_arn: str, source: SettingSource) -> None:
        pattern = (
            _PARAMETER_ARN
            if source is SettingSource.PARAMETER_STORE
            else _SECRET_ARN
        )
        match = pattern.fullmatch(resource_arn)
        if match is None:
            raise ConfigurationResolutionError(
                code=ResolutionCode.RESOURCE_SCOPE,
                logical_name="catalog-entry",
                source=source,
                resource_fingerprint=_fingerprint(resource_arn),
                retryable=False,
                provider_code="InvalidArn",
            )
        observed = (
            match.group("partition"),
            match.group("region"),
            match.group("account"),
        )
        expected = (self.partition, self.region, self.account_id)
        if observed != expected:
            raise ConfigurationResolutionError(
                code=ResolutionCode.RESOURCE_SCOPE,
                logical_name="catalog-entry",
                source=source,
                resource_fingerprint=_fingerprint(resource_arn),
                retryable=False,
                provider_code="ScopeMismatch",
            )


@dataclass(frozen=True, slots=True)
class SettingSpec:
    """One catalog entry with an explicit source, selector, and cache policy."""

    logical_name: str
    classification: SettingClassification
    source: SettingSource
    resource_arn: str
    cache_ttl_seconds: int
    parameter_version: int | None = None
    parameter_label: str | None = None
    secret_version_id: str | None = None
    secret_version_stage: str | None = None

    def __post_init__(self) -> None:
        if _LOGICAL_NAME.fullmatch(self.logical_name) is None:
            raise ValueError("logical_name requires a stable lower-case identifier")
        expected = (
            SettingClassification.CONFIGURATION
            if self.source is SettingSource.PARAMETER_STORE
            else SettingClassification.SECRET
        )
        if self.classification is not expected:
            raise ValueError(f"{self.source.value} requires {expected.value} classification")
        if self.parameter_version is not None and self.parameter_version < 1:
            raise ValueError("parameter_version requires a positive integer")
        if self.parameter_version is not None and self.parameter_label is not None:
            raise ValueError("a Parameter Store selector uses a version or a label")
        if (
            self.parameter_label is not None
            and _PARAMETER_LABEL.fullmatch(self.parameter_label) is None
        ):
            raise ValueError("parameter_label requires 1..100 AWS label characters")
        if (
            self.secret_version_id is not None
            and _SECRET_VERSION_ID.fullmatch(self.secret_version_id) is None
        ):
            raise ValueError("secret_version_id requires 32..64 AWS version characters")
        if (
            self.secret_version_stage is not None
            and _SECRET_VERSION_STAGE.fullmatch(self.secret_version_stage) is None
        ):
            raise ValueError("secret_version_stage requires 1..256 AWS stage characters")
        if self.source is SettingSource.PARAMETER_STORE and (
            self.secret_version_id is not None
            or self.secret_version_stage is not None
        ):
            raise ValueError("Parameter Store entries use parameter selectors")
        if self.source is SettingSource.SECRETS_MANAGER and (
            self.parameter_version is not None or self.parameter_label is not None
        ):
            raise ValueError("Secrets Manager entries use secret selectors")
        maximum_ttl = (
            900 if self.source is SettingSource.SECRETS_MANAGER else 3600
        )
        if not 0 <= self.cache_ttl_seconds <= maximum_ttl:
            raise ValueError(
                f"{self.source.value} cache TTL requires 0..{maximum_ttl} seconds"
            )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> SettingSpec:
        return cls(
            logical_name=str(value["logical_name"]),
            classification=SettingClassification(str(value["classification"])),
            source=SettingSource(str(value["source"])),
            resource_arn=str(value["resource_arn"]),
            cache_ttl_seconds=int(value["cache_ttl_seconds"]),
            parameter_version=_optional_int(value.get("parameter_version")),
            parameter_label=_optional_text(value.get("parameter_label")),
            secret_version_id=_optional_text(value.get("secret_version_id")),
            secret_version_stage=_optional_text(value.get("secret_version_stage")),
        )

    def cache_key(self) -> tuple[str, ...]:
        return (
            self.logical_name,
            self.resource_arn,
            str(self.parameter_version or ""),
            self.parameter_label or "",
            self.secret_version_id or "",
            self.secret_version_stage or "",
        )


@dataclass(frozen=True, slots=True)
class RuntimeSettingCatalog:
    """Validated collection of runtime setting specifications."""

    schema_version: str
    scope: AwsResourceScope
    settings: Mapping[str, SettingSpec]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> RuntimeSettingCatalog:
        if value.get("schema_version") != "1.0.0":
            raise ValueError("schema_version requires the released 1.0.0 catalog")
        scope_value = _mapping(value.get("aws_scope"), field_name="aws_scope")
        scope = AwsResourceScope(
            partition=str(scope_value["partition"]),
            region=str(scope_value["region"]),
            account_id=str(scope_value["account_id"]),
        )
        entries = value.get("settings")
        if not isinstance(entries, list) or not entries:
            raise ValueError("settings requires a populated list")
        specs = tuple(SettingSpec.from_mapping(_mapping(item, field_name="setting")) for item in entries)
        by_name = {spec.logical_name: spec for spec in specs}
        if len(by_name) != len(specs):
            raise ValueError("logical_name values require catalog-wide uniqueness")
        for spec in specs:
            scope.validate(resource_arn=spec.resource_arn, source=spec.source)
        return cls(
            schema_version=str(value["schema_version"]),
            scope=scope,
            settings=by_name,
        )

    def require(self, logical_name: str) -> SettingSpec:
        try:
            return self.settings[logical_name]
        except KeyError as cause:
            raise ConfigurationResolutionError(
                code=ResolutionCode.MISSING,
                logical_name=logical_name,
                source=SettingSource.PARAMETER_STORE,
                resource_fingerprint="catalog",
                retryable=False,
                provider_code="UnknownLogicalName",
            ) from None


class ParameterStoreClient(Protocol):
    def get_parameter(self, **kwargs: Any) -> Mapping[str, Any]: ...


class SecretsManagerClient(Protocol):
    def get_secret_value(self, **kwargs: Any) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True, repr=False)
class ResolvedSetting:
    """Runtime value whose ordinary representation remains value-free."""

    logical_name: str
    source: SettingSource
    version: str
    fetched_at_monotonic: float
    _value: str = field(repr=False)

    def reveal(self) -> str:
        """Return the value to the narrow integration boundary that consumes it."""

        return self._value

    def safe_fields(self) -> dict[str, str]:
        return {
            "logical_name": self.logical_name,
            "source": self.source.value,
            "version": self.version,
            "value": "[REDACTED]",
        }

    def __repr__(self) -> str:
        return (
            "ResolvedSetting("
            f"logical_name={self.logical_name!r}, "
            f"source={self.source.value!r}, "
            f"version={self.version!r}, "
            "value='[REDACTED]')"
        )


class ConfigurationResolutionError(RuntimeError):
    """Structured provider failure whose public surface excludes provider messages."""

    def __init__(
        self,
        *,
        code: ResolutionCode,
        logical_name: str,
        source: SettingSource,
        resource_fingerprint: str,
        retryable: bool,
        provider_code: str,
    ) -> None:
        self.code = code
        self.logical_name = logical_name
        self.source = source
        self.resource_fingerprint = resource_fingerprint
        self.retryable = retryable
        self.provider_code = provider_code
        super().__init__(
            f"runtime setting {logical_name!r} requires {code.value} handling; "
            f"source={source.value}; resource={resource_fingerprint}; "
            f"retryable={str(retryable).lower()}; provider_code={provider_code}"
        )

    def safe_fields(self) -> dict[str, str | bool]:
        return {
            "event": "runtime_setting_resolution",
            "code": self.code.value,
            "logical_name": self.logical_name,
            "source": self.source.value,
            "resource_fingerprint": self.resource_fingerprint,
            "retryable": self.retryable,
            "provider_code": self.provider_code,
        }


@dataclass(slots=True)
class _CacheEntry:
    resolved: ResolvedSetting
    expires_at: float


class RuntimeConfigurationResolver:
    """Resolve AWS-backed settings through a bounded, fail-closed memory cache."""

    def __init__(
        self,
        *,
        scope: AwsResourceScope,
        parameter_store: ParameterStoreClient,
        secrets_manager: SecretsManagerClient,
        monotonic: Callable[[], float] = time.monotonic,
        max_cache_entries: int = 128,
    ) -> None:
        if max_cache_entries < 1:
            raise ValueError("max_cache_entries requires a positive bound")
        self._scope = scope
        self._parameter_store = parameter_store
        self._secrets_manager = secrets_manager
        self._monotonic = monotonic
        self._max_cache_entries = max_cache_entries
        self._cache: OrderedDict[tuple[str, ...], _CacheEntry] = OrderedDict()
        self._lock = RLock()

    def resolve(
        self, spec: SettingSpec, *, force_refresh: bool = False
    ) -> ResolvedSetting:
        self._scope.validate(resource_arn=spec.resource_arn, source=spec.source)
        key = spec.cache_key()
        now = self._monotonic()
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and not force_refresh and now < cached.expires_at:
                self._cache.move_to_end(key)
                return cached.resolved
            self._cache.pop(key, None)

        resolved = self._retrieve(spec, now=now)
        if spec.cache_ttl_seconds > 0:
            with self._lock:
                self._cache[key] = _CacheEntry(
                    resolved=resolved,
                    expires_at=now + spec.cache_ttl_seconds,
                )
                self._cache.move_to_end(key)
                while len(self._cache) > self._max_cache_entries:
                    self._cache.popitem(last=False)
        return resolved

    def resolve_json_member(
        self,
        spec: SettingSpec,
        *,
        member: str,
        force_refresh: bool = False,
    ) -> ResolvedSetting:
        resolved = self.resolve(spec, force_refresh=force_refresh)
        try:
            document = json.loads(
                resolved.reveal(),
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
            value = document[member]
            if not isinstance(value, str) or not value:
                raise TypeError("member requires a populated string")
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as cause:
            raise ConfigurationResolutionError(
                code=ResolutionCode.PAYLOAD,
                logical_name=spec.logical_name,
                source=spec.source,
                resource_fingerprint=_fingerprint(spec.resource_arn),
                retryable=False,
                provider_code=type(cause).__name__,
            ) from None
        return ResolvedSetting(
            logical_name=f"{spec.logical_name}.{member}",
            source=resolved.source,
            version=resolved.version,
            fetched_at_monotonic=resolved.fetched_at_monotonic,
            _value=value,
        )

    def invalidate(self, logical_name: str | None = None) -> int:
        with self._lock:
            if logical_name is None:
                removed = len(self._cache)
                self._cache.clear()
                return removed
            keys = [key for key in self._cache if key[0] == logical_name]
            for key in keys:
                self._cache.pop(key, None)
            return len(keys)

    def _retrieve(self, spec: SettingSpec, *, now: float) -> ResolvedSetting:
        try:
            if spec.source is SettingSource.PARAMETER_STORE:
                return self._retrieve_parameter(spec, now=now)
            return self._retrieve_secret(spec, now=now)
        except ConfigurationResolutionError:
            raise
        except Exception as cause:
            provider_code = _provider_error_code(cause)
            code, retryable = _classify_provider_error(provider_code)
            raise ConfigurationResolutionError(
                code=code,
                logical_name=spec.logical_name,
                source=spec.source,
                resource_fingerprint=_fingerprint(spec.resource_arn),
                retryable=retryable,
                provider_code=provider_code,
            ) from None

    def _retrieve_parameter(
        self, spec: SettingSpec, *, now: float
    ) -> ResolvedSetting:
        response = self._parameter_store.get_parameter(
            Name=_parameter_reference(spec),
            WithDecryption=False,
        )
        parameter = _mapping(response.get("Parameter"), field_name="Parameter")
        observed_name = parameter.get("Name")
        expected_names = {
            spec.resource_arn,
            "/" + spec.resource_arn.split(":parameter/", 1)[1],
        }
        if observed_name not in expected_names:
            raise ConfigurationResolutionError(
                code=ResolutionCode.RESOURCE_SCOPE,
                logical_name=spec.logical_name,
                source=spec.source,
                resource_fingerprint=_fingerprint(spec.resource_arn),
                retryable=False,
                provider_code="ParameterIdentityMismatch",
            )
        if parameter.get("Type") != "String":
            raise ConfigurationResolutionError(
                code=ResolutionCode.CLASSIFICATION,
                logical_name=spec.logical_name,
                source=spec.source,
                resource_fingerprint=_fingerprint(spec.resource_arn),
                retryable=False,
                provider_code="SecureStringRequiresSecretCatalog",
            )
        value = parameter.get("Value")
        version = parameter.get("Version")
        if not isinstance(value, str) or not value or not isinstance(version, int):
            raise ConfigurationResolutionError(
                code=ResolutionCode.PAYLOAD,
                logical_name=spec.logical_name,
                source=spec.source,
                resource_fingerprint=_fingerprint(spec.resource_arn),
                retryable=False,
                provider_code="InvalidParameterPayload",
            )
        if spec.parameter_version is not None and version != spec.parameter_version:
            raise ConfigurationResolutionError(
                code=ResolutionCode.PAYLOAD,
                logical_name=spec.logical_name,
                source=spec.source,
                resource_fingerprint=_fingerprint(spec.resource_arn),
                retryable=False,
                provider_code="ParameterVersionMismatch",
            )
        if (
            spec.parameter_version is not None
            or spec.parameter_label is not None
        ) and parameter.get("Selector") != _parameter_reference(spec):
            raise ConfigurationResolutionError(
                code=ResolutionCode.PAYLOAD,
                logical_name=spec.logical_name,
                source=spec.source,
                resource_fingerprint=_fingerprint(spec.resource_arn),
                retryable=False,
                provider_code="ParameterSelectorMismatch",
            )
        return ResolvedSetting(
            logical_name=spec.logical_name,
            source=spec.source,
            version=str(version),
            fetched_at_monotonic=now,
            _value=value,
        )

    def _retrieve_secret(self, spec: SettingSpec, *, now: float) -> ResolvedSetting:
        request: dict[str, str] = {"SecretId": spec.resource_arn}
        if spec.secret_version_id is not None:
            request["VersionId"] = spec.secret_version_id
        if spec.secret_version_stage is not None:
            request["VersionStage"] = spec.secret_version_stage
        response = self._secrets_manager.get_secret_value(**request)
        if response.get("ARN") != spec.resource_arn:
            raise ConfigurationResolutionError(
                code=ResolutionCode.RESOURCE_SCOPE,
                logical_name=spec.logical_name,
                source=spec.source,
                resource_fingerprint=_fingerprint(spec.resource_arn),
                retryable=False,
                provider_code="SecretIdentityMismatch",
            )
        value = response.get("SecretString")
        version = response.get("VersionId")
        if not isinstance(value, str) or not value or not isinstance(version, str):
            raise ConfigurationResolutionError(
                code=ResolutionCode.PAYLOAD,
                logical_name=spec.logical_name,
                source=spec.source,
                resource_fingerprint=_fingerprint(spec.resource_arn),
                retryable=False,
                provider_code="SecretStringRequired",
            )
        if spec.secret_version_id is not None and version != spec.secret_version_id:
            raise ConfigurationResolutionError(
                code=ResolutionCode.PAYLOAD,
                logical_name=spec.logical_name,
                source=spec.source,
                resource_fingerprint=_fingerprint(spec.resource_arn),
                retryable=False,
                provider_code="SecretVersionMismatch",
            )
        stages = response.get("VersionStages")
        expected_stage = spec.secret_version_stage or "AWSCURRENT"
        if (
            not isinstance(stages, list)
            or not all(isinstance(stage, str) for stage in stages)
            or expected_stage not in stages
        ):
            raise ConfigurationResolutionError(
                code=ResolutionCode.PAYLOAD,
                logical_name=spec.logical_name,
                source=spec.source,
                resource_fingerprint=_fingerprint(spec.resource_arn),
                retryable=False,
                provider_code="SecretStageMismatch",
            )
        return ResolvedSetting(
            logical_name=spec.logical_name,
            source=spec.source,
            version=version,
            fetched_at_monotonic=now,
            _value=value,
        )


class RuntimeValueRedactionFilter(logging.Filter):
    """Replace registered runtime values before a log record reaches a handler."""

    def __init__(self, *, capacity: int = 128) -> None:
        super().__init__()
        if capacity < 1:
            raise ValueError("capacity requires a positive bound")
        self._capacity = capacity
        self._values: OrderedDict[str, None] = OrderedDict()
        self._lock = RLock()

    def register(self, resolved: ResolvedSetting) -> None:
        value = resolved.reveal()
        with self._lock:
            self._values[value] = None
            self._values.move_to_end(value)
            while len(self._values) > self._capacity:
                self._values.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._values.clear()

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redact(record.msg)
        record.args = self._redact(record.args)
        if record.exc_text is not None:
            record.exc_text = self._redact(record.exc_text)
        if record.stack_info is not None:
            record.stack_info = self._redact(record.stack_info)
        if record.exc_info is not None:
            _, exception, _ = record.exc_info
            safe_message = self._redact(str(exception))
            safe_exception = RuntimeError(
                f"{type(exception).__name__}: {safe_message}"
            )
            record.exc_info = (RuntimeError, safe_exception, None)
        standard = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "taskName",
        }
        for key, value in tuple(record.__dict__.items()):
            if key not in standard:
                record.__dict__[key] = self._redact(value)
        return True

    def _redact(self, value: Any) -> Any:
        if isinstance(value, str):
            with self._lock:
                protected = tuple(self._values)
            output = value
            for candidate in protected:
                output = output.replace(candidate, "[REDACTED]")
            return output
        if isinstance(value, Mapping):
            return {key: self._redact(item) for key, item in value.items()}
        if isinstance(value, tuple):
            return tuple(self._redact(item) for item in value)
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        return value


def _mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} requires an object")
    return value


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _optional_text(value: Any) -> str | None:
    return None if value is None else str(value)


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError("secret JSON members require one definition")
        output[key] = value
    return output


def _reject_json_constant(_: str) -> None:
    raise ValueError("secret JSON values require finite JSON representations")


def _parameter_reference(spec: SettingSpec) -> str:
    if spec.parameter_version is not None:
        return f"{spec.resource_arn}:{spec.parameter_version}"
    if spec.parameter_label is not None:
        return f"{spec.resource_arn}:{spec.parameter_label}"
    return spec.resource_arn


def _fingerprint(resource_arn: str) -> str:
    return "sha256:" + sha256(resource_arn.encode("utf-8")).hexdigest()[:16]


def _provider_error_code(cause: Exception) -> str:
    response = getattr(cause, "response", None)
    if isinstance(response, Mapping):
        error = response.get("Error")
        if isinstance(error, Mapping):
            code = error.get("Code")
            if isinstance(code, str) and code:
                return re.sub(r"[^A-Za-z0-9_.-]", "", code)[:80] or "ProviderError"
    return type(cause).__name__[:80]


def _classify_provider_error(provider_code: str) -> tuple[ResolutionCode, bool]:
    if provider_code in {
        "AccessDenied",
        "AccessDeniedException",
        "DecryptionFailure",
        "InvalidKeyId",
    }:
        return ResolutionCode.ACCESS, False
    if provider_code in {
        "ParameterNotFound",
        "ResourceNotFoundException",
    }:
        return ResolutionCode.MISSING, False
    if provider_code in {
        "Throttling",
        "ThrottlingException",
        "TooManyUpdates",
    }:
        return ResolutionCode.THROTTLED, True
    return ResolutionCode.PROVIDER, True
