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

The database begins from versioned migration V001 and advances through Flyway
Community 13.0.0. Flyway owns discovery, ordering, locking, one PostgreSQL
transaction per migration, applied history, checksum validation, status, and
no-op replay. `database/flyway-release.json` pins the open-source image by exact
version and digest; `flyway.conf` keeps validation enabled, order strict, clean
disabled, and automatic baseline adoption disabled. A failed migration rolls
back. An applied migration receives a successor forward repair. Cluster-wide
role provisioning remains a separate privileged deployment step. The Flyway
runtime authenticates as `laboratory_migrator`, whose role attributes are
`LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS`. A
digest-bound `afterConnect.sql` callback verifies that session identity and
the effective identity. Privileged provisioning installs a target-database
startup setting that selects the no-login `laboratory_owner` through its `SET
TRUE, INHERIT FALSE, ADMIN FALSE` membership on every new connection. Database
and schema ownership live on that owner role; the authenticated login
receives connection authority and a distinct runtime credential. The callback
also verifies the exact catalog binding, while `RESET ROLE` exposes the
configured owner default and `SET ROLE NONE` exposes the migrator's
direct-DDL-rejecting privilege set. The credential can deliberately select the
owner through its released membership and therefore enters only the migration
workload boundary.

V004 moves outbox state relations and trusted transition routines to the
isolated `laboratory_outbox_authority`. The schema owner receives a single
`ADMIN FALSE, INHERIT FALSE, SET TRUE` membership so it can perform PostgreSQL's
required ownership transfer. Both roles remain `NOLOGIN NOBYPASSRLS`, and
`INHERIT FALSE` keeps the transfer capability distinct from ambient runtime
authority. V004 settles caller access controls and triggers under the migration
owner, then transfers ownership while the destination role has its bounded
schema capability. The destination role clears ownership-transferred outbox
privileges, then establishes the narrow DML used by its routines and guards,
including `UPDATE` on attempt and outcome so append-only triggers govern
attempted mutation and PostgreSQL can lock an outcome while validating the
recovery foreign key. It restores the custody producer's column-level insert
grant before the migration owner revokes that capability. Static and hosted
catalog proofs verify the ordering, exact role edge, final table and routine
owners, bounded DML surface, and absence of schema-creation privilege on clean
and successor paths.

Forced row-level security remains active during migration. Every tenant table
has a second permissive policy scoped to `laboratory_owner` whose predicate
verifies the complete catalog-backed migration session coordinate. The ordinary
tenant predicate becomes SQL `NULL` only for that exact coordinate, avoiding an
exception during cross-tenant maintenance. Application, worker, evidence,
trusted `SECURITY DEFINER`, and direct migrator paths continue to require a
signed tenant context. This keeps cross-tenant data evolution explicit while
the migration secret, digest-bound SQL, and deployment stage form its authority
boundary.

Migration V002 establishes finite temporal values, state coherence, the signed
tenant authority, typed instrument measurements, custody history/CAS, and
immutable outbox content. Migration V003 fixes privileged routine name resolution,
removes direct worker delivery mutation, and introduces fenced outbox lease
functions plus transition guards. Migration V004 retains that released history
and narrows the current API to 1 through 900 integer seconds. A dedicated
no-login authority enforces the complete transition matrix; append-only tenant
relations preserve each attempt, outcome, transport receipt, and recovery
release. The producer and worker share one database-enforced, nonblank
printable-ASCII message identity of at most 256 bytes. Migration V004 admits only
initial ready rows with zero attempts, so every accepted message begins durable
attempt provenance under the new model. It also binds measurement scale to the
stored numeric, binds complete inbox lineage, and binds each custody position to
one complete event coordinate. A deterministic transaction-scoped
`ACCESS EXCLUSIVE` lock set precedes the preflight; 30-second lock acquisition
and five-minute statement and idle-in-transaction budgets make contention a
clean, retryable rollback. Source precision remains producer-observed metadata
until retained source lexemes or canonical payload bytes support independent
verification. A populated untracked baseline enters
through a fresh-target restore and semantic comparison rehearsal rather than
object-name inference. The complete adoption and evidence gates are documented in
`docs/database-migrations.md`.

Migration V005 keeps `custody_event` and `instrument_measurement` as the single
durable facts. It binds inbox rows to specimens, records append-only instrument
review resolutions through signed tenant authority, and requires any accepted
replacement to carry the same specimen identity. Security-invoker views provide
the normalized-observation and workbench read shapes without duplicating
canonical scientific values.
