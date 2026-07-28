# Implementation architecture

## Architectural center

The canonical laboratory model owns scientific identity, revision, lifecycle,
lineage, custody, raw-artifact integrity, review, and release meaning. Vendor
objects are projections through versioned ports. This keeps a configured vendor
valuable while preserving an intelligible data-exit path.

```text
instrument bytes ──> durable inbox ──> canonical domain ──> scientific review
                          │                    │                    │
                          ▼                    ▼                    ▼
                    quarantine         transactional outbox   release decision
                                               │
                                  ┌────────────┼────────────┐
                                  ▼            ▼            ▼
                                Sapio      Benchling      LabKey
                                  └────────────┼────────────┘
                                               ▼
                                     authoritative readback
```

## Invariants

1. Tenant identity participates in every persistence and integration key.
2. A command binds one stable identity to one canonical content digest.
3. Exact replay returns the recorded outcome.
4. Changed content receives a new command identity or a reviewable collision.
5. Aggregate revisions serialize concurrent lifecycle and custody plans.
6. Instrument bytes retain their original SHA-256 digest through normalization.
7. External timeout ambiguity resolves through authoritative readback before
   another write is eligible.
8. Migration parity covers identity, revision, payload, relationships, audit,
   and artifact bytes.
9. Operational rates retain their good-event numerator and valid-event denominator.
10. Scientific, Quality, and Regulatory acceptance remain separate decisions.

## Transaction boundaries

The production persistence adapter places aggregate mutation, append-only domain
event, idempotency commit, and outbox message in one database transaction.
External delivery begins after commit. A worker claims outbox rows with bounded
leases, records each attempt, and moves exhausted work to a reviewable recovery
queue with its source identity intact.

Instrument ingress stores bytes in versioned object storage before parsing.
Database metadata binds the object key and checksum to the inbox identity.
Scientific normalization creates a new canonical digest while preserving the
raw digest.

## Vendor boundaries

Every adapter implements the same port:

- write from an expected external revision;
- return confirmed or ambiguous certainty;
- read current state by stable external identity;
- expose environment, SDK, schema, permission, and configuration versions in
  its receipt.

Sapio, Benchling, and LabKey retain separate conformance profiles because their
events, validation, revision, and permission semantics differ. The shared port
captures laboratory intent; the configured-environment suite proves each mapping.

## Evidence boundary

Application code emits redacted operational facts. A receipt assembler binds
those facts to repository commit, environment, schema, configuration, fixture,
scenario, performer, reviewer, date, artifact digest, and limitations.

Observed evidence advances an assurance stage only after its named gate passes.
Simulated evidence remains useful for forecasting and comparative literacy while
its `evidence_mode` keeps authority legible.

