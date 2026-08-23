# PostgreSQL evolution with Flyway Community

## Ownership boundary

Flyway Community 13.0.0 owns migration discovery, ordering, locking, transaction
boundaries, applied history, checksum validation, status, and replay behavior.
`database/flyway-release.json` pins the exact open-source Alpine image by version
and multi-architecture digest. `database/flyway-artifact-inventory.json` binds
the configuration, callback, cluster-role prerequisite, and every
V001-through-V005 migration by individual SHA-256 plus an ordered aggregate
SHA-256. The release manifest binds both the
inventory file and aggregate, creating one independently reviewable release
coordinate while Flyway continues to own applied history and mechanics.
The aggregate canonicalization emits each inventory entry in listed order as
UTF-8 `path`, one NUL byte, the lowercase hexadecimal SHA-256, and one LF byte,
then hashes the complete byte stream.
`flyway.conf` keeps the operational controls in reviewable source:

- versioned migrations follow `V###__description.sql`;
- `validateOnMigrate=true` and `validateMigrationNaming=true` surface drift;
- `outOfOrder=false` preserves released order;
- `cleanDisabled=true` protects maintained environments;
- `baselineOnMigrate=false` makes adoption an explicit, attested operation;
- `group=false` gives each PostgreSQL-compatible migration its own transaction;
- `mixed=false` keeps transaction-incompatible SQL on a separately reviewed
  path.

Privileged provisioning applies `ALTER ROLE laboratory_migrator IN DATABASE
<target> SET role TO laboratory_owner`. PostgreSQL applies that database-scoped
default whenever the migrator starts a new target-database session. Every
Flyway connection therefore begins with `session_user = laboratory_migrator`
and `current_user = laboratory_owner`, including connections used to create or
inspect Flyway history. Flyway 13 discovers `sql/afterConnect.sql` immediately
after connection. This digest-bound callback verifies both identities and the
exact `pg_db_role_setting` catalog entry. It performs read-only verification on
the supported
[connection callback](https://documentation.red-gate.com/flyway/reference/callback-events)
surface. PostgreSQL documents database-scoped login defaults under
[`ALTER ROLE ... IN DATABASE`](https://www.postgresql.org/docs/17/sql-alterrole.html).

The repository owns domain SQL: PostgreSQL primitives, constraints, lineage,
row security, grants, triggers, and trusted routines. Vendor-owned LIMS/ELN
schemas continue through their supported upgrade mechanisms. Cross-platform
scientific data movement continues through vendor APIs, resumable transfer,
semantic reconciliation, and accountable acceptance.

## Runtime invocation

The repository stores zero deployable database credentials. A workload identity
or secret delivery boundary supplies `FLYWAY_URL`, the released
`laboratory_migrator` login, and its runtime credential; hosted tests use
conspicuously synthetic isolated values.
The container invocation mounts the project read-only and uses the released
configuration:

```sh
docker run --rm --network host \
  --volume "$PWD:/flyway/project:ro" \
  --env FLYWAY_URL --env FLYWAY_USER --env FLYWAY_PASSWORD \
  flyway/flyway:13.0.0-alpine@sha256:f3c8433401abf859ef9022584c8e6111684363ec490f737e749e9a4705ea32d0 \
  -workingDirectory=/flyway/project \
  -configFiles=/flyway/project/flyway.conf migrate
```

Release automation follows `migrate`, `validate`, and `info`. A second
`migrate` proves that the released head is a no-op. Flyway's
`flyway_schema_history` table is the applied-history authority.

Cluster roles live outside Flyway because they span databases. A privileged
deployment step applies `database/provision_cluster_roles.sql`, verifies the
released least-privilege attributes, and binds a distinct migrator credential.
The migrator is `LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
NOBYPASSRLS`. Its owner membership is `ADMIN FALSE, INHERIT FALSE, SET TRUE`,
matching PostgreSQL's explicit
[role-membership](https://www.postgresql.org/docs/17/role-membership.html)
model. Target database and schema creation are reserved for
`laboratory_owner`; the database-scoped startup setting selects that role on
each new migrator connection. Flyway history and domain objects consequently
belong to the owner. `RESET ROLE` selects the configured owner default. `SET
ROLE NONE` recovers the authenticated migrator's
narrow privilege set and supports an explicit direct-DDL rejection proof. The
credential can deliberately select `laboratory_owner` through its released
`SET TRUE` membership, so deployment delivers this secret only to the migration
job. The
provisioning step establishes the public-creation boundary before the first
migration runs.

The privileged prerequisite makes `laboratory_owner` the owner of the target
`public` schema. This gives the migration owner the grant authority required to
open and close V004's schema capability inside one migration transaction.

Migration 004 deliberately transfers outbox tables and trusted routines from
the general schema owner to the isolated `laboratory_outbox_authority` role.
PostgreSQL requires the acting owner to hold `SET ROLE` authority for an
ownership transfer. Provisioning therefore grants that no-login,
`NOBYPASSRLS` role to `laboratory_owner` with `ADMIN FALSE, INHERIT FALSE, SET
TRUE`. V004 completes caller ACLs and trigger definitions while the migration
owner still has authority, grants the destination owner `CREATE` on `public`,
and transfers the objects. It then selects the destination role, clears the
outbox privileges inherited with ownership, and establishes the rights
exercised by its trusted routines and semantic guards: `SELECT`, `INSERT`, and
`UPDATE` on the outbox, `SELECT` and `INSERT` on the evidence tables, and
`UPDATE` on attempt and outcome. Attempt updates reach the append-only trigger;
outcome updates support PostgreSQL's `FOR KEY SHARE` check when recovery facts
reference outcomes, while the same trigger governs attempted mutation. The
destination role also restores the exact column-level
producer grant required by the custody routine. The migration owner is selected
again before it revokes the temporary schema capability. The owner gains a
deliberate transfer operation while ordinary sessions gain zero inherited
outbox authority and the new owner retains zero schema-creation capability at
head. Static ordering checks, the connection callback, bounded-session
verifier, artifact inventory, and hosted role graph bind this exact edge.

Tenant relations retain `FORCE ROW LEVEL SECURITY` during schema and data
evolution. A permissive policy for `laboratory_owner` opens cross-tenant
maintenance only when
`laboratory_security.bounded_migration_session_active()` verifies the complete
migration coordinate: authenticated migrator, effective owner, both roles'
least-privilege attributes, exact membership options, the database-scoped
startup role, the live `role` setting, and one direct non-grantable `CONNECT`
database ACL. For that exact coordinate, the ordinary tenant function returns
SQL `NULL`, producing a total false tenant predicate while the maintenance
policy admits the migration statement. Every other coordinate retains the
explicit tenant-context exception. Runtime roles receive no execution grant on
the verifier and continue through the signed tenant policy. The migration
credential can perform cross-tenant evolution by design; its delivery boundary
and the immutable Flyway artifact set constrain that authority.

The Compose migrator service receives only `postgres_migrator_password`. The
bootstrap secret remains on the role-provisioning service. Application,
outbox, evidence, and tenant-verification secrets enter their narrower
post-migration configuration stage.

## Fresh and successor paths

The clean path provisions cluster roles, applies V001 through V005, validates,
inspects, and replays. The successor path provisions the same roles, runs
`migrate -target=003`, seeds representative pre-V004 rows, and then runs the
head migration. The head step applies V004 and V005 in order.

V004 deliberately rejects historical outbox terminal state that lacks the new
attempt and outcome ledgers. The rejection leaves Flyway history at V003 and
retains the historical row for an explicit export, attestation, conversion, or
disposition. After that disposition, Flyway applies V004 and V005 and a replay
reports zero pending work. A second clean database reaches the same schema; schema-only
comparison proves clean-versus-upgrade convergence.

The integration suite reuses the existing tenant, custody, quantity, and outbox
scenarios. It also proves:

- a stored numeric scale equals `source_scale`;
- every instrument inbox fact names an existing specimen;
- a quarantine resolution binds its original and optional accepted replacement
  to one tenant and specimen and remains append-only;
- security-invoker workbench views reuse canonical custody, measurement, vendor,
  review, and outbox state;
- a measurement binds message, specimen, raw digest, capture time, and accepted
  or replayed inbox disposition as one foreign-key lineage coordinate;
- inbox facts become append-only when measurement projection is active;
- a custody position binds tenant, specimen, resulting version, and transfer
  identity to one custody event;
- V004 failure is transactional;
- Flyway validation accepts the released checksums;
- the migrator login has bounded role attributes and `SET ROLE NONE` returns to a
  direct-DDL-rejecting privilege set;
- every migrator session starts with the released authenticated/effective
  identity pair and the callback verifies that pair plus its catalog binding;
- V002 cross-tenant backfills complete under forced RLS only through the
  catalog-verified bounded migration policy;
- application and direct-login migrator probes remain on the signed-tenant
  path and fail closed without a verified tenant context;
- Flyway history and domain relations are created as `laboratory_owner`;
- outbox state tables and trusted transition routines finish under the
  segregated `laboratory_outbox_authority` owner on clean and successor paths;
- target V003, head migration, `info`, validation, and no-op replay behave as
  one coherent release path.

`source_precision` remains producer-observed metadata. The database can verify
stored decimal scale after PostgreSQL parses the numeric value; exact source
precision also depends on the retained source lexeme or a released canonical
payload contract. ENV-INSTRUMENT-001 owns that configured-source verification.

## Existing database adoption

`baselineOnMigrate=false` keeps object-name similarity from becoming migration
evidence. Adoption uses a comparative path:

1. retain a recoverable source snapshot and record database, version, extension,
   and configuration coordinates;
2. provision a fresh target and apply the complete Flyway chain;
3. move representative data through resumable checkpoints;
4. reconcile identity, revision, JSON meaning, timestamps, quantities,
   relationships, audit facts, and artifact bytes;
5. rehearse rollback and clean restore against selected RTO and RPO; and
6. record separate Engineering, Security, Operations, Scientific, Quality, and
   Regulatory dispositions.

An existing schema receives an explicit baseline only after catalog and semantic
attestation demonstrates equivalence to the selected version. The baseline
command and its receipt belong to the environment deployment workflow. The
repository keeps automatic baselining disabled.

## V004 availability and integrity posture

V004 sets a 30-second lock-wait budget and five-minute statement and
idle-in-transaction budgets. It acquires a deterministic `ACCESS EXCLUSIVE`
lock set before its preflight across custody, inbox, measurement, and outbox
relations. A timeout rolls back and preserves V003 for a scheduled retry.

Preflight admits measurements whose stored scale and complete inbox lineage are
coherent, custody positions bound to one complete event coordinate, and outbox
rows at the initial ready/zero-attempt boundary. It then establishes the
database constraints, narrows mutation authority, and creates immutable outbox
attempt, outcome, acknowledgement, and recovery evidence.

High-volume successors use expand/validate/contract: add compatible state,
backfill through resumable bounded batches, validate constraints, move readers
and writers, observe, and retire compatibility in a later versioned migration.
Flyway continues to own the mechanics; the program continues to own scientific
meaning and release evidence.

## Promotion receipt minimum

A database promotion receipt binds:

- repository commit, Flyway release digest, Flyway version, container digest,
  and migration head;
- PostgreSQL version and extension versions;
- `validate` and `info` results plus clean, target-V003, head, and no-op outcomes;
- backup, restore, comparison, and reconciliation artifact digests;
- adversarial tenant, custody, inbox-lineage, quantity, and outbox scenarios;
- lock wait, execution duration, WAL, replica lag, and recovery observations;
- performer, independent reviewer, evidence mode, limitations, and residual
  risk; and
- separate accountable Engineering, Security, Operations, Scientific, Quality,
  and Regulatory decisions.
