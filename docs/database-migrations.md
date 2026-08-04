# PostgreSQL migration and upgrade posture

## Released contract

`database/migration-manifest.json` is the ordered source of truth. Each entry
binds an identifier, repository path, SHA-256 checksum, and transaction mode.
The same manifest binds the migration runner's own path and SHA-256 checksum.
`scripts/apply_database_migrations.py` verifies the runner and entire sequence
before it contacts PostgreSQL. It then:

1. creates a private applied-history table;
2. acquires one transaction-level advisory lock;
3. compares any applied identifier with its released path and checksum;
4. applies each pending file in one owned transaction; and
5. records actor and database time only after the migration statements succeed.

Applied versioned files retain their bytes. A correction is a new ordered
migration. Repository validation treats checksum drift and unlisted SQL as
release failures.

Verify files locally:

```sh
python3 scripts/apply_database_migrations.py --verify-only
```

Apply to an explicitly selected database:

```sh
python3 scripts/apply_database_migrations.py --dsn "$LIMS_DATABASE_DSN"
```

The DSN comes from the runtime secret boundary. Shell history, command output,
and repository files remain value-free. The local Compose path reads its
bootstrap password and tenant-verification key from mounted secret files.

## Fresh environment

The migrator starts after PostgreSQL health succeeds. Application proof starts
after the migrator exits successfully. Re-running the migrator verifies applied
checksums and performs an exact no-op for each released migration.

CI exercises two independent paths. The fresh path applies migrations 001
through 004 and replays the current manifest. The successor path applies the
checksum-bound `database/migration-manifest-through-003.json`, then applies 004
and replays the current manifest. This keeps the already-released migration 003
bytes visible while proving the forward-repair path.

The bootstrap identity owns schema change. Application, outbox, evidence, and
migration workload roles remain `NOSUPERUSER NOBYPASSRLS`; ordinary runtime
connections receive their own narrow grants.

## Existing untracked baseline

Object-name similarity is insufficient evidence that a populated database is
exactly migration 001. The supported adoption path is comparative:

1. retain a recoverable source snapshot and record its database/version/configuration coordinates;
2. provision a fresh target and apply the complete released migration chain;
3. migrate or restore representative data through resumable checkpoints;
4. reconcile identity, revision, JSON meaning, timestamps, quantities,
   relationships, audit events, and artifact bytes;
5. exercise rollback and restore timing; and
6. cut over only after separate Engineering, Security, Operations, Scientific,
   Quality, and Regulatory dispositions are recorded.

An operator can choose an independently reviewed baseline-adoption mechanism
in a successor migration tool. This reference requires deliberate
reconciliation before an existing database can be marked as migration 001;
partial and hand-edited schemas receive an explicit disposition.

## Lock and availability posture

Migration 002 introduces constraints, policies, tables, triggers, grants, and a
backfill of outbox digests and existing custody positions. Migration 003 requires
a drained outbox lease set before it records the invoking database principal,
replaces direct worker updates with fenced functions, and replaces the privileged
custody function with schema-qualified execution. Migration 004 retains those
published bytes and requires another drained-lease, state-coherence gate before
it changes ownership, grants, routine signatures, state guards, and evidence
relations. The worker supplies 1 through 900 integer seconds; the database
constructs the interval, so calendar-relative month and day fields remain
outside the caller-controlled lease boundary. Immutable attempt, outcome,
transport-receipt, and recovery-release rows establish the transition evidence.
Several `ALTER TABLE`
forms can take strong locks. A populated-environment rehearsal records:

- row and byte counts per affected table;
- constraint exception counts before the change;
- ready, leased, delivered, and recovery-required outbox counts, with a zero
  active-lease gate for migrations 003 and 004;
- expected and observed lock modes and wait time;
- transaction duration, WAL growth, replica lag, and storage headroom;
- application compatibility before, during, and after the change;
- rollback and clean-restore time; and
- semantic and artifact parity after restore.

Future high-volume changes use expand/validate/contract: add compatible nullable
state, backfill in resumable bounded batches, attach or validate constraints,
move readers and writers, observe, then retire the compatibility surface in a
later release.

## Forward repair

A failed transactional migration rolls back as one unit. Once a migration is
recorded as applied, its bytes remain fixed. A newly discovered defect receives
a successor forward-repair migration. Database restoration remains available
for environment recovery and release rollback when the wider system decision
requires it.

## Tenant verification key lifecycle

The database verifies short-lived tenant assertions with an HMAC key stored in
the private `laboratory_security` schema. Runtime roles can execute verification
and have zero direct key-table privilege. A configured issuer holds signing
authority outside the application process.

Production rotation uses a successor key identifier, overlapping validity,
issuer switchover, expiry observation, and revocation of the predecessor. Key
material belongs in AWS Secrets Manager with workload identity, narrow resource
ARNs, audit events, and a separately rehearsed rotation path. The SQL table is a
verification projection populated by the protected deployment control plane.

## Receipt minimum

A database promotion receipt binds:

- repository commit and migration-manifest digest;
- PostgreSQL image or service version and extension versions;
- source and target schema heads;
- backup, restore, and comparison artifact digests;
- adversarial tenant, custody, outbox, and quantity scenario results;
- lock, duration, WAL, lag, and recovery observations;
- performer and independent reviewer;
- evidence mode, assurance stage, limitations, and residual risk; and
- separate accountable decisions for Engineering, Security, Operations,
  Scientific, Quality, and Regulatory concerns.
