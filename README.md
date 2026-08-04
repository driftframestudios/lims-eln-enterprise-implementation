# LIMS/ELN Enterprise Implementation

This repository is the executable member of a LIMS/ELN vendor-evaluation
constellation. It concentrates on the parts that materially affect laboratory
data portability and integration: canonical specimen identity, lifecycle,
custody, instrument ingress, exact scientific quantities, vendor projections,
PostgreSQL data primitives, schema evolution, and cross-service events.

## Executable scope

- Tenant-scoped specimen lifecycle with optimistic revisions and idempotent
  commands.
- Custody compare-and-set transitions with append-only history.
- Byte-preserving instrument ingress, finite decimal quantities, UCUM unit
  codes, source precision and scale, and explainable quarantine.
- Vendor-neutral ports plus an executable LabKey JSON API adapter.
- Authoritative readback after ambiguous vendor writes.
- PostgreSQL 17 constraints and row isolation exercised against a real database.
- Flyway Community migrations with timestamp successors, validation,
  transaction ownership, immutable history, and out-of-order execution.
- One append-only transactional outbox captured by Debezium's Outbox Event
  Router.
- Parameter Store and Secrets Manager references resolved by AWS Powertools
  Parameters through workload identity.
- OpenTelemetry-compatible metrics, logs, traces, and protected-field redaction.

The repository models engineering behavior. A selected vendor deployment owns
authentication, organization policy, scientific review, Quality procedures,
Regulatory applicability, and production release in its established systems.

## Architecture

```text
instrument bytes -> canonical specimen -> scientific review
                         |                      |
                         v                      v
                  custody + event       vendor projection
                         |
                         v
              append-only PostgreSQL outbox
                         |
                         v
             Debezium Outbox Event Router
```

Domain changes and their outbox rows share one PostgreSQL transaction. Debezium
owns change capture, offsets, Kafka publication, and connector recovery. The
deployment supplies its connector, broker, credentials, TLS, topic policy, and
monitoring. See [cross-service events](docs/outbox.md).

## Database evolution

The four legacy migrations remain immutable Flyway history. The timestamped
successor migration moves the active schema to the simpler runtime posture:

- canonical laboratory relations remain;
- bounded-caller, modeled-acceptance, receipt, and migration-simulation tables
  leave the active schema;
- the signed HMAC tenant protocol becomes one transaction-local tenant scope
  set after application authentication; and
- outbox lease, fence, attempt, and recovery tables leave the active schema in
  favor of Debezium capture from immutable inserts.

Flyway owns discovery, ordering, locking, checksums, history, validation,
information, replay, and out-of-order application. Schema deployment proceeds
independently from application releases. See
[database migrations](docs/database-migrations.md) and the
[data primitive corrective ledger](docs/data-primitive-corrective-ledger.md).

## Vendor evaluation

Every selected vendor adapter implements the same material boundary:

1. write from an expected external revision with a stable request identity;
2. classify the result as confirmed or ambiguous;
3. read authoritative state after an ambiguous result;
4. verify tenant, external identity, revision, and canonical digest; and
5. expose version and pagination behavior for configured-environment testing.

The LabKey exemplar keeps credentials in its injected transport and exercises
documented query APIs. Sapio, Benchling, or another selected platform can use
the same port without changing canonical laboratory meaning.

## Runtime configuration

Terraform creates named Parameter Store values, value-free Secrets Manager
metadata, KMS encryption, and exact-resource IAM read policy. AWS Powertools
Parameters supplies provider access, caching, transforms, and provider errors.
The application carries resource identities; the platform supplies workload
credentials. See the
[AWS runtime settings runbook](docs/runbooks/aws-runtime-configuration-and-secret-rotation.md).

## Repository map

- `src/lims_eln_implementation` — domain and vendor integration code.
- `sql` — immutable Flyway history and timestamped successor migrations.
- `database` — Flyway release metadata and migration-compatible role setup.
- `infra/debezium` — Outbox Event Router transformation settings.
- `infra/terraform` — Parameter Store, Secrets Manager, KMS, and IAM.
- `fixtures/synthetic` — invented, stable comparison examples.
- `tests` — unit, schema-posture, and configured PostgreSQL integration tests.
- `machine-node.json` — documentation-only collaboration orientation.
- `docs/quarantine` — framework destinations for removed prototype concepts.

## Verify

Use Python 3.12 or 3.13:

```sh
python -m pip install -e '.[dev]'
make validate
make test
make build
```

CI also provisions PostgreSQL 17, applies and validates the Flyway chain, and
proves tenant-scoped custody plus outbox atomicity against the resulting schema.
Repository rules and required checks belong in GitHub Rulesets.

## Collaboration orientation

[`machine-node.json`](machine-node.json) remains available as a hydration and
way-finding artifact. It has no runtime import, validation gate, digest binding,
or authorization effect. The
[framework-backing map](docs/quarantine/framework-backing-map.md) preserves
useful concerns from the quarantined prototypes and names mature frameworks to
adopt when an observed requirement calls for them.
