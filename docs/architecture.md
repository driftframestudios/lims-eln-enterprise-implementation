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
13. A tenant assertion is short-lived, signed by a trusted issuer, and verified
    inside PostgreSQL before a row policy returns state.
14. Scientific quantities retain finite exact decimal value, source precision
    and scale, a released unit code/system, and raw-to-normalized lineage.
15. Applied schema migrations retain immutable identity, path, checksum, actor,
    database time, transaction ownership, and serialized runner coordination.
16. Privileged database routines resolve canonical relations and composite types
    by released schema, with temporary schemas last in the fixed search path.
17. Outbox delivery requires the signed tenant, invoking SQL principal,
    worker-instance label, rotating lease UUID, monotonic fence, and database time.

## Transaction boundaries

The production persistence contract places aggregate mutation, append-only
domain event, idempotency commit, and outbox message in one database transaction.
The in-memory atomic adapter proves rollback semantics for lifecycle plus
idempotency and custody plus outbox. PostgreSQL's `record_custody_transfer`
function locks the current position, enforces expected-version CAS, appends one
immutable custody event, updates the position, and inserts the full-payload
outbox message in one transaction. The schema supplies tenant-bound claim,
expired-lease reclaim, and exact confirmation functions. These functions record
the invoking SQL principal separately from the worker-instance label, rotate the
lease UUID, advance a monotonic fence, and compare the complete unexpired lease
coordinate before completion. The durable invocation and receipt adapters prove
their statements independently. The configured deployment still needs a
connection-scoped specimen-lifecycle composition and broker-facing worker that
routes exhausted work to reviewable recovery. Those configured-environment
receipts remain open.

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

Tenant-scoped tables use forced row-level security and
`laboratory_security.authorized_tenant_id()`. A trusted issuer supplies a
short-lived HMAC assertion containing tenant, subject, key identity, validity
window, and nonce. PostgreSQL verifies its exact field set, lifetime, active
private key, and signature before setting the transaction-local context. The
legacy caller-set tenant GUC has zero policy authority.

Application, outbox, evidence, and migration identities are distinct
`NOSUPERUSER NOBYPASSRLS` roles. They can execute verification and have zero
key-table access. A separately approved break-glass administration identity
belongs to the adopting environment and sits outside the ordinary repository
runtime.

## Database evolution boundary

The database begins from immutable migration 001 and advances through the
SHA-256-bound sequence in `database/migration-manifest.json`. The dependency-free
runner verifies all files, records applied identity/path/checksum/actor/time,
and uses a transaction-level advisory lock so concurrent runners converge on
one ordered result. A failed migration rolls back. An applied migration receives
a successor forward repair.

Migration 002 establishes finite temporal values, state coherence, the signed
tenant authority, typed instrument measurements, custody history/CAS, and
immutable outbox content. Migration 003 fixes privileged routine name resolution,
removes direct worker delivery mutation, and introduces fenced outbox lease
functions plus transition guards. Migration 004 retains that released history
and narrows the current API to 1 through 900 integer seconds. A dedicated
no-login authority enforces the complete transition matrix; append-only tenant
relations preserve each attempt, outcome, transport receipt, and recovery
release. The producer and worker share one database-enforced, nonblank
printable-ASCII message identity of at most 256 bytes. Migration 004 admits only
initial ready rows with zero attempts, so every accepted message begins durable
attempt provenance under the new model. A transaction-scoped `ACCESS EXCLUSIVE`
outbox lock precedes both provenance predicates; 30-second lock acquisition and
five-minute statement and idle-in-transaction budgets make contention a clean,
retryable rollback. A populated untracked baseline enters
through a fresh-target restore and semantic comparison rehearsal rather than
object-name inference. The complete adoption and evidence gates are documented in
`docs/database-migrations.md`.
