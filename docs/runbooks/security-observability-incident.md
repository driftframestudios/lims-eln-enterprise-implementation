# Security and observability incident

1. Open the organization's incident process and record the affected service,
   tenant scope, time window, and data classes.
2. Preserve relevant OpenTelemetry traces, metrics, logs, CloudTrail events,
   database logs, and vendor request identifiers.
3. Rotate affected Secrets Manager versions and workload credentials through
   established platform procedures.
4. Restrict affected integration traffic while preserving recoverable source
   and outbox data.
5. Compare canonical domain state with vendor readback and broker offsets.
6. Reconcile ambiguous writes by stable request and external identity.
7. Restore service through the deployment platform and observe SLO indicators.
8. Retain the incident timeline and corrective work in the organization's
   incident and change systems.

Telemetry uses allowlisted fields and the repository's redactor. Protected
payloads remain in approved operational stores.
