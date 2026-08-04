# Data primitive corrective ledger

This ledger records each material schema decision in the current target state.
It distinguishes canonical laboratory data from framework-owned operational
mechanics and retired prototype structures.

| ID | Element | Previous risk | Current representation | Executable evidence |
|---|---|---|---|---|
| DP-001 | All recorded times | Text values lose ordering, timezone, and database validation. | `timestamptz`, UTC at boundaries, `isfinite` checks for stored domain times. | Python rejects naive datetimes; PostgreSQL constraints cover specimen, event, custody, inbox, measurement, vendor, and outbox times. |
| DP-002 | Scientific quantity | Floating point changes decimal meaning; fixed coercion can erase observed scale. | PostgreSQL `numeric` plus finite, scale 0–18, and magnitude checks; `source_precision` 1–38 and `source_scale` 0–18 remain explicit. | Instrument tests cover exact decimal strings, non-finite values, precision, scale, units, and lineage. |
| DP-003 | Business identifiers | Numeric storage discards leading zeroes and invites arithmetic on identifiers. | `text` for tenant, specimen, command, instrument, vendor, transfer, topic, and account-scoped external identities; bounded printable formats where required. | Model and database constraints exercise empty, collision, and over-bound identities. |
| DP-004 | Event identity | Free-form identifiers weaken interoperability. | PostgreSQL `uuid` for domain event identity; stable text remains for externally supplied idempotency and vendor request keys. | Lifecycle uses deterministic UUIDv5 events and stable command identities. |
| DP-005 | Canonical documents | Unstructured serialized text obscures shape and comparison. | `jsonb` with object checks and canonical SHA-256 digests. | Canonical serialization and changed-content collision tests. |
| DP-006 | Command replay | Repeated delivery can repeat a material effect. | Tenant-scoped idempotency key, content digest, explicit reserved/committed state, and stored outcome. | Exact replay, collision, in-progress, commit, and rollback tests. |
| DP-007 | Specimen and custody concurrency | Last-write-wins can overwrite another actor's update. | `bigint` aggregate and custody revisions with compare-and-set transitions. | Unit tests and PostgreSQL `record_custody_transfer` integration. |
| DP-008 | Custody history | Current position alone cannot reconstruct movement. | Append-only `custody_event`; current position carries the complete resulting-version and transfer foreign key. | Static composite-FK checks and configured PostgreSQL tests. |
| DP-009 | Instrument source | Parsed values can detach from source bytes. | Raw object key, SHA-256, capture time, inbox disposition, normalized digest, and composite measurement lineage. | Raw-digest, message replay, scale, and source-lineage tests. |
| DP-010 | Units | Display strings can silently mix incompatible measures. | Released UCUM code and system columns beside exact quantity. | Unit allowlist and normalized-document tests. |
| DP-011 | Tenant isolation | Queries without tenant coordinates can leak adjacent rows. | Tenant in every key; forced PostgreSQL RLS reads one transaction-local `app.tenant_id` selected after application authentication. | Unit test for the binding helper and configured PostgreSQL isolation test. |
| DP-012 | Vendor projection | Provider records can advance independently or return ambiguous writes. | Expected external revision, stable request identity, canonical digest, certainty classification, and authoritative readback. | In-memory gateway, LabKey, pagination, retry, conflict, and ambiguity tests. |
| DP-013 | Cross-service event | A database commit followed by direct broker publication creates a dual-write gap. | Insert-only transactional outbox with event identity, topic, aggregate key and revision, payload, digest, canonicalization, and database time. | Custody and outbox commit/rollback tests; Debezium Event Router configuration test. |
| DP-014 | Outbox delivery state | A custom lease/fence/recovery engine duplicated connector and broker responsibilities. | Debezium owns log capture, offsets, routing, retries, and connector recovery. Delivery columns and recovery relations leave the current schema. | Successor-migration posture checks and PostgreSQL update/delete rejection. |
| DP-015 | Database migration state | A custom runner duplicated history, checksums, locking, and ordering. | Flyway Community `migrate`, `validate`, `info`, timestamp versions, and `outOfOrder=true`. | CI applies, validates, inspects, and replays the chain on PostgreSQL 17. |
| DP-016 | Runtime configuration | A 700-line resolver recreated provider caching, selectors, and error behavior. | Pydantic validates value-free references; AWS Powertools Parameters retrieves and caches Parameter Store and Secrets Manager values. | Injected getter tests prove names, versions, stages, TTL, and plaintext-free metadata. |
| DP-017 | Authentication and policy | A signed database HMAC document duplicated deployment identity and authorization. | The selected deployment identity layer authenticates and authorizes; PostgreSQL receives only the resulting tenant scope for row isolation. | Successor migration removes key storage and binding functions; tests prove the remaining scope. |
| DP-018 | Scientific and Quality decisions | Application tables simulated organizational acceptance and accountable people. | Decisions remain in the adopting organization's QMS/eQMS and vendor-evaluation process. The implementation repository supplies technical evidence only. | Successor migration removes acceptance and evidence-receipt tables. |
| DP-019 | Migration rehearsal | An in-memory migration engine competed with Flyway and environment tools. | Flyway evolves schema; vendor export/import tools and PostgreSQL snapshots perform representative rehearsal; comparison scripts remain environment-specific. | Python migration simulator and checkpoint table leave runtime; the migration runbook defines direct rehearsal outputs. |
| DP-020 | Repository policy | Custom branch regex and repository validators duplicated hosting controls and standard tools. | GitHub Rulesets, required CI checks, Ruff, unittest, build, Flyway validation, and platform secret scanning. | The custom validator workflow, source, and tests leave the repository. |

## Historical migration note

V001–V004 remain immutable because Flyway checksums already give them durable
identity. They contain earlier bounded-call, signed-tenant, acceptance, and
outbox-recovery structures. The timestamped successor removes those structures
from the active schema while preserving valuable specimen, custody, instrument,
quantity, vendor, and outbox facts.

## Remaining configured-environment work

The repository deliberately leaves these items to the selected environment:

- vendor sandbox versions, schemas, permissions, throttling, and data exit;
- broker topology, Debezium connector, logical replication, TLS, and topics;
- identity provider, workload identity, and tenant authorization policy;
- object-store durability and artifact transfer;
- representative migration volume, rollback, restore, RTO, and RPO; and
- scientific, Quality, and Regulatory evaluation in established systems.

Each item becomes executable after a vendor and hosting environment are chosen.
Until then, the code exposes stable integration seams rather than simulated
environment state.
