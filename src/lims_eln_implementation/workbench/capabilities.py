"""Bounded, detached composition records for the API and authored workbench.

The two adapters and five operations make construction O(1) in time and space.
The caller supplies package compatibility; this module performs no I/O.
"""

from typing import Any

from .shared_contracts import EXPECTED_CONTRACT_VERSION, EXPECTED_PACKAGE_VERSION


CONTRACT_ID = "urn:driftframe:lims-eln:workbench-capabilities:1.0.0"
_OPERATIONS = (
    ("summary", "GET", "/api/workbench/summary", "header_and_query"),
    ("specimen", "GET", "/api/workbench/specimens/{specimen_id}", "header_and_query"),
    ("observation", "GET", "/api/workbench/observations/{run_id}", "header_and_query"),
    ("golden_specimen", "POST", "/api/workbench/golden-runs", "header_and_body"),
    ("instrument_recovery", "POST", "/api/workbench/instrument-recovery-runs", "header_and_body"),
)


class CapabilityConfigurationError(ValueError):
    """The composition needs a supported adapter or explicit compatibility result."""


def require_state_adapter(value: str) -> str:
    """Admit the finite composition vocabulary without reflecting caller input."""
    if type(value) is not str or value not in ("process_local", "postgresql"):
        raise CapabilityConfigurationError(
            "Select process_local or postgresql for the workbench state adapter."
        )
    return value


def describe_workbench(state_adapter: str, *, package_compatible: bool) -> dict[str, Any]:
    """Project declared fields into fresh containers owned by this receiver."""
    adapter = require_state_adapter(state_adapter)
    if type(package_compatible) is not bool:
        raise CapabilityConfigurationError(
            "Supply an explicit Boolean package-version compatibility observation."
        )
    return {
        "contract_id": CONTRACT_ID,
        "runtime": {
            "state_adapter": adapter,
            "state_lifetime": "process" if adapter == "process_local" else "database",
            "access_scope": "local_reference",
        },
        "shared_contracts": {
            "expected_package_version": EXPECTED_PACKAGE_VERSION,
            "expected_contract_version": EXPECTED_CONTRACT_VERSION,
            "version_compatible": package_compatible,
        },
        "operations": {
            name: {"method": method, "path": path, "tenant_context": tenant_context}
            for name, method, path, tenant_context in _OPERATIONS
        },
        "administrative_interface": "python_library",
        "readiness_path": "/health/ready",
    }
