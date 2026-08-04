# Runbook — ambiguous vendor write

## Trigger

The adapter loses transport certainty before receiving a definitive response.

## Target state

One stable request identity produces one external effect, and the system knows
the authoritative external revision before further mutation.

## Procedure

1. Retain the idempotency reservation and request digest.
2. Record vendor, environment, tenant, stable external identity, request ID,
   trace ID, source revision, and timing.
3. Read the authoritative record through a fresh client connection.
4. Compare canonical digest and revision.
5. When the digest matches, commit the local projection as
   `readback_confirmed`.
6. When the record is absent, keep the reservation pending and repeat readback
   within the approved reconciliation window.
7. When the digest diverges, quarantine the projection with both revisions and
   a redacted difference in the selected incident or work-management system.
8. Resume writes from the authoritative revision with a new request identity
   when changed content is intended.

## Evidence

Capture request digest, redacted payload shape, readback digest, revisions,
timings, retry count, trace IDs, and disposition in existing telemetry and
work-management systems.
