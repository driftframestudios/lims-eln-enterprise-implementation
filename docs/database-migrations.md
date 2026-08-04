# Database migrations

## Ownership boundary

Flyway Community owns migration discovery, ordering, locking, transactions,
checksums, history, validation, information, replay, and out-of-order execution.
Repository code owns the domain SQL. Application releases and database
deployments can proceed on independent cadences through compatible expand and
contract changes.

`flyway.conf` enables:

- migration-name validation;
- validation before migration;
- `outOfOrder=true` for timestamped changes merged from parallel branches;
- disabled `clean` and automatic baseline; and
- one transaction per migration.

Successor names use `VyyyyMMddHHmmss__description.sql` with UTC timestamps.
CI creates PostgreSQL 17, applies the full chain, runs `validate`, runs `info`,
replays `migrate`, and exercises the resulting schema.

## History and current state

V001 through V004 are immutable historical migrations. They contain both the
valuable data-primitive corrections and prototype control-plane structures that
were later removed from runtime. Their checksums remain stable for databases
that already applied them.

`V20260804190000__simplify_runtime_boundaries.sql` is a forward transition. It:

1. removes bounded-call, acceptance, evidence-receipt, and simulated-migration
   relations;
2. removes outbox lease, fence, attempt, outcome, and recovery machinery;
3. preserves existing outbox messages while dropping delivery-engine columns;
4. retains an insert-only outbox for Debezium capture;
5. removes the tenant HMAC key and binding protocol; and
6. retains transaction-local tenant scope for row isolation after application
   authentication.

The transition preserves specimen, event, idempotency, custody, instrument,
measurement, vendor-projection, and outbox data. Custody writes continue through
the same PostgreSQL routine, so custody event and outbox insertion remain one
transaction.

## Role provisioning

Cluster roles are provisioned outside Flyway because PostgreSQL cluster roles
sit above one application schema. `laboratory_migrator` authenticates with a
runtime secret and starts each target-database session as the no-login
`laboratory_owner`. The small `afterConnect.sql` callback confirms that login
and effective role.

Historical migrations reference outbox recovery and evidence roles, so fresh
installs provision those compatibility identities while applying V001–V004.
The current runtime grants them no application capability after the successor
migration. Application traffic uses `laboratory_app`; Debezium uses a
deployment-configured connector identity with the PostgreSQL logical-replication
privileges required by the selected hosting platform.

## Existing database adoption

`baselineOnMigrate=false` keeps object-name similarity from becoming evidence of
schema equivalence. An existing database follows this direct path:

1. retain a recoverable snapshot;
2. record PostgreSQL and extension versions;
3. apply the chain to a fresh target;
4. migrate representative tenant, specimen, custody, instrument, quantity,
   vendor, and artifact data;
5. compare keys, revisions, relationships, JSON meaning, timestamps, quantities,
   units, audit facts, and bytes; and
6. rehearse rollback and restore against the environment's RTO and RPO.

An explicit Flyway baseline becomes appropriate only after the adopting team
demonstrates catalog and semantic equivalence to the selected version.

## Expand and contract

Compatible changes follow three phases:

| Phase | Database | Application |
|---|---|---|
| Expand | Add nullable or defaulted structures and compatibility indexes. | Existing readers and writers continue. |
| Transition | Backfill bounded batches and validate constraints. | Readers move first; writers can dual-write when required. |
| Contract | Remove compatibility in a later timestamped migration. | Current readers and writers use the new contract. |

The successor simplification is a contract migration over control-plane tables
that have no canonical laboratory meaning. Its outbox portion preserves producer
facts before removing delivery-state columns.

## Operational checks

A configured migration run records ordinary platform outputs:

- Flyway `validate`, `info`, and `migrate` results;
- PostgreSQL version and extension versions;
- backup and restore results;
- row counts and reconciliation differences;
- lock duration, migration duration, WAL volume, and replica lag; and
- application compatibility during the deployment window.

These outputs live in the organization's deployment and observability systems.
The implementation repository carries executable tests and runbooks rather
than a parallel receipt platform.
