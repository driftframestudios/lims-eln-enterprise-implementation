# Data primitive corrective ledger

## Decision frame

This ledger records observed implementation facts, their material effects, the
selected correction, and the remaining evidence. It distinguishes a confirmed
defect from a design preference and from a conforming primitive.

The probabilities below estimate this conditional outcome:

> Given a capable delivery team, one release cycle, the stated gates, and a
> representative PostgreSQL rehearsal, what is the probability that the plan
> reaches a release candidate which passes independent principal-engineer,
> database, security, operations, and scientific review with only bounded
> follow-up?

They are judgmental priors for sequencing, rather than measured defect rates.
Each interstitial replaces the prior with evidence from the latest executable
receipt.

## Plan range

| Plan | Shape | Estimated probability | Characteristic strength | Material gap |
|---|---|---:|---|---|
| A. Narrow primitive patch | Correct timestamp and quantity types in place; retain the original bootstrap path. | 0.46 | Small review surface. | Leaves schema history, authority, concurrency, and upgrade safety implicit. |
| B. Migration-first vertical integrity | Freeze the baseline; add checksum-bound migrations, trusted tenant context, typed quantities, custody CAS/history, governed outbox leases, and live adversarial tests. | **0.88** | Connects each primitive to authority, transaction, recovery, and evidence. | Requires a representative active-environment upgrade rehearsal and operating ownership. |
| C. Mature migration product now | Adopt Flyway or Liquibase, import baseline history, and express every future change through the selected product. | 0.72 | Brings a broad operational ecosystem and familiar controls. | Product adoption can obscure the domain corrections during this tranche; baseline attestation still requires judgment. |
| D. Shadow database and dual-read comparison | Build the corrected schema beside the current system, replay representative data, compare semantic digests, then cut over. | 0.68 | Produces powerful comparative evidence and a recoverable cutover. | Doubles operational surfaces and requires explicit conflict ownership. |
| E. Full canonical-model decomposition | Replace broad JSON documents and free-form identifiers with domain tables, reference vocabularies, and temporal history in one program. | 0.57 | Maximizes relational expressiveness. | Broad simultaneous change raises migration, scientific-validation, and delivery risk. |

The selected synthesis uses Plan B as the spine, Plan C's immutable history and
validation semantics, Plan D's restore-and-compare rehearsal, and Plan E only
where a primitive has stable scientific meaning. JSON remains useful at
versioned ingress and evidence boundaries; canonical scientific quantities now
also have a typed relational representation.

## Finding ledger

| ID | Observed condition and material effect | Disposition | Evidence or next gate |
|---|---|---|---|
| DP-001 | Schema creation depended on a Docker initialization directory. An existing database had no ordered upgrade mechanism or applied-history checksum. | **Corrected for the active vertical slice.** `database/migration-manifest.json` binds the runner and SQL files. The runner supplies strict order, SHA-256 drift detection, append-only applied history, one transaction per migration, and transaction-level advisory coordination. The reference pack separately demonstrates session-level plan serialization, authenticated pre-populated-baseline adoption, and an atomic backfill/validate/cutover group. | Static drift tests and the active PostgreSQL 17 clean-install job pass. The reference pack adds PostgreSQL 16/18 clean-install and synthetic populated-adoption proof. ENV-DB-001 remains the configured active-environment receipt; the comparator records the two release mechanisms as distinct paths. |
| DP-002 | The original row policies trusted caller-set `app.tenant_id`. Any role able to issue SQL could select another tenant value before a query. | **Corrected.** Migration 002 replaces every policy with a database-verified, short-lived HMAC assertion. The verification key is private to `laboratory_security`; workload roles receive zero key-table privilege. | Adversarial live tests cover unsigned, expired, and tenant-tampered assertions plus legacy-GUC irrelevance. Production issuer, key rotation, and revocation receipts remain SEC-CTX-001. |
| DP-003 | Python outbox replay used `message_id` alone, so two tenants sharing a source identifier collapsed into one message. Changed content also returned as though it were an exact replay. | **Corrected.** Identity is `(tenant_id, message_id)` and changed semantic content raises a reviewable collision. | Unit tests cover cross-tenant reuse, exact replay, and changed content. |
| DP-004 | The in-memory outbox retained only a caller-supplied digest. A downstream worker lacked the immutable payload needed to publish or reconcile the event. | **Corrected.** `OutboxMessage` snapshots full canonical payload JSON and derives its digest from that snapshot. Custody publishes the full transfer fact. | Mutation, rollback, replay, and content-collision tests pass. |
| DP-005 | SQL grants allowed the application and worker to update every outbox column. Payload, aggregate identity, digest, and delivery coordinates could drift after commit. | **Corrected.** Insert-time digest verification and an immutable-content trigger preserve message meaning. Migration 003 removes direct worker mutation and exposes tenant-bound claim, expired-lease reclaim, and confirmation functions. Each lease records the invoking database principal and worker-instance label, rotates a UUID, advances attempts and a monotonic fence, and confirms through an exact unexpired compare-and-set coordinate. A transition trigger and state checks preserve legal movement independently of caller SQL. | Static grants and function-shape checks plus live PostgreSQL prove direct-update rejection, claim, simulated crash expiry, fenced reclaim, stale-worker rejection, and current-worker completion. ENV-OUTBOX-001 remains the configured throughput, broker, crash-process, recovery-alert, and operating-owner qualification receipt. |
| DP-006 | Custody persistence performed an unconditional last-write-wins save and kept only current position. A stale writer could replace a valid transfer and the audit trail could disappear. | **Corrected.** Both conformance and SQL models use expected-version CAS, tenant-scoped transfer idempotency, append-only history, and one atomic outbox transaction. | Unit tests cover stale writers, exact replay, changed transfer content, history, and rollback. Live PostgreSQL covers CAS, replay, history, and outbox atomicity. |
| DP-007 | Instrument JSON accepted JavaScript numeric extensions such as `NaN`, coerced structured analytes with `str()`, and left precision and scale implicit. | **Corrected.** Ingress uses exact `Decimal` parsing, duplicate-member detection, finite-value checks, a 38/18 released profile, explicit analyte shape, bounded payload size, and UCUM-coded units. | Negative tests cover non-finite, duplicate, structured, Boolean, over-scale, additional-field, and unsupported-unit cases. Scientific range qualification remains SCI-QTY-001. |
| DP-008 | Normalized measurements existed only as JSON digest material. SQL had no exact quantity primitive for scientific query, validation, or export. | **Corrected.** `instrument_measurement` stores an exact unconstrained `numeric` with explicit 20-integer-digit, 18-fractional-digit, and finite-value checks. This avoids typmod rounding before validation. It also stores source precision/scale, analyte code, UCUM system/code, raw and normalized digests, finite timestamps, tenant identity, and inbox lineage. | Static policy and schema checks pass. Configured instrument-to-measurement persistence remains ENV-INSTRUMENT-001. |
| DP-009 | `Command.content_digest` was recomputed from caller-owned nested payload objects. Mutation after construction could change authorization and replay meaning. | **Corrected.** Commands now retain recursively immutable JSON snapshots and construction-time digests. | A nested-mutation regression test passes. |
| DP-010 | A suspected text representation for `updated_at_utc` was checked. In this repository the column was already `timestamptz`; all baseline operational dates use temporal types. | **Verified conforming, then strengthened.** Migration 002 adds finite-time checks because PostgreSQL timestamp types intentionally admit infinity. | Schema checks and the active PostgreSQL 17 migration job cover this exact implementation. The reference pack exercises the canonical temporal contract on PostgreSQL 16 and 18 as separate portability evidence. |
| DP-011 | Several state machines used independent nullable columns whose combinations were only partially constrained. | **Partially corrected.** Idempotency, instrument disposition, outbox delivery, and evidence JSON shapes now have coherence checks. | Lifecycle-wide property and transition testing remains DATA-STATE-001. |
| DP-012 | Canonical JSON digests depend on an explicit byte representation. PostgreSQL `jsonb::text` and Python sorted compact JSON are different canonicalization profiles. | **Corrected at each boundary.** Python messages name their canonical snapshot implicitly through code release; SQL records `postgresql-jsonb-text-v1` and verifies its digest in the database. | A cross-language canonicalization contract or RFC 8785 adoption remains DATA-CANON-001 before messages cross runtimes by digest alone. |
| DP-013 | Broad `text` identifiers allow values whose length and vocabulary vary across tables. Text itself is a sound PostgreSQL primitive; missing domain bounds are the risk. | **Open by design.** New signed-context, custody-function, analyte, and measurement inputs are bounded. | DATA-ID-001 will inventory every identifier, select durable external/local identity semantics, and add constraints through expand/validate/contract migrations. |
| DP-014 | `specimen.canonical_document` and several evidence documents remain JSONB. Their digests and schemas are application-governed rather than fully database-governed. | **Open with containment.** Object/array shape gates were added where meaning is stable. | DATA-JSON-001 will decide per field among generated typed columns, JSON Schema at ingress, or a decomposed relational model. |
| DP-015 | The database accepts a specimen document and its supplied SHA-256 without independently deriving the same canonical bytes. | **Open.** Cross-runtime canonicalization needs a released algorithm before a trigger can prove equality. | DATA-CANON-001 owns the algorithm decision and corpus of Unicode, decimal, ordering, and normalization vectors. |
| DP-016 | Migration 002 adds checks which intentionally surface incoherent legacy rows. Object names alone provide insufficient evidence for adopting an untracked populated baseline. | **Partially evidenced and receipt-bound.** The reference pack authenticates a populated v0.1 baseline through an exact catalog fingerprint, preserves source and target representations, applies grouped conversion, and produces reconciliation and restore evidence. The active system uses restore, migration, semantic comparison, and evidence-bound cutover in its configured environment. | PostgreSQL 16/18 synthetic adoption proves the reference mechanism. ENV-DB-001 records active-environment preflight counts, constraint exceptions, lock time, rollback timing, restore parity, and accountable approval. |
| DP-017 | A signed tenant assertion is a bearer capability which can be replayed during its short validity window. The nonce provides unique signed content and currently has no consumption ledger. | **Open with containment.** The 15-minute maximum lifetime, TLS, narrow issuer, private verification key, per-statement expiry check, and database audit boundary limit exposure. | SEC-CTX-002 decides whether configured risk calls for shorter lifetimes, channel binding, a replay ledger, or sender-constrained credentials. |
| DP-018 | Tenant authorization and accountable actor attribution are separate concerns. The signed context carries a subject, while custody currently accepts a custodian identifier as domain input. | **Open with explicit ownership.** The bounded-caller layer verifies actor/delegation and persists attributable receipts; the database independently enforces tenant scope. | AUTH-ACTOR-001 will bind actor/delegation evidence to database mutations where the configured threat model requires database-level verification. |
| DP-019 | `record_custody_transfer` executed with owner authority while its table and composite-type names were unqualified and `public` preceded the implicit temporary schema. A session-local relation could redirect privileged statements away from canonical custody evidence. | **Corrected.** Migration 003 replaces the function with explicit `public` qualification for every relation and composite type, explicit schema qualification for extension calls, and `pg_catalog, pg_temp` as its fixed search path. The same posture governs every new outbox `SECURITY DEFINER` routine. | A live application-role adversarial test creates three same-named temporary relations, executes a custody transfer, observes zero temporary rows, and verifies the canonical custody and outbox facts. Static checks retain the safe search path and qualified-object contract. |
| DP-020 | The migration-003 outbox claim and reclaim routines accepted PostgreSQL `interval` values and compared them with `interval '15 minutes'`. Intervals preserve independent month, day, and time fields; a mixed-sign value such as `1 month -30 days + 1 second` can compare as a short duration while timestamp addition resolves to materially longer wall time on some calendar dates. The first migration-004 draft also expressed its 86,400-second recovery ceiling as calendar-relative `interval '1 day'`, which diverges from elapsed seconds across daylight-saving boundaries. | **Corrected in immutable successor migration 004.** Privileged APIs accept integer seconds only, claim/reclaim require the closed range 1 through 900, recovery release requires 0 through 86,400, and both construct or compare expiry with `pg_catalog.make_interval(secs => ...)`. Migration 003 retains its published bytes. | A live PostgreSQL regression submits the mixed-unit interval through the retired signature and proves that interval dispatch has no callable surface; companion cases prove integer ceilings. Static checks preserve the exact 86,400-second recovery comparison. Fenced claim/reclaim and recovery prove accepted durations and current-coordinate completion. |
| DP-021 | The migration-003 transition guard covered selected lease and delivery movements while leaving `ready` and `recovery_required` reachable through owner-shaped updates. Its recovery-state constraint accepted ambiguous lease-coordinate combinations. The application also retained table-level insert authority and could supply a coherent terminal state instead of allowing defaults to establish `ready`. | **Corrected in migration 004.** A dedicated no-login outbox authority owns state mutation. Application insert authority is column-scoped to message identity/content and intentional availability; defaults and an insert guard establish the initial state. The transition guard accepts exactly `ready → leased`, expired `leased → leased`, `leased → delivered`, `leased → recovery_required`, and evidence-backed `recovery_required → ready`. A worker records exact failure coordinates, while a separately attributable recovery operator records the bounded release decision. | Static checks enumerate the complete matrix and narrow grants. Live PostgreSQL rejects a forged terminal application insert, direct worker updates, owner-shaped `ready → recovery_required`, and recovery release without immutable evidence; legal failure and release complete through governed routines. Configured separation-of-duty membership and recovery operations remain part of ENV-OUTBOX-001. |
| DP-022 | Reclaim replaced the current lease coordinate and confirmation cleared it, so parent-row state retained no durable reconstruction of every attempt. A successful confirmation also accepted no transport acknowledgement, leaving delivery status disconnected from broker evidence. | **Corrected in migration 004.** Tenant-scoped append-only attempt and outcome relations retain worker label, invoking principal, UUID, fence, open/expiry/close times, expiry or failure outcomes, and the bounded transport system and receipt. Recovery releases form a third immutable relation. Confirmation closes the exact current attempt and requires a tenant-unique transport acknowledgement; reclaim closes the expired attempt before opening its successor. | Live PostgreSQL proves two attempts survive reclaim, stale completion is rejected, append-only guards preserve prior evidence, one durable receipt closes the current attempt, duplicate tenant receipt replay fails, and failure/recovery/re-delivery remains reconstructable. Broker authenticity and configured retention/export qualification remain ENV-OUTBOX-001. |
| DP-023 | The first migration-004 draft restricted governed routine inputs to 256 printable bytes while application column-level insert still accepted any PostgreSQL `text` message identity. A producer could insert a longer or non-ASCII identity, the claim routine could lease it, and every completion or recovery routine would reject it, stranding a live lease. | **Corrected in migration 004.** Preflight and a table constraint establish the same nonblank printable-ASCII 1-through-256-byte identity domain that every governed routine accepts. The bound lives below the producer and worker APIs, so every claimable message remains completable. | Live PostgreSQL rejects over-bound and non-ASCII application inserts, then carries an exact 256-byte identity through claim and transport-confirmed completion. Static checks bind the preflight, table constraint, and routine limits. The broader identifier inventory remains DATA-ID-001. |
| DP-024 | The first migration-004 draft allowed pre-existing delivered or recovery-required rows while creating empty attempt, outcome, and recovery-release relations. Those terminal histories could cross the upgrade boundary without reconstructable provenance even though subsequent delivery was fully evidenced. A provenance query before the migration's first table lock would also leave a check-to-change race for a concurrent legacy writer. | **Corrected in migration 004 with a locked, strict provenance gate.** A transaction-scoped `ACCESS EXCLUSIVE` outbox lock precedes both preflight predicates. Preflight accepts only coherent initial `ready` rows with zero attempts, zero fence, and empty lease/error/delivery coordinates. Every accepted row opens its first evidenced attempt after migration. Historical terminal or attempted rows require an explicit export, attestation, conversion, or disposition before 004 can apply. Lock acquisition has a 30-second budget, while statements and idle-in-transaction time have five-minute budgets; contention preserves the prior head for a scheduled retry. | A static exact-order proof binds the lock before the preflight and its local time budgets. A hosted PostgreSQL 17 upgrade proof applies 001–003, seeds representative ready and terminal rows, proves 004 rejects the terminal state while leaving migration history at 003, disposes the synthetic exception, preserves two ready rows, then exercises confirm and failure/recovery/re-delivery with complete immutable evidence. Active-environment lock duration, disposition, and maintenance-window acceptance remain ENV-DB-001. |

## Recommended chain of action and interstitials

1. **Freeze and bind.** Preserve migration 001 byte-for-byte and require the
   manifest checksum in repository validation. Interstitial: checksum drift or
   an unlisted SQL file returns the tranche to design.
2. **Rehearse from empty.** Apply 001 through 004 through the runner on PostgreSQL
   17, then rerun to prove exact no-op replay. Exercise the reference mechanism
   independently on PostgreSQL 16 and 18. Interstitial: inspect locks, duration,
   warnings, roles, extensions, applied-history rows, and release-mechanism
   coordinates before comparing results.
3. **Rehearse with representative state.** Restore a synthetic-but-shaped
   populated baseline into an isolated source; attest its catalog and source
   population; migrate a fresh target; compare identities, quantities,
   relationships, audit events, artifacts, and digests. The migration-004 gate
   accepts only initial ready outbox rows and routes prior attempt or terminal
   state to an explicit disposition. Interstitial: every exception receives a
   named migration disposition and accountable owner.
4. **Exercise adversaries.** Run tenant-forgery, temporary-relation shadowing,
   stale custody, outbox mutation, worker crash/reclaim, stale-fence completion,
   mixed-unit lease-duration bypass, unfinishable message identity, malformed
   quantity, key revocation, concurrent runner, and crash-point scenarios.
   Interstitial: update probability from the observed pass/fail and severity
   distribution.
5. **Qualify operations.** Observe backup, restore, forward-repair, key rotation,
   lease expiry, queue recovery, and monitoring in the configured environment.
   Interstitial: Operations and Security sign separate receipts.
6. **Qualify scientific meaning.** Scientific and Quality owners approve the
   quantity ranges, UCUM mappings, analyte vocabulary, rounding policy, and
   source-to-canonical trace. Interstitial: Regulatory evaluates intended-use
   impact separately.
7. **Promote through expand/validate/contract.** Future migrations add nullable
   structures, backfill with resumable checkpoints, validate constraints, move
   readers and writers, and retire compatibility surfaces after observation.

## Cross-repository evidence boundary

The active implementation and reference pack now share the intended scientific
and tenancy invariants while retaining distinct release paths:

- the active implementation uses a manifest-authenticated PostgreSQL runner,
  one transaction per migration, transaction-level advisory coordination, and
  an applied-history relation under `laboratory_migration`;
- the reference pack uses a separately digest-bound manifest runner,
  session-level plan serialization, an atomic adoption group, and an
  applied-artifact relation under `migration_control`;
- the comparative-evidence repository represents target-state agreement and
  release-path agreement as independent dimensions. Its
  `aligned_target_distinct_release_path` status keeps this choice visible for
  architecture disposition;
- repository-synthetic adoption and engine-matrix receipts advance the
  executable reference. Configured vendor, migration and restore, production
  security and observability, and accountable Scientific, Quality, and
  Regulatory receipts remain the active promotion coordinates.

The promotion decision can adopt one mechanism, publish a mechanism-neutral
contract with exact history/lock/transaction semantics, or qualify both paths
with path-specific receipts.

## Evidence basis

- PostgreSQL's versioning policy recommends the current minor release for each
  supported major; the executable proof surface therefore pins PostgreSQL
  17.10 rather than an earlier 17.x image:
  <https://www.postgresql.org/support/versioning/> and
  <https://www.postgresql.org/docs/17/release-17-10.html>.
- PostgreSQL documents timezone-aware temporal storage and its special values:
  <https://www.postgresql.org/docs/current/datatype-datetime.html>.
- PostgreSQL documents interval construction from independent month, day, and
  time fields and the calendar-sensitive behavior of interval arithmetic:
  <https://www.postgresql.org/docs/current/functions-datetime.html>.
- PostgreSQL check constraints treat a null result as satisfied, while `NOT
  NULL` expresses required presence. The state and outcome branches therefore
  pair type-specific predicates with explicit presence constraints:
  <https://www.postgresql.org/docs/current/ddl-constraints.html>.
- PostgreSQL supports column-specific insertion privileges, which lets message
  producers supply identity, content, and intentional availability while
  database defaults retain initial delivery-state authority:
  <https://www.postgresql.org/docs/current/ddl-priv.html>.
- PostgreSQL documents exact `numeric` behavior, including special numeric
  values which require an explicit domain decision:
  <https://www.postgresql.org/docs/current/datatype-numeric.html>.
- PostgreSQL row-security guidance explains default-deny behavior, policy
  evaluation, owner behavior, and security-definer access:
  <https://www.postgresql.org/docs/current/ddl-rowsecurity.html>.
- PostgreSQL locking guidance supports row locks for competing writers and
  session- or transaction-level advisory locks for application-defined
  coordination: <https://www.postgresql.org/docs/current/explicit-locking.html>
  and <https://www.postgresql.org/docs/current/functions-admin.html#FUNCTIONS-ADVISORY-LOCKS>.
- The PostgreSQL project's own regression suites provide lived edge-case
  examples for row security and numeric behavior:
  <https://github.com/postgres/postgres/blob/master/src/test/regress/sql/rowsecurity.sql>
  and
  <https://github.com/postgres/postgres/blob/master/src/test/regress/sql/numeric.sql>.
- Flyway's current validation contract independently supports immutable
  versioned migrations, applied history, and checksum comparison:
  <https://documentation.red-gate.com/flyway/reference/commands/validate>.
- AWS assigns rotatable credentials to Secrets Manager and configuration to
  Parameter Store; the repository keeps this separation for database passwords
  and tenant-verification key material:
  <https://docs.aws.amazon.com/secretsmanager/latest/userguide/best-practices.html>.
