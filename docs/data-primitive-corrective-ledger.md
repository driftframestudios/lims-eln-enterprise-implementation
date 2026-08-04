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
| B. Custom migration-first vertical integrity | Build checksum history, locking, ordering, replay, trusted tenant context, typed quantities, custody CAS/history, governed outbox leases, and live adversarial tests inside the repository. | 0.58 | Connects each primitive to authority, transaction, recovery, and evidence. | Duplicates a mature migration product and diverts review toward non-differentiating mechanics. |
| C. Flyway-owned evolution with domain-owned SQL | Use Flyway Community for history, checksums, locking, transactions, status, and replay; keep primitives, lineage, RLS, and scientific acceptance in the repository. | **0.90** | Applies an industry-tested ownership boundary while preserving the valuable domain corrections and tests. | Explicit baseline attestation and configured-environment receipts still require program judgment. |
| D. Shadow database and dual-read comparison | Build the corrected schema beside the current system, replay representative data, compare semantic digests, then cut over. | 0.74 | Produces powerful comparative evidence and a recoverable cutover. | Doubles operational surfaces and requires explicit conflict ownership. |
| E. Full canonical-model decomposition | Replace broad JSON documents and free-form identifiers with domain tables, reference vocabularies, and temporal history in one program. | 0.57 | Maximizes relational expressiveness. | Broad simultaneous change raises migration, scientific-validation, and delivery risk. |

The selected synthesis uses Plan C as the spine, Plan B's domain integrity
corrections and adversarial tests, Plan D's restore-and-compare rehearsal, and
Plan E only where a primitive has stable scientific meaning. JSON remains useful
at versioned ingress and evidence boundaries; canonical scientific quantities
also have a typed relational representation. These estimates are structured
planning beliefs under the stated one-cycle conditions rather than measured
frequencies.

## Finding ledger

| ID | Observed condition and material effect | Disposition | Evidence or next gate |
|---|---|---|---|
| DP-001 | Schema creation depended on a Docker initialization directory. The first correction then recreated migration history, checksums, locking, ordering, transactions, and replay in a repository-specific Python runner. | **Corrected with a mature ownership boundary.** Flyway Community 13.0.0 owns migration mechanics through a version-and-digest-pinned open-source image. Repository SQL retains domain constraints and forward repairs. Cluster roles run in a separate privileged step, while runtime credentials resolve from the secret boundary. | Static tests bind the Flyway configuration and immutable V003 bytes. Hosted proof exercises clean migration, target V003, transactional V004 rejection, head migration, `validate`, `info`, no-op replay, and clean-versus-upgrade convergence. ENV-DB-001 remains the configured active-environment receipt. |
| DP-002 | The original row policies trusted caller-set `app.tenant_id`. Any role able to issue SQL could select another tenant value before a query. | **Corrected.** Migration 002 replaces every policy with a database-verified, short-lived HMAC assertion. The verification key is private to `laboratory_security`; workload roles receive zero key-table privilege. | Adversarial live tests cover unsigned, expired, and tenant-tampered assertions plus legacy-GUC irrelevance. Production issuer, key rotation, and revocation receipts remain SEC-CTX-001. |
| DP-003 | Python outbox replay used `message_id` alone, so two tenants sharing a source identifier collapsed into one message. Changed content also returned as though it were an exact replay. | **Corrected.** Identity is `(tenant_id, message_id)` and changed semantic content raises a reviewable collision. | Unit tests cover cross-tenant reuse, exact replay, and changed content. |
| DP-004 | The in-memory outbox retained only a caller-supplied digest. A downstream worker lacked the immutable payload needed to publish or reconcile the event. | **Corrected.** `OutboxMessage` snapshots full canonical payload JSON and derives its digest from that snapshot. Custody publishes the full transfer fact. | Mutation, rollback, replay, and content-collision tests pass. |
| DP-005 | SQL grants allowed the application and worker to update every outbox column. Payload, aggregate identity, digest, and delivery coordinates could drift after commit. | **Corrected.** Insert-time digest verification and an immutable-content trigger preserve message meaning. Migration 003 removes direct worker mutation and exposes tenant-bound claim, expired-lease reclaim, and confirmation functions. Each lease records the invoking database principal and worker-instance label, rotates a UUID, advances attempts and a monotonic fence, and confirms through an exact unexpired compare-and-set coordinate. A transition trigger and state checks preserve legal movement independently of caller SQL. | Static grants and function-shape checks plus live PostgreSQL prove direct-update rejection, claim, simulated crash expiry, fenced reclaim, stale-worker rejection, and current-worker completion. ENV-OUTBOX-001 remains the configured throughput, broker, crash-process, recovery-alert, and operating-owner qualification receipt. |
| DP-006 | Custody persistence performed an unconditional last-write-wins save and kept only current position. A stale writer could replace a valid transfer and the audit trail could disappear. | **Corrected.** Both conformance and SQL models use expected-version CAS, tenant-scoped transfer idempotency, append-only history, and one atomic outbox transaction. | Unit tests cover stale writers, exact replay, changed transfer content, history, and rollback. Live PostgreSQL covers CAS, replay, history, and outbox atomicity. |
| DP-007 | Instrument JSON accepted JavaScript numeric extensions such as `NaN`, coerced structured analytes with `str()`, and left precision and scale implicit. | **Corrected.** Ingress uses exact `Decimal` parsing, duplicate-member detection, finite-value checks, a 38/18 released profile, explicit analyte shape, bounded payload size, and UCUM-coded units. | Negative tests cover non-finite, duplicate, structured, Boolean, over-scale, additional-field, and unsupported-unit cases. Scientific range qualification remains SCI-QTY-001. |
| DP-008 | Normalized measurements existed only as JSON digest material. SQL had no exact quantity primitive for scientific query, validation, or export. | **Corrected with an explicit residual boundary.** `instrument_measurement` stores exact unconstrained `numeric` values with 20-integer-digit, 18-fractional-digit, and finite-value checks. Stored scale is database-verifiable. Source precision remains producer-observed metadata because PostgreSQL parsing cannot reconstruct every lexical detail such as exponent form or leading zeros. | Static and live checks cover the numeric profile and stored scale. Retained source lexeme or canonical-payload verification remains ENV-INSTRUMENT-001. |
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
| DP-025 | `instrument_measurement.source_scale` could disagree with the scale PostgreSQL retained for `quantity`, allowing metadata and scientific value to tell different stories. | **Corrected in V004.** Preflight requires existing coherence and a named check enforces `source_scale = scale(quantity)` for every successor row. | The existing scientific-quantity integration scenario now retains exact-scale success and adds a direct mismatched-scale rejection. Source precision remains producer-observed as documented under DP-008. |
| DP-026 | Independent foreign keys allowed a measurement to cite inbox message A while supplying specimen, raw digest, capture time, or disposition from another fact. An inbox row could also change after measurement projection. | **Corrected in V004.** One composite foreign key binds tenant, message, specimen, raw digest, capture time, and accepted/replayed disposition. Inbox facts become append-only and application/migration workload roles lose direct update authority. | Reused integration setup adds adversarial raw-digest, capture-time, disposition, and stored-scale cases. Configured instrument authenticity and source-lexeme qualification remain ENV-INSTRUMENT-001. |
| DP-027 | `custody_position.last_transfer_id` referenced an event by tenant and transfer only, so position specimen and version were independent of the referenced event coordinate. | **Corrected in V004.** The position now references tenant, specimen, custody version, and transfer identity against one unique custody-event key. Preflight rejects a legacy mismatch before constraints change. | The existing custody CAS/replay scenario now attempts a cross-specimen event substitution and observes the composite foreign-key rejection. |
| DP-028 | The first Flyway transition authenticated the migration container with the cluster bootstrap role. That credential carried cluster-scoped authority beyond schema evolution and collapsed provisioning and migration into one runtime identity. A connection-callback role change then proved too narrow because Flyway can open a separate connection while creating history. | **Corrected at the deployment boundary.** Flyway authenticates as `laboratory_migrator`, a `LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS` role with a distinct secret. `ADMIN FALSE, INHERIT FALSE, SET TRUE` membership permits the no-login `laboratory_owner`. Privileged provisioning stores `role=laboratory_owner` for this login and target database, so PostgreSQL applies the owner identity at every new session. A digest-bound `afterConnect.sql` callback verifies `session_user`, `current_user`, and the exact catalog setting. Required database and schema creation privileges live on the owner; the bootstrap credential remains in the cluster-role stage. | Static proofs bind the callback digest, catalog-setting SQL, Compose secret separation, role grant options, and Flyway user. Hosted PostgreSQL proves the startup identity pair, direct-DDL rejection after `SET ROLE NONE`, successful history creation across Flyway connections, and owner attribution for both Flyway history and domain tables. The migration credential can deliberately select the owner by design and therefore remains scoped to the migration workload. |
| DP-029 | Moving from the cluster bootstrap identity to a non-superuser migration owner caused V002's cross-tenant custody backfill to meet forced row-level security and request an application tenant assertion. Disabling forced RLS or granting `BYPASSRLS` would hide the migration authority instead of naming it. | **Corrected through an explicit maintenance policy.** Tenant tables retain `FORCE ROW LEVEL SECURITY`. A permissive `laboratory_owner` policy calls a security-invoker verifier that returns true only for the complete bounded migration coordinate: `session_user=laboratory_migrator`, `current_user=laboratory_owner`, live `role=laboratory_owner`, released role attributes, exact `ADMIN FALSE, INHERIT FALSE, SET TRUE` membership, exact target-database startup role, and one direct non-grantable `CONNECT` database ACL. For this coordinate alone, the ordinary tenant function returns SQL `NULL`; every other coordinate retains explicit tenant-context validation. Runtime roles receive no verifier execution grant. The policy is present before V002's first backfill and accompanies later tenant tables. | Static proofs enumerate every session/catalog predicate and forced-RLS tenant table. Hosted Flyway applies the V002 backfill and sees all synthetic tenants. An application call to the verifier is rejected, an application call through a `laboratory_owner` `SECURITY DEFINER` routine still requires signed context, and `SET ROLE NONE` returns the migration connection to the direct login whose cross-tenant read requires signed tenant context. Clean, target-V003, V004, replay, and convergence paths reuse the same policy. |
| DP-030 | V004 assigns outbox state relations and trusted transition routines to `laboratory_outbox_authority`. PostgreSQL requires the acting owner to be able to `SET ROLE` to a new owner and requires the new owner to hold `CREATE` on the containing schema. The first transfer sequence moved tables before completing ACL statements. The next ordering pass completed ACLs first, while explicit revokes on the old owner left the transferred authority without the ordinary DML needed by its security-definer routines; the old owner's self-grant also ceased to supply the custody producer path after transfer. The first explicit settlement then reached recovery insertion and showed that PostgreSQL's foreign-key `FOR KEY SHARE` check also requires `UPDATE` on its referenced outcome table. | **Corrected with one ordered transfer and settlement boundary.** Cluster provisioning grants `laboratory_outbox_authority` to `laboratory_owner` with `ADMIN FALSE, INHERIT FALSE, SET TRUE`; both roles remain `NOLOGIN NOBYPASSRLS`. V004 completes caller ACLs and trigger definitions under `laboratory_owner`, opens the destination's schema capability, and transfers the four tables and six trusted routines. It selects the destination role, clears the outbox privileges inherited with ownership, and grants only the operations exercised by the routines and guards: outbox `SELECT`, `INSERT`, and `UPDATE`; evidence-table `SELECT` and `INSERT`; and `UPDATE` on attempt and outcome for append-only trigger proofs and foreign-key row locking. It grants the former owner the exact outbox insert columns used by custody, selects `laboratory_owner` again, and revokes schema `CREATE` in the same Flyway transaction. | Static tests bind role options and the complete order from ACLs through transfer, narrow DML settlement, producer re-grant, owner restoration, and capability withdrawal. Hosted clean and V003→V004 proofs apply V004, exercise custody and the outbox transition suite, and assert final ownership, operation-level privileges, exact producer-column access, and absence of schema `CREATE`. Clean-versus-upgrade comparison preserves schema convergence. |

## Recommended chain of action and interstitials

1. **Delegate mechanics.** Pin Flyway Community by version and container digest;
   retain validation, strict ordering, clean protection, and explicit baseline
   adoption in source. Provision cluster roles separately. Interstitial: a
   migration naming, checksum, product-version, image-digest, or configuration
   difference returns the tranche to review.
2. **Rehearse from empty.** Apply V001 through V004 through Flyway on PostgreSQL
   17, run `validate` and `info`, then rerun `migrate` to prove no-op replay.
   Interstitial: inspect Flyway history, locks, duration, warnings, roles,
   extensions, and release coordinates before comparing results.
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
   quantity-scale and inbox-lineage mismatch, custody-event mismatch, key
   revocation, concurrent migration, and crash-point scenarios.
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

The active implementation and reference pack share the intended scientific and
tenancy invariants while the migration-mechanics convergence remains explicit:

- the active implementation now delegates ordering, locking, transactions,
  applied history, checksum validation, status, and replay to Flyway Community;
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

The wider constellation can converge the reference pack on Flyway in a bounded
successor tranche while retaining its adoption and reconciliation tests. This
implementation repository records the corrected ownership boundary now.

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
- Flyway documents `migrate`, `info`, and transaction handling as product-owned
  behavior:
  <https://documentation.red-gate.com/flyway/reference/commands/migrate>,
  <https://documentation.red-gate.com/flyway/reference/commands/info>, and
  <https://documentation.red-gate.com/fd/migration-transaction-handling-273973399.html>.
- AWS assigns rotatable credentials to Secrets Manager and configuration to
  Parameter Store; the repository keeps this separation for database passwords
  and tenant-verification key material:
  <https://docs.aws.amazon.com/secretsmanager/latest/userguide/best-practices.html>.
