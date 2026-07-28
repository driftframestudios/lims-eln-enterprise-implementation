# Runbook — security and observability exercise

## Target state

Production-bound controls preserve tenant isolation, protected-data handling,
auditability, and actionable service visibility during ordinary and stressed
operation.

## Exercise

1. Establish approved synthetic canaries for protected-field discovery.
2. Exercise cross-tenant access, revoked identity, expired break-glass access,
   replayed events, and signature-role separation.
3. Rotate a workload credential and observe continued authorized operation.
4. Saturate an integration queue and observe backpressure, alerting, and recovery.
5. Interrupt telemetry export and observe bounded buffering and collector recovery.
6. Inject an application-level semantic failure that still returns transport success.
7. Confirm dashboards expose good-event numerator, valid-event denominator,
   window, target, and current value.
8. Route the incident to the secondary responder and exercise laboratory
   continuity while the primary responder is unavailable.
9. Search logs, traces, metrics, and receipts for synthetic canaries.
10. Replace discovered protected values, repair the emitting boundary, and
    repeat the exercise until the canary search is clear.

## Receipt

Capture control IDs, environment and configuration digests, actors, timestamps,
expected and observed signals, alert latency, recovery time, canary search,
deviations, owners, reviewer, and retest trigger.

