# LIMS/ELN Enterprise Implementation

This repository is the **actual-implementation member** of the comparative
Site Reading constellation. It provides a principal-level Python reference
system for specimen lifecycle, custody, instrument ingress, vendor projection,
migration, recovery, evidence, security, and operational acceptance.

The repository begins from the public architectural provenance of
`driftframestudios/prototype-exemplars` pull request
[#3](https://github.com/driftframestudios/prototype-exemplars/pull/3):

- source head: `8be1e2c2ce239e51dcd5d1e19d1ff52e9d080b72`;
- merged result: `613f524821a25389748a9cd98d1bb0d303de87cf`;
- source validation floor: 69 synthetic tests on Python 3.12 and 3.13.

This implementation is independently evolved. Runtime code stays within this
repository and consumes versioned contracts rather than simulation code.

## What runs

The standard-library test suite exercises:

- a typed bounded caller with task-scoped identity, tenant, capability,
  resource, request-budget, exact-approval, and replay boundaries;
- registered read, idempotent narrow-write, approval-gated broad-write, and
  bounded golden-journey operations whose services retain effect control;
- durable PostgreSQL receipt persistence and version-banded vendor SDK seams;
- Flyway Community migration ordering, locking, transactions, history,
  validation, status, target selection, and no-op replay;
- database-verified, short-lived signed tenant assertions for every row policy;
- tenant-bound, attributable, revision-checked specimen transitions;
- exact replay and changed-content collision handling;
- custody compare-and-set transfer with append-only history, a schema-qualified
  privileged routine, and an atomic full-payload outbox;
- tenant-bound outbox claim, expired-lease reclaim, and exact confirmation with
  database-principal attribution, rotating UUIDs, monotonic fencing, and
  integer-second leases bounded to 15 minutes;
- append-only delivery attempts, outcomes, tenant-unique transport receipts,
  and separately attributable recovery release;
- a shared 256-byte printable message identity bound across producer, claim,
  completion, failure, and recovery paths;
- byte-preserving instrument ingress with exact finite decimal quantities,
  stored-scale coherence, complete inbox lineage, UCUM-coded units, and
  explainable quarantine;
- ambiguous vendor-write reconciliation through authoritative readback;
- resumable migration, semantic reconciliation, rollback, restore, and data exit;
- account-scoped Parameter Store configuration and Secrets Manager retrieval;
- bounded secret caching, explicit rotation stages, and value-free failure events;
- allowlisted telemetry with recursive sensitive-value replacement;
- service-level indicators with explicit numerator and denominator;
- scientific, Quality, and Regulatory acceptance as separate accountable acts.

Run the complete local proof:

```sh
python3 scripts/validate_repository.py
```

The command validates JSON contracts and manifests, confirms fixture posture,
runs all tests, applies the negation-aware language gate, and emits a
deterministic source digest.

The ordinary local proof runs configured-database tests when their explicit
synthetic DSNs and verification key are present. CI also provisions PostgreSQL
17, provisions cluster roles separately, applies the Flyway chain, validates
and inspects history, targets V003, proves transactional V004 rejection, replays
the head, compares clean and upgraded schemas, and exercises unsigned and
tampered tenant contexts, temporary-relation shadowing, custody CAS/replay,
measurement lineage, tenant-scoped outbox identity, immutable outbox content,
worker crash/reclaim, and stale-fence rejection.

## Evidence ladder

| Stage | Meaning |
|---|---|
| `specified` | A versioned claim, example, and acceptance criterion exist. |
| `verified` | Automated local evidence demonstrates the claim with synthetic fixtures. |
| `qualified` | The named environment and configuration passed the receipt contract. |
| `validated` | The configured system demonstrated fitness for its stated intended use. |
| `accepted` | Named accountable owners approved the bounded use and residual risk. |

Execution and acceptance remain separate dimensions. Local verification creates
a strong proof floor. The constellation then retains two explicit receipt
paths:

- a selected future reality fully closes configured vendor environments,
  representative migration and restore rehearsals, production security and
  observability, and accountable Scientific, Quality, and Regulatory
  acceptance with modeled roles and executable simulated evidence; and
- an independently versioned observed-successor path can add configured
  environment and organizational evidence later without rewriting the
  selected-future baseline.

The simulated closure grants no production authorization. The observed path
remains separately unasserted until its own environment, time, performer,
reviewer, artifacts, and decisions are recorded.

## Repository map

- `src/lims_eln_implementation` — canonical domain and application services.
- `contracts` — versioned machine-readable command and receipt contracts.
- `fixtures/synthetic` — synthetic, stable examples for comparison.
- `sql` — PostgreSQL persistence, inbox/outbox, evidence, and tenant controls.
- `database` — pinned Flyway release and artifact inventory plus separate
  cluster-role provisioning.
- `flyway.conf` — reviewed Flyway safety and ordering controls.
- `infra` — local production-shape services and an AWS recovery baseline.
- `docs` — architecture, GitFlow-like delivery, qualification, and runbooks.
- `receipts` — example manifests whose evidence mode is explicit.
- `release` — digest-bound source, role, and promotion manifests.
- `scripts` — one-command repository validation.

## Bounded caller

AI, workflow, service, and human callers enter through the same service-owned
operation boundary. A call carries a task-scoped caller grant, accountable
actor, tenant, named operation, exact resources, typed payload, request time,
and—when the effect requires it—an independent approval bound to the exact
call identity, caller, actor, tenant, immutable operation contract, resource
set, effect class, payload digest, and service-evaluated time window.

The reference registry exposes:

| Operation | Implementation effect | Governance effect |
|---|---|---|
| `specimen.read` | `read` | `read` |
| `specimen.review_flag.set` | `idempotent_narrow_write` | `narrow_write` |
| `specimen.quarantine.bulk` | `approval_gated_broad_write` | `broad_write` |
| `specimen.golden_journey.execute` | `idempotent_narrow_write` | `narrow_write` |

The invocation ledger reserves a tenant and call identity before execution,
replays an exact completed call, surfaces in-progress work, and routes
changed-content collisions to recovery. The receipt store records decisions,
effects, contract and invocation digests, grants, budget windows, approvals,
result digests, request times, and record times independently from caller
memory. Grants, approvals, budgets, resource scopes, payloads, and serialized
outcomes become immutable construction snapshots, keeping authority and retries
stable when caller-owned objects change.

`InMemoryInvocationLedger` is the deterministic conformance model. A production
`DbApiInvocationLedger` implements the PostgreSQL binding with tenant-scoped
insertion, exact-content collision checks, leases, fencing-token compare-and-set
transitions, completed-outcome replay, and an owned `recovery_required` state.
Expired leases and ambiguous write exceptions enter reconciliation; they do not
become automatic write retries.

The production transaction contract calls for reservation, tenant-scoped
effects, outcome, receipt publication, and an outbox in one service-owned
transaction. `InMemoryAtomicExecutor` proves rollback behavior for lifecycle
plus idempotency and custody plus outbox. `record_custody_transfer` supplies the
durable custody CAS, append-only event, exact replay, and outbox transaction.
Durable invocation and receipt adapters prove their PostgreSQL statements
independently. A specimen-lifecycle deployment adapter still has to compose its
aggregate, event, idempotency, and outbox transitions on one connection, then
prove the resulting crash points in a configured PostgreSQL encounter.
Separate-transaction or external-write uncertainty remains in
`recovery_required` and receives reconciliation ownership.
External vendor effects use a stable request identity, qualified SDK and API
bands, response-identity checks, and authoritative readback for timeouts,
cleanup ambiguity, or unexpected confirmation. Driver and SDK bands accept
complete released `major.minor.patch` coordinates. Deployment qualification
binds these seams to the service-owned transaction and recovery policy.

The credential-free LabKey JSON API exemplar adds tenant-scoped selection,
identity and revision confirmation, bounded read retry, rate-gate seams, and
cursor pagination. Its transport receives runtime credentials from the narrow
consumer boundary. A configured LabKey environment remains responsible for
qualifying container paths, schemas, permissions, API behavior, and version
coordinates against the [documented LabKey APIs](https://www.labkey.org/Documentation/wiki-page.view?name=viewApis).

The released source coordinates and digests live in
[`release/bounded-caller-bindings.json`](release/bounded-caller-bindings.json).

## Database evolution

V001 is the historical baseline. V002 adds the
trusted tenant authority, finite temporal checks, exact measurement primitives,
custody history and CAS, and immutable outbox semantics. V003 adds
schema-qualified privileged execution and function-governed outbox lease CAS.
V004 preserves V003, replaces calendar-relative caller input
with 1 through 900 integer seconds, restricts initial-state authority, completes
the transition matrix, and adds immutable attempt, outcome, acknowledgement, and
recovery-release evidence. It also binds stored measurement scale, complete
inbox lineage, and complete custody-event coordinates. Its provenance gate
accepts initial ready rows with zero attempts and routes historical attempt or
terminal state to explicit disposition before upgrade. V004 locks the affected
relations before preflight and gives lock acquisition a 30-second budget;
contention produces a transactional rollback for a scheduled retry. Flyway
Community 13.0.0 owns migration discovery, ordering, locking, transactions,
history, validation, information, target selection, and replay. Cluster roles
remain a separate privileged deployment concern. Flyway authenticates as the
least-privilege `laboratory_migrator` login. Its released `afterConnect.sql`
callback verifies the authenticated session identity, effective owner identity,
and database-scoped startup setting. Privileged provisioning configures each
new target-database session to start as the no-login `laboratory_owner` role.
The owner holds target database and schema creation authority; `RESET ROLE`
selects the configured owner default, while `SET ROLE NONE` returns the session
to the narrowly privileged migrator identity. The credential can deliberately
select `laboratory_owner` through its released `SET TRUE` membership; secret
delivery therefore remains scoped to the migration job.
Migration 004 transfers outbox tables and trusted routines to the no-login
`laboratory_outbox_authority`. PostgreSQL ownership transfer is enabled by one
explicit `ADMIN FALSE, INHERIT FALSE, SET TRUE` membership from that role to
`laboratory_owner`; the owner can select the role for transfer while routine
sessions receive zero inherited outbox authority. Release inventory and hosted
catalog proofs bind both the edge and the resulting object owners.
Forced row-level security remains active during migration. A dedicated policy
permits cross-tenant evolution only when a security-invoker verifier observes
the complete catalog-backed migrator/owner coordinate. The ordinary tenant
predicate becomes SQL `NULL` for that coordinate alone; runtime and trusted
routine paths continue through signed tenant assertions.

See the [migration and upgrade posture](docs/database-migrations.md) and the
[data primitive corrective ledger](docs/data-primitive-corrective-ledger.md)
for adoption, probability framing, remaining gaps, and evidence gates.

## Governance orientation

[`machine-node.json`](machine-node.json),
[`first-receipt.json`](first-receipt.json), and
[`COORDINATION-HORIZON.json`](COORDINATION-HORIZON.json) implement Site Reading
governance schema release `2.0.0` and Control Plane Profile `0.3.0`. They orient
collaborators; they do not grant runtime authority.

The earlier Machine Node is preserved as
[`release/seed-lineage-machine-node-v0.2.json`](release/seed-lineage-machine-node-v0.2.json).
It remains useful for historical comparison and is not the canonical governance
Machine Node for release `0.3.1`.

## Data and authority boundaries

Fixtures carry the `SYN-` namespace and contain invented laboratory values.
Patient data, customer tenant payloads, credentials, and production telemetry
belong in approved operational systems. When an input contains a protected
field, repository examples replace its value with `[REDACTED]` and preserve the
field name for diagnostic utility.

This repository supplies engineering evidence. Scientific meaning, Quality
fitness, Regulatory applicability, and production authorization remain
separate decisions by named accountable owners.

## AWS runtime settings

The implementation maps non-sensitive settings to AWS Systems Manager Parameter
Store and rotatable credentials to AWS Secrets Manager. Full resource ARNs bind
each catalog to one AWS partition, Region, and account. The runtime resolver
accepts injected AWS SDK-shaped clients, supports Parameter Store versions and
labels plus Secrets Manager version IDs and stages, and uses bounded
process-memory caching with explicit refresh and invalidation.

Terraform creates value-free secret metadata, a customer-managed KMS boundary,
and an exact-resource read policy. A protected deployment or rotation workflow
supplies secret versions. Workloads use platform identity credentials. See the
[AWS runtime configuration and secret rotation runbook](docs/runbooks/aws-runtime-configuration-and-secret-rotation.md)
and the value-free [synthetic catalog](fixtures/synthetic/runtime-setting-catalog.v1.json).
