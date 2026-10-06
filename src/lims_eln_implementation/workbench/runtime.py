"""Local workbench composition with explicit state and file-delivered credentials."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hmac
import os
from pathlib import Path
import re
import secrets
import stat
import time

from fastapi import FastAPI

from ..security import (
    SignedTenantContext,
    TenantContextProvider,
    TenantSessionBindingError,
    tenant_context_signing_message,
)
from .api import create_app
from .postgres import PostgresWorkbenchService
from .shared_contracts import contract_available

TENANT_ID = "SYN-TENANT-A"
CALLER_ID = "svc-golden-specimen-workbench"
ADAPTERS = ("process_local", "postgresql")
_HOST = re.compile(r"[A-Za-z0-9_.:-]{1,253}")
_DATABASE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,62}")
_KEY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_PORT = re.compile(r"[0-9]{1,5}")
_KEY_HEX = re.compile(r"[a-f0-9]{64}")


class RuntimeConfigurationError(ValueError):
    """Local entry requires a complete, value-free configuration decision."""


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    """A snapshot of public connection fields and local secret-file references."""

    adapter: str
    host: str = "127.0.0.1"
    port: int = 5432
    database: str = "laboratory"
    password_file: Path | None = None
    tenant_key_file: Path | None = None
    tenant_key_id: str = "local-compose-v1"


def settings_from_environment(environment: Mapping[str, str]) -> RuntimeSettings:
    """Read only declared fields; validate bounded text before numeric conversion."""
    adapter = environment.get("LIMS_WORKBENCH_ADAPTER", "process_local")
    if adapter not in ADAPTERS:
        raise RuntimeConfigurationError(
            "LIMS_WORKBENCH_ADAPTER requires process_local or postgresql"
        )
    if adapter == "process_local":
        return RuntimeSettings(adapter=adapter)

    host = environment.get("LIMS_WORKBENCH_DB_HOST", "127.0.0.1")
    database = environment.get("LIMS_WORKBENCH_DB_NAME", "laboratory")
    port_text = environment.get("LIMS_WORKBENCH_DB_PORT", "5432")
    key_id = environment.get("LIMS_WORKBENCH_TENANT_KEY_ID", "local-compose-v1")
    for name, value, grammar in (
        ("LIMS_WORKBENCH_DB_HOST", host, _HOST),
        ("LIMS_WORKBENCH_DB_NAME", database, _DATABASE),
        ("LIMS_WORKBENCH_TENANT_KEY_ID", key_id, _KEY_ID),
    ):
        if grammar.fullmatch(value) is None:
            raise RuntimeConfigurationError(f"{name} requires its bounded identifier form")
    if _PORT.fullmatch(port_text) is None or not 1 <= int(port_text) <= 65535:
        raise RuntimeConfigurationError("LIMS_WORKBENCH_DB_PORT requires an integer from 1 to 65535")
    paths = []
    for name in ("LIMS_WORKBENCH_DB_PASSWORD_FILE", "LIMS_WORKBENCH_TENANT_KEY_FILE"):
        value = environment.get(name, "")
        if not value.strip() or len(value) > 4096 or "\0" in value:
            raise RuntimeConfigurationError(f"{name} requires a local file path")
        paths.append(Path(value))
    return RuntimeSettings(adapter, host, int(port_text), database, *paths, key_id)


def _read_secret(path: Path, setting: str) -> str:
    """Read at most 1025 bytes from a regular file; diagnostics retain the setting name."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise RuntimeConfigurationError(f"{setting} requires a regular local file")
            raw = source.read(1025)
    except OSError:
        raise RuntimeConfigurationError(f"{setting} requires a readable regular local file") from None
    if len(raw) > 1024:
        raise RuntimeConfigurationError(f"{setting} supports at most 1024 file bytes")
    value = raw.rstrip(b"\r\n")
    if not value or any(byte < 32 or byte > 126 for byte in value):
        raise RuntimeConfigurationError(f"{setting} requires printable ASCII secret material")
    return value.decode("ascii")


def local_tenant_issuer(key_hex: str, key_id: str) -> TenantContextProvider:
    """Issue one-tenant assertions for the local reference profile.

    The local issuer holds key material; the service receives only signed
    assertions. A remote identity provider retains its own deployment boundary.
    """
    if _KEY_HEX.fullmatch(key_hex) is None:
        raise RuntimeConfigurationError("LIMS_WORKBENCH_TENANT_KEY_FILE requires 64 lowercase hex digits")
    if _KEY_ID.fullmatch(key_id) is None:
        raise RuntimeConfigurationError("LIMS_WORKBENCH_TENANT_KEY_ID requires its bounded identifier form")
    key = bytes.fromhex(key_hex)

    def issue(tenant_id: str) -> SignedTenantContext:
        if tenant_id != TENANT_ID:
            raise TenantSessionBindingError("local issuer requires the configured workbench tenant")
        issued_at = int(time.time())
        fields = {
            "tenant_id": tenant_id,
            "subject_id": CALLER_ID,
            "key_id": key_id,
            "issued_at_epoch": issued_at,
            "expires_at_epoch": issued_at + 60,
            "nonce": secrets.token_urlsafe(24),
        }
        signature = hmac.digest(key, tenant_context_signing_message(**fields), "sha256").hex()
        return SignedTenantContext(**fields, signature_hex=signature)

    return issue


def create_configured_app() -> FastAPI:
    """Resolve one process-owned composition; each database operation owns its connection."""
    settings = settings_from_environment(os.environ)
    if settings.adapter == "process_local":
        return create_app()
    if not contract_available():
        raise RuntimeConfigurationError("PostgreSQL entry requires the reviewed contracts extra")
    try:
        import psycopg
    except ImportError:
        raise RuntimeConfigurationError("PostgreSQL entry requires the postgres extra") from None
    assert settings.password_file is not None and settings.tenant_key_file is not None
    password = _read_secret(settings.password_file, "LIMS_WORKBENCH_DB_PASSWORD_FILE")
    key_hex = _read_secret(settings.tenant_key_file, "LIMS_WORKBENCH_TENANT_KEY_FILE")
    issuer = local_tenant_issuer(key_hex, settings.tenant_key_id)

    def connect():
        return psycopg.connect(
            host=settings.host,
            port=settings.port,
            dbname=settings.database,
            user="laboratory_app",
            password=password,
            connect_timeout=5,
            application_name="local-golden-specimen-workbench",
            options="-c statement_timeout=10000 -c lock_timeout=3000",
        )

    return create_app(
        PostgresWorkbenchService(connect, tenant_context_provider=issuer)
    )
