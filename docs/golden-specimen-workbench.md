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

The process-local adapter is a deterministic engineering encounter. A restart
creates a fresh encounter. The Flyway chain begins at
[`sql/V001__laboratory_core.sql`](../sql/V001__laboratory_core.sql); successor
[`sql/V005__golden_specimen_workbench.sql`](../sql/V005__golden_specimen_workbench.sql)
adds the durable review-resolution record and workbench projections without
creating a second custody or measurement truth.

## Run locally

Use Python 3.12 or newer:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[test]"
lims-eln-workbench
```

Within a sibling constellation checkout, install the shared contract package to
emit and retrieve the versioned observation envelope:

```sh
python -m pip install -e ../lims-eln-program-specification
```

The dashboard is available at `http://127.0.0.1:8000/workbench`. The OpenAPI
description is available at `http://127.0.0.1:8000/api/docs`.

The default dashboard values use the `SYN-` namespace. The reference service
holds one named tenant grant and three permitted actor identities; compose a
separate service for another tenant or actor set. Each run accepts an explicit
specimen, run, and role identity within that grant. Repeating the same content
under the same run identity returns the recorded outcome. Changing the content
under that identity produces an explainable collision and invites a new run
identity.

## HTTP surface

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

When `lims-eln-program-specification` 0.3.x is installed, each successful run
also validates and stores an `ObservationEnvelope` at contract revision 1.0.0.
The envelope names the shared `SCN-GOLDEN-SPECIMEN-001` scenario, preserves the
raw digest, and classifies the process-local encounter as simulated verified
evidence. The main run remains available when the independently distributed
contract package is outside the current environment.

## Instrument review and recovery

The review path receives an incomplete analyte, non-finite or structurally
unsupported quantity, unsupported unit, malformed document, duplicate JSON member, or
changed content under a stable message identity as a named `409` domain
decision. The reached specimen stays `in_process`; its original bytes, digest,
reason code, recovery instruction, custody, and lifecycle events remain
inspectable. The tenant summary counts this as one open review item.

Recovery uses a new bounded call identity and carries `recovery_of_run_id` to
the quarantined call. The initial failure remains recovery-required, and only a
distinct recovery operation can continue it. Both paths emit visible bounded
call decisions and receipt identities. The review record retains tenant and
specimen identity in both the process-local service and durable SQL shape. A conforming corrected message
advances the existing specimen through scientific review and Quality release.
The open review count returns to zero while `quarantine_history_count` retains
the evidence that review occurred. Exact recovery replay returns the recorded
outcome.

## Evidence boundary

This workbench establishes local engineering verification with synthetic
fixtures. Configured PostgreSQL, object storage for raw payloads, vendor
credentials, recovery drills, and accountable Scientific, Quality, Regulatory,
Security, and Operations decisions each retain their own receipt path. This
separation keeps the local encounter useful while preserving the meaning of
qualified, validated, and accepted evidence.

## Extension seam

The `WorkbenchService` is the process-local composition root. Durable adapters
can implement the repository, inbox, outbox, and query seams while keeping the
FastAPI request and response contracts stable. The next configured encounter
should bind one transaction to lifecycle mutation, custody history, instrument
inbox, normalized observation, evidence receipt, and outbox publication, then
exercise its crash points against PostgreSQL.
