"""FastAPI delivery adapter for the Golden Specimen Workbench."""

from __future__ import annotations

from base64 import b64decode
from binascii import Error as Base64Error
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Protocol

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from ..bounded_caller import CallDenied
from ..idempotency import IdempotencyError, TransactionRetryRequired
from ..model import DomainError
from ..ports import VendorRevisionConflict
from ..vendors import AmbiguousOutcomePending
from .capabilities import describe_workbench, require_state_adapter
from .service import ObservationAbsent, SpecimenAbsent, WorkbenchService
from .shared_contracts import contract_available


_PACKAGE_ROOT = Path(__file__).resolve().parent
_IDENTITY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{1,126}[A-Za-z0-9]$"


class GoldenRunRequest(BaseModel):
    """One attributable, tenant-scoped synthetic journey."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=3, max_length=128, pattern=_IDENTITY_PATTERN)
    tenant_id: str = Field(min_length=3, max_length=128, pattern=_IDENTITY_PATTERN)
    specimen_id: str = Field(min_length=3, max_length=128, pattern=_IDENTITY_PATTERN)
    actor_id: str = Field(min_length=3, max_length=128, pattern=_IDENTITY_PATTERN)
    scientist_id: str = Field(min_length=3, max_length=128, pattern=_IDENTITY_PATTERN)
    quality_actor_id: str = Field(min_length=3, max_length=128, pattern=_IDENTITY_PATTERN)
    occurred_at: AwareDatetime
    raw_instrument_payload_base64: str = Field(min_length=4, max_length=1_400_000)
    vendor_payload: dict[str, Any] = Field(default_factory=dict)


class InstrumentRecoveryRequest(GoldenRunRequest):
    recovery_of_run_id: str = Field(
        min_length=3,
        max_length=128,
        pattern=_IDENTITY_PATTERN,
    )


class TenantContextMismatch(DomainError):
    """The authority context and requested resource belong to different tenants."""


class WorkbenchPort(Protocol):
    state_adapter: str

    def check_ready(self) -> None: ...

    def summary(self, tenant_id: str) -> dict[str, Any]: ...

    def specimen(self, tenant_id: str, specimen_id: str) -> dict[str, Any]: ...

    def observation(self, tenant_id: str, run_id: str) -> dict[str, Any]: ...

    def run_golden_specimen(self, **arguments: Any) -> dict[str, Any]: ...

    def resume_instrument_review(self, **arguments: Any) -> dict[str, Any]: ...


def create_app(service: WorkbenchPort | None = None) -> FastAPI:
    """Create an application with an injectable state composition root."""
    workbench = service or WorkbenchService()
    state_adapter = require_state_adapter(workbench.state_adapter)
    templates = Jinja2Templates(directory=str(_PACKAGE_ROOT / "templates"))
    app = FastAPI(
        title="LIMS/ELN Golden Specimen Workbench",
        summary="Inspectable specimen flow and evidence across system boundaries",
        version="0.3.2",
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.state.workbench = workbench
    app.mount(
        "/workbench/static",
        StaticFiles(directory=str(_PACKAGE_ROOT / "static")),
        name="workbench-static",
    )

    @app.middleware("http")
    async def response_boundaries(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'"
        )
        return response

    @app.exception_handler(SpecimenAbsent)
    async def specimen_absent(request: Request, error: SpecimenAbsent) -> JSONResponse:
        return _problem(request, 404, "specimen_absent", str(error.args[0]))

    @app.exception_handler(ObservationAbsent)
    async def observation_absent(
        request: Request, error: ObservationAbsent
    ) -> JSONResponse:
        return _problem(request, 404, "observation_absent", str(error.args[0]))

    @app.exception_handler(TenantContextMismatch)
    async def tenant_mismatch(
        request: Request, error: TenantContextMismatch
    ) -> JSONResponse:
        return _problem(request, 403, "tenant_context_mismatch", str(error))

    @app.exception_handler(CallDenied)
    async def call_denied(request: Request, error: CallDenied) -> JSONResponse:
        return _problem(request, 403, error.reason_code, str(error))

    @app.exception_handler(TransactionRetryRequired)
    async def transaction_retry(request: Request, error: TransactionRetryRequired) -> JSONResponse:
        return _problem(request, 409, "transaction_retry", str(error))

    for error_type in (
        DomainError,
        IdempotencyError,
        VendorRevisionConflict,
        AmbiguousOutcomePending,
    ):
        app.add_exception_handler(error_type, _domain_problem)

    @app.get("/health/live", include_in_schema=False)
    def liveness() -> dict[str, str]:
        return {"status": "live"}

    @app.get("/health/ready", include_in_schema=False)
    def readiness() -> JSONResponse:
        try:
            workbench.check_ready()
        except Exception:  # Adapter failures keep process liveness independently observable.
            return JSONResponse(
                status_code=503,
                content={
                    "status": "waiting_for_dependencies",
                    "state_adapter": workbench.state_adapter,
                },
                headers={"Cache-Control": "no-store"},
            )
        return JSONResponse(
            content={"status": "ready", "state_adapter": workbench.state_adapter},
            headers={"Cache-Control": "no-store"},
        )

    def capability_document() -> dict[str, Any]:
        return describe_workbench(state_adapter, package_compatible=contract_available())

    @app.get("/api/workbench/capabilities")
    def capabilities() -> JSONResponse:
        return JSONResponse(
            content=capability_document(),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/workbench", include_in_schema=False)
    def workbench_page(request: Request) -> Any:
        return templates.TemplateResponse(
            request=request,
            name="workbench.html",
            context={
                "default_tenant": "SYN-TENANT-A",
                "default_actor": "SYN-ACTOR-01",
                "default_scientist": "SYN-SCIENTIST-01",
                "default_quality_actor": "SYN-QUALITY-01",
                "capabilities": capability_document(),
            },
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/workbench/summary")
    def summary(
        tenant_id: Annotated[str, Query(min_length=3, max_length=128)],
        tenant_context: Annotated[str, Header(alias="X-Tenant-ID")],
    ) -> dict[str, Any]:
        _assert_tenant(tenant_context, tenant_id)
        return workbench.summary(tenant_id)

    @app.get("/api/workbench/specimens/{specimen_id}")
    def specimen(
        specimen_id: str,
        tenant_id: Annotated[str, Query(min_length=3, max_length=128)],
        tenant_context: Annotated[str, Header(alias="X-Tenant-ID")],
    ) -> dict[str, Any]:
        _assert_tenant(tenant_context, tenant_id)
        return workbench.specimen(tenant_id, specimen_id)

    @app.get("/api/workbench/observations/{run_id}")
    def observation(
        run_id: str,
        tenant_id: Annotated[str, Query(min_length=3, max_length=128)],
        tenant_context: Annotated[str, Header(alias="X-Tenant-ID")],
    ) -> dict[str, Any]:
        _assert_tenant(tenant_context, tenant_id)
        return workbench.observation(tenant_id, run_id)

    @app.post("/api/workbench/golden-runs", status_code=201)
    def run_golden_specimen(
        payload: GoldenRunRequest,
        tenant_context: Annotated[str, Header(alias="X-Tenant-ID")],
    ) -> dict[str, Any]:
        _assert_tenant(tenant_context, payload.tenant_id)
        raw_payload = _decode_raw_payload(payload.raw_instrument_payload_base64)
        return workbench.run_golden_specimen(
            run_id=payload.run_id,
            tenant_id=payload.tenant_id,
            specimen_id=payload.specimen_id,
            actor_id=payload.actor_id,
            scientist_id=payload.scientist_id,
            quality_actor_id=payload.quality_actor_id,
            occurred_at=_as_datetime(payload.occurred_at),
            raw_instrument_json=raw_payload,
            vendor_payload=payload.vendor_payload,
        )

    @app.post("/api/workbench/instrument-recovery-runs", status_code=201)
    def resume_instrument_review(
        payload: InstrumentRecoveryRequest,
        tenant_context: Annotated[str, Header(alias="X-Tenant-ID")],
    ) -> dict[str, Any]:
        _assert_tenant(tenant_context, payload.tenant_id)
        raw_payload = _decode_raw_payload(payload.raw_instrument_payload_base64)
        return workbench.resume_instrument_review(
            recovery_of_run_id=payload.recovery_of_run_id,
            run_id=payload.run_id,
            tenant_id=payload.tenant_id,
            specimen_id=payload.specimen_id,
            actor_id=payload.actor_id,
            scientist_id=payload.scientist_id,
            quality_actor_id=payload.quality_actor_id,
            occurred_at=_as_datetime(payload.occurred_at),
            raw_instrument_json=raw_payload,
            vendor_payload=payload.vendor_payload,
        )

    return app


async def _domain_problem(request: Request, error: Exception) -> JSONResponse:
    return _problem(request, 409, "domain_decision", str(error))


def _problem(
    request: Request,
    status: int,
    code: str,
    detail: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": f"urn:lims-eln:problem:{code}",
            "title": code.replace("_", " ").title(),
            "status": status,
            "detail": detail,
            "instance": str(request.url.path),
        },
    )


def _assert_tenant(context: str, requested: str) -> None:
    if context != requested:
        raise TenantContextMismatch(
            "tenant context and requested tenant require one exact identity"
        )


def _decode_raw_payload(value: str) -> bytes:
    try:
        raw_payload = b64decode(value, validate=True)
    except (Base64Error, ValueError) as error:
        raise DomainError(
            "raw instrument payload requires canonical base64 bytes"
        ) from error
    if len(raw_payload) > 1_000_000:
        raise DomainError(
            "raw instrument payload supports up to 1,000,000 bytes in this pilot"
        )
    return raw_payload


def _as_datetime(value: datetime) -> datetime:
    return value


app = create_app()
