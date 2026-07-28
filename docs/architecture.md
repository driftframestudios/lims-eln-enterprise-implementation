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
11. Authority grants, approval scopes, budgets, request resources, and payloads
    retain immutable construction snapshots.
12. A write exception retains durable recovery ownership until authoritative
    reconciliation determines its material effect.

## Transaction boundaries

The production persistence contract places aggregate mutation, append-only
domain event, idempotency commit, and outbox message in one database transaction.
The in-memory atomic adapter proves rollback semantics for lifecycle plus
idempotency and custody plus outbox. The PostgreSQL schema supplies outbox
leases, fencing, and recovery state, while the durable invocation and receipt
adapters prove their statements independently. The configured deployment still
needs one connection-scoped composition and a worker that claims rows, records
attempts, and routes exhausted work to reviewable recovery. Those two
configured-environment receipts remain open.

The bounded-caller invocation row uses a lease token and monotonically governed
fencing token for every completion, pre-effect release, and recovery transition.
Exact completed content replays its stored output. Changed content receives a
collision. An expired lease and an ambiguous write exception move to
`recovery_required`, preserving the call identity for authoritative
reconciliation.

The production contract stores instrument bytes in versioned object storage
before parsing and binds object key and checksum to the inbox identity.
The current executable ingress is an in-memory conformance model; a durable
object-store/inbox adapter and its crash-point proof remain configured-
environment work. Scientific normalization creates a new canonical digest
while preserving the raw digest.

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

## Runtime configuration boundary

The deployed setting catalog separates non-sensitive configuration from
rotatable secrets:

```text
Terraform output ──> value-free catalog ──> account/Region scope gate
                                                │
                         ┌──────────────────────┴──────────────────────┐
                         ▼                                             ▼
              Parameter Store `String`                     Secrets Manager
              version or label selector                  version ID / stage
                         │                                             │
                         └──────────────────────┬──────────────────────┘
                                                ▼
                                  bounded process-memory cache
                                                │
                                                ▼
                                 narrow consuming integration
```

The workload role can read only the named parameters and secrets. KMS
decryption is constrained to the runtime key, Secrets Manager service path,
and named secret encryption contexts. Provider failures become value-free
structured events; resolved values retain redacted representations and can be
registered with the logging guard.

## Governance-plane database boundary

`evidence_receipt` and `acceptance_decision` are tenant-scoped governance-plane
records. They bind one intended use and release claim to independent reviewers
and accountable Scientific, Quality, and Regulatory decisions. The application
workload role receives zero direct write authority to these tables. A separate
evidence-writer role uses append-only tables and the minimum statement set
needed to record a receipt or decision.

Tenant-scoped tables use forced row-level security and a verified,
transaction-local `app.tenant_id` setting. Application, outbox, evidence, and
migration identities are distinct `NOSUPERUSER NOBYPASSRLS` roles. A separately
approved break-glass administration identity belongs to the adopting
environment and is intentionally absent from the ordinary repository runtime.
