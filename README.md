# LIMS/ELN Enterprise Implementation

## Intent

This repository provides the comparative constellation's executable LIMS/ELN
reference implementation. It owns Python application and domain source,
synthetic fixtures, database evolution, configured engineering observations,
and the Golden Specimen Workbench.

The machine-readable evidence role `actual_implementation` means this source can
run and be compared with the Program, Simulation, and Comparative members.
Production qualification follows the configured-environment evidence and
accountable acceptance route described in [Evidence and authority](#evidence-and-authority).

## Start with the workbench

[Launch a process-local session](docs/README.md#start-with-a-process-local-session)
to explore laboratory records and the Golden Specimen flow. Start with a fresh
in-memory session, choose PostgreSQL when state should survive a restart, or use
the container route for a repeatable environment.

The [workbench starting guide](docs/README.md) connects those choices with
observation exports, comparison, and recovery. For example, load the Golden
Specimen, inspect its resulting state, then carry a selected run into an
observation export.

Insurance and administrative contracts are available through the accepted
Program package. [Explore the example and service boundaries](docs/README.md#explore-administrative-and-insurance-context)
before choosing the adapter or classification implementation work.

## Current state and branch roles

The [`repository role manifest`](release/repository-role.json) declares
`enterprise_implementation`, repository release `0.3.2`, external release
`implementation-v0.3.2`, and current state `post_release_development`. The
signed `v0.3.2` subject remains the accepted release baseline while current
`develop` source carries later, separately observed work.

| Branch | Role | Evidence route |
| --- | --- | --- |
| `main` | Preserves the observed v0.3.2 release baseline | [`0.3.2 promotion observation`](receipts/promotion-observation-v0.3.2.json) |
| `develop` | Integrates the post-release workbench, the exact hosted PostgreSQL observation for the Flyway 13.8.1 source coordinate, Governance 2.2.0 orientation, and Comparison 0.3.2 return | [`repository role manifest`](release/repository-role.json) and [`public-inspection manifest`](release/public-inspection-manifest.json) |

The [`Coordination Horizon`](COORDINATION-HORIZON.json) identifies additional
configured-environment qualification and accountable-role acceptance as the
next available route. Work enters that route
when an accountable receiver selects an approved environment and intended-use
scope, then binds its time, performer, reviewer, artifacts, limitations, and
acceptance path. The accepted Comparison return keeps its three measurement
differences with accountable scientific mapping.

## Choose your route

| Reader job | Start here | What the route provides |
| --- | --- | --- |
| Understand this repository's purpose | [Intent](#intent) | The implementation role and its production-qualification boundary |
| See the smallest executable system | [Quickest proof and workbench](#quickest-proof-and-workbench) | One synthetic journey across lifecycle, custody, instrument, vendor, and tenant boundaries |
| Evaluate released and current source | [`release/repository-role.json`](release/repository-role.json) and [`release/public-inspection-manifest.json`](release/public-inspection-manifest.json) | Signed release identity, current development state, exact current-byte inventory, and evidence boundaries |
| Find a technical capability | [Capability map by reader job](#capability-map-by-reader-job) | Grouped service-authority, laboratory-integrity, delivery, recovery, security, and assurance routes |
| Inspect deployment-shaped infrastructure | [`infra/README.md`](infra/README.md) | Compose-versus-Terraform chooser, prerequisites, checks, and evidence ceiling |
| Assess the strength of a claim | [Evidence and authority](#evidence-and-authority) | Distinct specified, verified, qualified, validated, and accepted states |
| Contribute, return, or resume work | [`AGENTS.md`](AGENTS.md), the [skill catalog](.agents/skills/README.md), and [return route](#collaboration-and-return-routes) | Current-source, branch, validation, recovery, evidence-binding, and handoff routes |

## Quickest proof and workbench

From a Python 3.12 environment with the test dependencies installed, run the
complete source-owned proof:

```sh
python3 scripts/validate_repository.py
```

This command validates contracts and manifests, confirms the synthetic-fixture
posture, checks credential-shaped material and authored language, runs the test
suite, and emits a deterministic source digest. Configured database and vendor
tests activate when their explicit environment coordinates are present; their
receipts remain the authority for those environments.

Run the process-local Golden Specimen Workbench from the isolated application
lock:

```sh
uv sync --locked --extra contracts --extra postgres --extra test --no-editable
.venv/bin/lims-eln-workbench --adapter process_local
```

Open `http://127.0.0.1:8000/workbench`. The process-local adapter begins a fresh
encounter after restart. The explicit `--adapter postgresql` route reuses
`PostgresWorkbenchService` and retained database state after the database,
roles, tenant, and verifier key have been prepared. Its readiness probe checks
the selected dependency and ordinary database identity.

The [local entry runbook](docs/runbooks/local-workbench-entry.v0.1.md) supplies
configuration, isolation, first-download versus repeat execution, and recovery.
The [owned database restart proof](docs/runbooks/owned-database-restart.v0.1.md)
creates private disposable clusters to exercise fast shutdown, immediate crash
recovery, retained state, replay, and pending-transaction rollback.
The [package handoff](docs/runbooks/program-package-handoff.v0.1.md) owns exact
Program 0.4.0 receiving evidence. This `develop` entry is a candidate for the
next release; the signed release baseline retains its original scope.

The [workbench guide](docs/golden-specimen-workbench.md) describes the API,
stored-state behavior, and typed observations. The [container entry](docs/runbooks/local-container-entry.v0.1.md)
adds protected retained credentials and the same PostgreSQL factory in a confined
application image. The [local observation export](docs/runbooks/local-observation-export.v0.1.md)
preserves typed comparison inputs in protected storage. The native and container
journey has completed acceptance under [Enterprise #43](https://github.com/driftframestudios/lims-eln-enterprise-implementation/issues/43).
The linked entry runbooks carry the current startup and recovery steps.

## Capability map by reader job

The focused proof exercises the following implementation families.

### Govern service effects and replay

- a typed bounded caller with task-scoped identity, tenant, capability,
  resource, request-budget, exact-approval, and replay boundaries;
- registered read, idempotent narrow-write, approval-gated broad-write, and
  bounded golden-journey operations whose services retain effect control;
- durable PostgreSQL receipt persistence and version-banded vendor SDK
  compatibility boundaries;
- exact replay and changed-content collision handling.

The [bounded caller](#bounded-caller) section carries the operation and durable
ledger detail.

### Trace laboratory state and scientific lineage

- database-verified, short-lived signed tenant assertions for every row policy;
- tenant-bound, attributable, revision-checked specimen transitions;
- custody compare-and-set transfer with append-only history, a schema-qualified
  privileged routine, and an atomic full-payload outbox;
- byte-preserving instrument ingress with exact finite decimal quantities,
  stored-scale coherence, complete inbox lineage, UCUM-coded units, and
  explainable quarantine.

### Inspect delivery, migration, and recovery

- Flyway Community migration ordering, locking, transactions, history,
  validation, status, target selection, and no-op replay;
- tenant-bound outbox claim, expired-lease reclaim, and exact confirmation with
  database-principal attribution, rotating UUIDs, monotonic fencing, and
  integer-second leases bounded to 15 minutes;
- append-only delivery attempts, outcomes, tenant-unique transport receipts,
  and separately attributable recovery release;
- a shared 256-byte printable message identity bound across producer, claim,
  completion, failure, and recovery paths;
- ambiguous vendor-write reconciliation through authoritative readback; and
- resumable migration, semantic reconciliation, rollback, restore, and data exit.

Continue through [Database evolution](#database-evolution) or the
[infrastructure reference](infra/README.md) when the deployment shape matters.

### Inspect runtime protection and accountable assurance

- account-scoped Parameter Store configuration and Secrets Manager retrieval;
- bounded secret caching, explicit rotation stages, and value-free failure events;
- allowlisted telemetry with recursive sensitive-value replacement;
- service-level indicators with explicit numerator and denominator; and
- scientific, Quality, and Regulatory acceptance as separate accountable acts.

Continue through [AWS runtime settings](#aws-runtime-settings) and
[Evidence and authority](#evidence-and-authority) for configuration and claim
boundaries.

## Evidence, release, and current inventory

[`release/public-inspection-manifest.json`](release/public-inspection-manifest.json)
gives a reviewer one deterministic inventory for the repository-owned
post-release source state. The separate `release_subject` retains the
immutable v0.3.2 tag object and accepted source coordinate. The current
inventory includes the exact Flyway 13.8.1 source and its separately observed
hosted database receipt without recasting that post-release work as part of the
signed release. It binds every current
FastAPI and domain source, Flyway V001 through
V007, local contract and synthetic input, operational configuration, behavior
proof, evidence record, and public orientation file by path, byte length,
SHA-256 digest, group digest, and one aggregate content identity. The signed
annotated tag `v0.3.1` identifies the prior accepted source release. Its later
[`promotion receipt`](receipts/promotion-receipt.json) records the tag object,
accepted commit and tree, tagged archive SHA-256, hosted checks, merge and tag
signature results, and where human approval was recorded alongside GitHub's
review state. The distinct
[`0.3.2 candidate receipt`](receipts/promotion-candidate.json) preserves the
bytes and external coordinates that entered review. The later
[`0.3.2 observation`](receipts/promotion-observation-v0.3.2.json) records the
accepted tag object, commit, tree, archive SHA-256, hosted validation, signature
results, and review route. Verify the checked-in inventory directly:

```sh
python3 scripts/build_public_inspection_manifest.py --check
```

[`release/external-contract-coordinates.json`](release/external-contract-coordinates.json)
binds the accepted Program package commit and scoped source digest together
with the accepted Governance 2.2.0 tag object, commit, tree, and archive digest.
It also binds the accepted Simulation and Comparative annotated tags that
reproduce the canonical selected-future closure digest.
The Comparative 0.3.1 coordinate remains the historical input that helped
select that future. A separate `comparison_return` records what the later
Comparison 0.3.2 run found: 10 agreements, four explainable variations, and
three measurement differences across 17 Golden Specimen paths. The analyte,
value, and unit differences now belong to accountable scientific mapping; the
comparison itself leaves their equivalence open. Its signed release, accepted
observation record, Golden report, and deterministic Pages projection retain
separate coordinates so each claim can be reproduced at the source that
establishes it.
The Program consumer observation uses a clean Python 3.12 environment, reads
the installed distribution's PEP 610 record, and exercises the released
catalog, scenario, example observations, four administrative resources, and nine
schemas. The [Program package handoff](docs/runbooks/program-package-handoff.v0.1.md)
provides the isolated receiving route and its recovery boundary. Reproduce that receiving
proof from adjacent accepted checkouts after installing the `contracts` extra:

```sh
python3 scripts/validate_received_contracts.py \
  --require-installed-program \
  --program-source ../lims-eln-program-specification \
  --governance-source ../site-reading-governance \
  --simulation-source ../lims-eln-simulated-final-state \
  --comparison-source ../lims-eln-comparative-evidence
```

The ordinary hosted pull-request proof remains self-contained and
credential-free. Configured-environment receipts retain their own system, time,
performer, reviewer, artifact, assurance, and limitation fields. Exact local
bytes, cross-repository acceptance, and environment evidence therefore remain
independently inspectable facts.

The ordinary local proof runs configured-database tests when their explicit
synthetic DSNs and verification key are present. CI also provisions PostgreSQL
17, provisions cluster roles separately, applies the Flyway chain, validates
and inspects history, targets V003, proves transactional V004 rejection, applies
V004 through the current head, replays the head, compares clean and upgraded
schemas, and exercises unsigned and
tampered tenant contexts, temporary-relation shadowing, custody CAS/replay,
measurement lineage, tenant-scoped outbox identity, immutable outbox content,
worker crash/reclaim, stale-fence rejection, and the durable FastAPI workbench's
restart, exact replay, changed-content collision, tenant isolation, rollback,
instrument recovery, and canonical-digest checks.

The [resource cleanup hosted receipt](receipts/hosted-postgresql-resource-cleanup-proof.json)
records successful PostgreSQL 17.10 and Flyway 13.8.1 clean/upgrade database jobs
at source `ae213e7c01262431030a2a8d81129bed090f1376`, after the transaction and
export resource ownership repair. The
[current plan observations](receipts/postgresql-resource-cleanup-plan-observations.json)
retain the actual planner and buffer results. The source workflow's Python jobs
rejected the earlier current-source receipt binding; this successor records the
successful database jobs, and its admission receives separate complete Python
validation. The separate
[native PostgreSQL 17 recovery receipt](receipts/owned-postgresql17-stream-ownership-proof.json)
records fast restart, immediate crash recovery and rollback at source
`a35dbaae69e8488a976bc580b3ea90addf12a9b1`, after the export stream follow-up,
using direct SQL migration execution. Local fault-injection tests cover teardown
interruptions, descriptor reuse and export publication state. The
[preceding native cleanup receipt](receipts/owned-postgresql17-resource-cleanup-proof.json)
retains its own source observation. The retained
[V007 hosted](receipts/hosted-postgresql-v007-proof.json),
[prior native recovery](receipts/owned-postgresql17-recovery-proof.json) and
[V005 hosted](receipts/hosted-postgresql-proof.json) receipts keep their original
source coordinates and evidence.

## Evidence and authority

| Stage | Meaning |
|---|---|
| `specified` | A versioned claim, example, and acceptance criterion exist. |
| `verified` | Automated local evidence demonstrates the claim with synthetic fixtures. |
| `qualified` | The named environment and configuration passed the receipt contract. |
| `validated` | The configured system demonstrated fitness for its stated intended use. |
| `accepted` | Named accountable owners approved the bounded use and residual risk. |

Execution and acceptance remain separate dimensions. Local verification
establishes source behavior with synthetic fixtures. The constellation then
retains two explicit receipt paths:

- a selected future reality fully closes configured vendor environments,
  representative migration and restore rehearsals, production security and
  observability, and accountable Scientific, Quality, and Regulatory
  acceptance with modeled roles and executable simulated evidence; and
- an independently versioned observed-successor path can add configured
  environment and organizational evidence later without rewriting the
  selected-future baseline.

The simulated closure establishes its selected-future evidence only. Production
authorization comes from a configured observation whose environment, time,
performer, reviewer, artifacts, limitations, and accountable decisions are
recorded.

## Repository map

- `src/lims_eln_implementation` — canonical domain and application services.
- `src/lims_eln_implementation/workbench` — functional dashboard, API, and
  process-local and PostgreSQL composition roots.
- `contracts` — versioned machine-readable command and receipt contracts.
- `fixtures/synthetic` — synthetic, stable examples for comparison.
- `sql` — PostgreSQL persistence, inbox/outbox, evidence, and tenant controls.
- `database` — pinned Flyway release and artifact inventory plus separate
  cluster-role provisioning.
- `flyway.conf` — reviewed Flyway safety and ordering controls.
- [`infra`](infra/README.md) — local deployment-shaped services and an AWS
  recovery baseline.
- [`docs`](docs) — architecture, GitFlow-like delivery, qualification, and
  runbooks.
- [`receipts`](receipts) — example manifests whose evidence mode is explicit.
- [`release`](release) — digest-bound source, role, and promotion manifests.
- [`scripts`](scripts) — one-command repository validation.

## Collaboration and return routes

The [repository-local skill catalog](.agents/skills/README.md) groups five
repeatable routes by reader job:

- [`repository-reentry`](.agents/skills/repository-reentry/SKILL.md) recovers
  current source, release, configured-environment evidence, and coordination
  truth.
- [`source-authority-mapping`](.agents/skills/source-authority-mapping/SKILL.md)
  distinguishes contract, implementation, observation, acceptance, release,
  and receiving roles.
- [`proportionate-recovery-routing`](.agents/skills/proportionate-recovery-routing/SKILL.md)
  selects the smallest useful recovery move after an observed problem.
- [`configured-environment-evidence-binding`](.agents/skills/configured-environment-evidence-binding/SKILL.md)
  admits a returned database, vendor, or runtime observation at exact
  coordinates.
- [`contextual-jargon-scan`](.agents/skills/contextual-jargon-scan/SKILL.md)
  revises collaboration-local shorthand while retaining exact technical and
  regulated language.

These skills currently carry the `public_possible` source band. That field
describes a review stage: a separate public-ready review can accept a settled
reader job and navigation route. Current user intent, repository evidence, and
granted authority continue to govern each use.

[`AGENTS.md`](AGENTS.md) owns the standing repository workflow. A complete
return names the changed source, the smallest observation that establishes its
behavior, the observation's reach and limit, and the role or repository that
can make the next decision.

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
| `specimen.golden_journey.recover_instrument` | `idempotent_narrow_write` | `narrow_write` |

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
`PostgresWorkbenchService` now composes the bounded Golden Specimen aggregate,
events, idempotency state, custody, instrument facts, vendor projection,
receipt, and outbox records on one connection. Its configured synthetic proof
observes late-failure rollback and a clean retry, then reconstructs the response
from canonical stored state after restart. Separate-transaction or external-
write uncertainty remains in `recovery_required` and receives reconciliation
ownership.
Database adapters attempt rollback and each acquired cursor/connection release
once. The first control interruption remains observable after the remaining
cleanup attempts; ordinary transaction failures keep their existing meaning.
Local exception diagnostics retain named `cleanup_failures`, with value-free
stage/type notes. Receipt and invocation adapters share their transaction owner;
the workbench retains its whole-request SQLSTATE retry translation.

External vendor effects use a stable request identity, qualified SDK and API
bands, response-identity checks, and authoritative readback for timeouts,
cleanup ambiguity, or unexpected confirmation. Driver and SDK bands accept
complete released `major.minor.patch` coordinates. Deployment qualification
binds these integration boundaries to the service-owned transaction and
recovery policy.

The credential-free LabKey JSON API exemplar adds tenant-scoped selection,
identity and revision confirmation, bounded read retry, and rate-limit
boundaries with cursor pagination. Its transport receives runtime credentials
from the narrow consumer boundary. A configured LabKey environment remains
responsible for qualifying container paths, schemas, permissions, API behavior,
and version coordinates against the [documented LabKey APIs](https://www.labkey.org/Documentation/wiki-page.view?name=viewApis).

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
V005 retains those canonical records, binds every inbox fact to its specimen,
records append-only quarantine resolutions with exact replacement lineage, and
offers security-invoker workbench projections. A bounded recording routine
accepts only quarantined sources and accepted or replayed replacements from the
same tenant and specimen.
Flyway
Community 13.8.1 owns migration discovery, ordering, locking, transactions,
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
sessions receive zero inherited outbox authority. V004 supplies and withdraws
the new owner's schema-creation capability inside the migration transaction.
Release inventory and hosted catalog proofs bind the edge, the resulting object
owners, and the absence of that creation capability at head.
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
governance schema release `2.2.0` and Control Plane Profile `0.3.0`. They orient
collaborators while bounded operations and accountable runtime roles retain
effect authority.

The earlier Machine Node is preserved as
[`release/seed-lineage-machine-node-v0.2.json`](release/seed-lineage-machine-node-v0.2.json).
It remains useful for historical comparison; `machine-node.json` is the
canonical governance Machine Node for the observed `0.3.2` source release.

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

## Provenance and authorship

Repository authorship and maintenance provenance is recorded in
[`AUTHORS`](AUTHORS). Git history and reviewed pull requests preserve change
chronology and contribution credit.

The architectural starting point is `driftframestudios/prototype-exemplars`
pull request [#3](https://github.com/driftframestudios/prototype-exemplars/pull/3):

- source head: `8be1e2c2ce239e51dcd5d1e19d1ff52e9d080b72`;
- merged result: `613f524821a25389748a9cd98d1bb0d303de87cf`;
- source validation floor: 69 synthetic tests on Python 3.12 and 3.13.

Runtime code is authored and maintained in this repository. Versioned
contracts connect it to the constellation's other members, while simulation
source retains its separate owner.
