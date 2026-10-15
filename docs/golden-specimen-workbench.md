# Golden Specimen Workbench

The Golden Specimen Workbench is the smallest useful application surface in
the enterprise implementation. It carries one synthetic specimen through five
system boundaries and returns the evidence as a single tenant-scoped read model.

## What the encounter demonstrates

| Boundary | Executable behavior | Visible evidence |
|---|---|---|
| Lifecycle | Register and accession with optimistic revisions | Attributable events, command digests, aggregate revision |
| Custody | Place with an exact-replay transfer identity | Current location, custodian, custody revision, outbox message |
| Instrument | Preserve submitted bytes and normalize an approved JSON profile | Raw SHA-256, readable analyte/value/unit, normalized SHA-256, disposition, recovery instruction |
| Vendor | Project through a stable request identity | External revision, trace identity, authoritative-readback result |
| Tenant | Bind request header and payload to one identity | Tenant-scoped summary and specimen read model |

The workbench has two explicit state postures. The process-local adapter is a
deterministic engineering encounter; a restart begins a fresh encounter. The
PostgreSQL adapter runs the same FastAPI contract against V001–V008, and a
fresh service instance reloads its specimen from canonical stored state. When
the independently distributed accepted Program contract package is installed,
the same stored state also yields the exact typed observation. The Flyway chain
begins at
[`sql/V001__laboratory_core.sql`](../sql/V001__laboratory_core.sql); successor
[`sql/V005__golden_specimen_workbench.sql`](../sql/V005__golden_specimen_workbench.sql)
adds the durable review-resolution record and workbench projections without
creating a second custody or measurement truth.

## Run locally

Use the application lock in an isolated Python 3.12 environment:

```sh
uv sync --locked --extra contracts --extra postgres --extra test --no-editable
.venv/bin/lims-eln-workbench --adapter process_local
```

The dashboard is available at `http://127.0.0.1:8000/workbench`; the OpenAPI
description is at `http://127.0.0.1:8000/api/docs`. The `contracts` extra
resolves the exact reviewed Program 0.4.0 commit through configured Git access.
An editable sibling package remains an explicit development choice; installed
conformance uses the immutable receiving route.

The [local entry runbook](runbooks/local-workbench-entry.v0.1.md) covers
`--adapter postgresql`, local secret-file configuration, dependency readiness,
retained-state recovery, and installed versus editable use.

## Compose the PostgreSQL adapter

The locked environment above includes the PostgreSQL driver. A prepared local
database can use the explicit launcher; another deployment composes the adapter
through its existing injected boundaries.

`PostgresWorkbenchService` receives a DB-API connection factory and a signed
`TenantContextProvider` from its deployment boundary. Passing that service to
`create_app(service)` preserves the HTTP surface while keeping database
credentials and tenant-signing authority outside the dashboard and request
payload. The configured integration proof composes this exact FastAPI path.

The durable slice owns one transaction for invocation reservation, tenant
binding, lifecycle and custody mutation, instrument and normalized measurement
facts, vendor projection, bounded receipt, idempotency completion, and outbox
records. Each returned specimen is then rebuilt in a fresh tenant-bound
transaction through the V005 canonical views. The proof observes restart,
exact replay, changed-content collision, tenant isolation, late-failure
rollback and clean retry, quarantine, one corrected recovery, decimal source
shape, and canonical-digest drift.

The default dashboard values use the `SYN-` namespace. The reference service
holds one named tenant grant and three permitted actor identities; compose a
separate service for another tenant or actor set. Each run accepts an explicit
specimen, run, and role identity within that grant. Repeating the same content
under the same run identity returns the recorded outcome. Changing the content
under that identity produces an explainable collision and invites a new run
identity.

## HTTP surface

### Execution-time database provenance

Each newly completed PostgreSQL run stores its migration head in durable
coordinate version `3.0.0`. The source-owned V008 function reads successful,
contiguous Flyway history through a narrow execution grant. The ordinary
application role retains its existing table permissions. The result digest binds
the configuration alongside the specimen snapshot and receipt identity.

Replay and observation export use this stored configuration. A later migration
changes the head recorded by a new run; an earlier run keeps its own head.
Version `2.0.0` coordinates remain readable with `migration_head: null` and
`migration_provenance: unrecorded_legacy`. Historical stored coordinates and
receipts retain their bytes. Fresh exports state the information actually
available, and their configuration digests reflect that distinction.

Drain existing application transactions, complete Flyway migration and
validation, then admit new application transactions. The function observes the transaction's history
snapshot; migration exclusion remains a deployment responsibility. Failed,
missing, mixed-type or incomplete history holds a new completion. Resolve that
history through Flyway before retrying the same request. Future migration heads
retain the three-digit contiguous SQL-chain convention; application compatibility
continues through source review and configured checks.

Readiness includes the provenance reader. Unavailable history holds readiness
and new completions; stored observations retain their read route. Attested
baselines and direct-SQL installations remain distinct profiles: the current
new-run reader requires the complete versioned SQL history. A future profile
can add a separately reviewed provenance contract for those installations.
The native proof authors an explicitly labeled history fixture after applying
the SQL sources. Its placeholder checksums exercise admission and replay;
Flyway CLI validation retains its own source-checksum evidence.

The existing V007 hosted and native receipts retain their named source scope.
V008 integration requires renewed configured evidence. The current-source
observation guard remains active until that evidence is admitted.

PostgreSQL's [function-security guidance](https://www.postgresql.org/docs/17/perm-functions.html)
informs the fixed search path and qualified objects; Flyway retains
[migration transactions](https://documentation.red-gate.com/fd/migration-transaction-handling-273973399.html)
and applied-history validation.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health/live` | Process liveness |
| `GET` | `/health/ready` | Adapter readiness and state posture |
| `GET` | `/workbench` | Human-readable dashboard |
| `GET` | `/api/workbench/summary?tenant_id=…` | Tenant lifecycle and boundary summary |
| `GET` | `/api/workbench/specimens/{specimen_id}?tenant_id=…` | One complete specimen view |
| `GET` | `/api/workbench/observations/{run_id}?tenant_id=…` | Shared observation-envelope v1 view |
| `POST` | `/api/workbench/golden-runs` | Execute one five-boundary synthetic journey |
| `POST` | `/api/workbench/instrument-recovery-runs` | Link corrected bytes to a quarantined run and continue from processing |

Workbench API calls carry `X-Tenant-ID`. The header and requested tenant form
one exact identity. Raw instrument content travels as base64 so the service can
hash the submitted bytes before normalization.

When the reviewed `lims-eln-program-specification` 0.4.0 package is installed,
each successful run validates an exact `GoldenSpecimenObservation` at contract
revision 1.0.0. The observation names the shared
`SCN-GOLDEN-SPECIMEN-001` scenario, preserves raw and normalized digests, and
projects lifecycle, custody, measurement, review, and release into the shared
typed result. The PostgreSQL adapter builds that observation from freshly
loaded durable state. The main run remains available when the independently
distributed contract package is outside the current environment.

## Instrument review and recovery

The review path receives an incomplete analyte, non-finite or structurally
unsupported quantity, unsupported unit, malformed document, duplicate JSON
member, or changed content under a stable message identity as a named `409` domain
decision. The reached specimen stays `in_process`; its original bytes, digest,
reason code, recovery instruction, custody, and lifecycle events remain
inspectable. The tenant summary counts this as one open review item.

Recovery uses a new bounded call identity and carries `recovery_of_run_id` to
the quarantined call. The initial failure remains recovery-required, and only a
distinct recovery operation can continue it. Both paths emit visible bounded
call decisions and receipt identities. The review record retains tenant and
specimen identity in both the process-local service and durable SQL shape. A
conforming corrected message advances the existing specimen through scientific
review and Quality release.
The open review count returns to zero while `quarantine_history_count` retains
the evidence that review occurred. Exact recovery replay returns the recorded
outcome.

## Evidence boundary

This workbench establishes engineering verification with synthetic fixtures.
The configured PostgreSQL proof establishes the durable transaction and reload
behavior for its named PostgreSQL 17 environment. Versioned object storage for
raw payload bytes, broker delivery, configured vendor behavior, representative
restore drills, and accountable Scientific, Quality, Regulatory, Security, and
Operations decisions each retain their own receipt path. This separation keeps
the durable encounter useful while preserving the meaning of qualified,
validated, and accepted evidence.

## Extension seam

`WorkbenchService` remains the process-local composition root, while
`PostgresWorkbenchService` owns the bounded durable slice. A deployment
composition supplies its connection and signed tenant-context providers. The
next configured encounters can add versioned object storage, broker delivery,
and a qualified vendor mapping without changing the FastAPI request and
response contracts or the canonical V005 read model.
