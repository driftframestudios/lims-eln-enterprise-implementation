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
| B. Migration-first vertical integrity | Freeze the baseline; add checksum-bound migrations, trusted tenant context, typed quantities, custody CAS/history, immutable outbox content, and live adversarial tests. | **0.80** | Connects each primitive to authority, transaction, recovery, and evidence. | Requires a representative upgrade rehearsal and operating ownership. |
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
| DP-001 | Schema creation depended on a Docker initialization directory. An existing database had no ordered upgrade mechanism or applied-history checksum. | **Corrected.** `database/migration-manifest.json` binds the runner and SQL files. The runner supplies strict order, SHA-256 drift detection, append-only applied history, transaction ownership, and a transaction-level advisory lock. | Static drift tests pass. A live PostgreSQL 17 job applies the chain from empty state. A representative populated upgrade remains ENV-DB-001. |
| DP-002 | The original row policies trusted caller-set `app.tenant_id`. Any role able to issue SQL could select another tenant value before a query. | **Corrected.** Migration 002 replaces every policy with a database-verified, short-lived HMAC assertion. The verification key is private to `laboratory_security`; workload roles receive zero key-table privilege. | Adversarial live tests cover unsigned, expired, and tenant-tampered assertions plus legacy-GUC irrelevance. Production issuer, key rotation, and revocation receipts remain SEC-CTX-001. |
| DP-003 | Python outbox replay used `message_id` alone, so two tenants sharing a source identifier collapsed into one message. Changed content also returned as though it were an exact replay. | **Corrected.** Identity is `(tenant_id, message_id)` and changed semantic content raises a reviewable collision. | Unit tests cover cross-tenant reuse, exact replay, and changed content. |
| DP-004 | The in-memory outbox retained only a caller-supplied digest. A downstream worker lacked the immutable payload needed to publish or reconcile the event. | **Corrected.** `OutboxMessage` snapshots full canonical payload JSON and derives its digest from that snapshot. Custody publishes the full transfer fact. | Mutation, rollback, replay, and content-collision tests pass. |
| DP-005 | SQL grants allowed the application and worker to update every outbox column. Payload, aggregate identity, and digest could drift after commit. | **Corrected.** Insert-time digest verification, an immutable-content trigger, column-level worker grants, coherent state checks, and a tenant-led queue index preserve message meaning. | Live owner-level mutation and tenant-scoped identity proofs run in CI. Worker lease/fencing crash-point qualification remains ENV-OUTBOX-001. |
| DP-006 | Custody persistence performed an unconditional last-write-wins save and kept only current position. A stale writer could replace a valid transfer and the audit trail could disappear. | **Corrected.** Both conformance and SQL models use expected-version CAS, tenant-scoped transfer idempotency, append-only history, and one atomic outbox transaction. | Unit tests cover stale writers, exact replay, changed transfer content, history, and rollback. Live PostgreSQL covers CAS, replay, history, and outbox atomicity. |
| DP-007 | Instrument JSON accepted JavaScript numeric extensions such as `NaN`, coerced structured analytes with `str()`, and left precision and scale implicit. | **Corrected.** Ingress uses exact `Decimal` parsing, duplicate-member detection, finite-value checks, a 38/18 released profile, explicit analyte shape, bounded payload size, and UCUM-coded units. | Negative tests cover non-finite, duplicate, structured, Boolean, over-scale, additional-field, and unsupported-unit cases. Scientific range qualification remains SCI-QTY-001. |
| DP-008 | Normalized measurements existed only as JSON digest material. SQL had no exact quantity primitive for scientific query, validation, or export. | **Corrected.** `instrument_measurement` stores an exact unconstrained `numeric` with explicit 20-integer-digit, 18-fractional-digit, and finite-value checks. This avoids typmod rounding before validation. It also stores source precision/scale, analyte code, UCUM system/code, raw and normalized digests, finite timestamps, tenant identity, and inbox lineage. | Static policy and schema checks pass. Configured instrument-to-measurement persistence remains ENV-INSTRUMENT-001. |
| DP-009 | `Command.content_digest` was recomputed from caller-owned nested payload objects. Mutation after construction could change authorization and replay meaning. | **Corrected.** Commands now retain recursively immutable JSON snapshots and construction-time digests. | A nested-mutation regression test passes. |
| DP-010 | A suspected text representation for `updated_at_utc` was checked. In this repository the column was already `timestamptz`; all baseline operational dates use temporal types. | **Verified conforming, then strengthened.** Migration 002 adds finite-time checks because PostgreSQL timestamp types intentionally admit infinity. | Schema checks and the PostgreSQL 17 migration job are the current evidence. |
| DP-011 | Several state machines used independent nullable columns whose combinations were only partially constrained. | **Partially corrected.** Idempotency, instrument disposition, outbox delivery, and evidence JSON shapes now have coherence checks. | Lifecycle-wide property and transition testing remains DATA-STATE-001. |
| DP-012 | Canonical JSON digests depend on an explicit byte representation. PostgreSQL `jsonb::text` and Python sorted compact JSON are different canonicalization profiles. | **Corrected at each boundary.** Python messages name their canonical snapshot implicitly through code release; SQL records `postgresql-jsonb-text-v1` and verifies its digest in the database. | A cross-language canonicalization contract or RFC 8785 adoption remains DATA-CANON-001 before messages cross runtimes by digest alone. |
| DP-013 | Broad `text` identifiers allow values whose length and vocabulary vary across tables. Text itself is a sound PostgreSQL primitive; missing domain bounds are the risk. | **Open by design.** New signed-context, custody-function, analyte, and measurement inputs are bounded. | DATA-ID-001 will inventory every identifier, select durable external/local identity semantics, and add constraints through expand/validate/contract migrations. |
| DP-014 | `specimen.canonical_document` and several evidence documents remain JSONB. Their digests and schemas are application-governed rather than fully database-governed. | **Open with containment.** Object/array shape gates were added where meaning is stable. | DATA-JSON-001 will decide per field among generated typed columns, JSON Schema at ingress, or a decomposed relational model. |
| DP-015 | The database accepts a specimen document and its supplied SHA-256 without independently deriving the same canonical bytes. | **Open.** Cross-runtime canonicalization needs a released algorithm before a trigger can prove equality. | DATA-CANON-001 owns the algorithm decision and corpus of Unicode, decimal, ordering, and normalization vectors. |
| DP-016 | Migration 002 adds checks which intentionally surface incoherent legacy rows. An untracked populated baseline cannot be safely adopted from object names alone. | **Open environment receipt.** The supported posture is restore into a fresh migrated database, compare semantic and artifact digests, then cut over. | ENV-DB-001 records preflight counts, constraint exceptions, lock time, rollback timing, restore parity, and accountable approval. |
| DP-017 | A signed tenant assertion is a bearer capability which can be replayed during its short validity window. The nonce provides unique signed content and currently has no consumption ledger. | **Open with containment.** The 15-minute maximum lifetime, TLS, narrow issuer, private verification key, per-statement expiry check, and database audit boundary limit exposure. | SEC-CTX-002 decides whether configured risk calls for shorter lifetimes, channel binding, a replay ledger, or sender-constrained credentials. |
| DP-018 | Tenant authorization and accountable actor attribution are separate concerns. The signed context carries a subject, while custody currently accepts a custodian identifier as domain input. | **Open with explicit ownership.** The bounded-caller layer verifies actor/delegation and persists attributable receipts; the database independently enforces tenant scope. | AUTH-ACTOR-001 will bind actor/delegation evidence to database mutations where the configured threat model requires database-level verification. |

## Recommended chain of action and interstitials

1. **Freeze and bind.** Preserve migration 001 byte-for-byte and require the
   manifest checksum in repository validation. Interstitial: checksum drift or
   an unlisted SQL file returns the tranche to design.
2. **Rehearse from empty.** Apply 001 and 002 through the runner on PostgreSQL
   17, then rerun to prove exact no-op replay. Interstitial: inspect locks,
   duration, warnings, roles, extensions, and applied-history rows.
3. **Rehearse with representative state.** Restore a synthetic-but-shaped
   populated baseline into an isolated source; migrate a fresh target; compare
   identities, quantities, relationships, audit events, artifacts, and digests.
   Interstitial: any exception becomes a named migration disposition.
4. **Exercise adversaries.** Run tenant-forgery, stale custody, outbox mutation,
   malformed quantity, key revocation, concurrent runner, and crash-point
   scenarios. Interstitial: update probability from the observed pass/fail and
   severity distribution.
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

## Evidence basis

- PostgreSQL's versioning policy recommends the current minor release for each
  supported major; the executable proof surface therefore pins PostgreSQL
  17.10 rather than an earlier 17.x image:
  <https://www.postgresql.org/support/versioning/> and
  <https://www.postgresql.org/docs/17/release-17-10.html>.
- PostgreSQL 17 documents timezone-aware temporal storage and its special
  values: <https://www.postgresql.org/docs/17/datatype-datetime.html>.
- PostgreSQL documents exact `numeric` behavior, including special numeric
  values which require an explicit domain decision:
  <https://www.postgresql.org/docs/17/datatype-numeric.html>.
- PostgreSQL row-security guidance explains default-deny behavior, policy
  evaluation, owner behavior, and security-definer access:
  <https://www.postgresql.org/docs/17/ddl-rowsecurity.html>.
- PostgreSQL locking guidance supports row locks for competing writers and
  transaction-level advisory locks for application-defined coordination:
  <https://www.postgresql.org/docs/17/explicit-locking.html>.
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
