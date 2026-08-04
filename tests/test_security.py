from __future__ import annotations

import unittest

from lims_eln_implementation.security import (
    EvidenceRedactor,
    PostgresTenantScope,
    TenantSessionBindingError,
)


class FakeCursor:
    def __init__(self, observed: tuple[str] | None) -> None:
        self.observed = observed
        self.executions: list[tuple[str, tuple[str]]] = []

    def execute(self, operation: str, parameters: tuple[str]) -> None:
        self.executions.append((operation, parameters))

    def fetchone(self) -> tuple[str] | None:
        return self.observed


class SecurityTests(unittest.TestCase):
    def test_tenant_scope_uses_one_transaction_local_setting(self) -> None:
        cursor = FakeCursor(("SYN-TENANT-A",))
        PostgresTenantScope("SYN-TENANT-A").bind(cursor)
        self.assertEqual(
            cursor.executions,
            [
                (
                    "select set_config('app.tenant_id', %s, true)",
                    ("SYN-TENANT-A",),
                )
            ],
        )

    def test_tenant_scope_requires_database_confirmation(self) -> None:
        with self.assertRaises(TenantSessionBindingError):
            PostgresTenantScope("SYN-TENANT-A").bind(FakeCursor(None))

    def test_redactor_preserves_shape_and_replaces_protected_values(self) -> None:
        redactor = EvidenceRedactor({"tenant_id", "trace_id", "status", "details", "patient_name"})
        output = redactor.redact(
            {
                "tenant_id": "SYN-TENANT-A",
                "trace_id": "SYN-TRACE-01",
                "status": "quarantined",
                "patient_name": "Synthetic Person",
                "details": {
                    "token": "secret-value",
                    "reason": "unit_mapping",
                },
            }
        )
        self.assertEqual(output["tenant_id"], "SYN-TENANT-A")
        self.assertEqual(output["patient_name"], "[REDACTED]")
        self.assertEqual(output["details"]["token"], "[REDACTED]")
        self.assertEqual(output["details"]["reason"], "[REDACTED]")


if __name__ == "__main__":
    unittest.main()
