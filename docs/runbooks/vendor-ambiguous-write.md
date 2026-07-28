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
5. When the digest matches, commit the local projection receipt as
   `readback_confirmed`.
6. When the record is absent, keep the reservation pending and repeat readback
   within the approved reconciliation window.
7. When the digest diverges, quarantine the projection and route it to the
   integration owner with both revisions and a redacted difference.
8. Resume writes after the owner establishes the authoritative revision and
   chooses a new request identity where changed content is intended.

## Evidence

Capture request digest, redacted payload shape, readback digest, revisions,
timings, retry count, trace IDs, disposition, recovery owner, and reviewer.

