# Implementation architecture

## Center

The canonical model owns specimen identity, revision, lifecycle, lineage,
custody, instrument integrity, and vendor-neutral meaning. Vendor records are
projections through a stable port. This lets an evaluation compare platforms
while keeping data exit and scientific interpretation intelligible.

```text
instrument bytes -> inbox + normalized measurement -> canonical specimen
                                                        |
                         +------------------------------+------------------+
                         |                              |                  |
                      custody                       LabKey             vendor B
                         |                              |                  |
                         +-> transactional outbox       +-> readback <----+
                                      |
                                      +-> Debezium -> broker
```

## Domain invariants

1. Tenant identity participates in every persistence and integration key.
2. A command identity binds to one canonical content digest.
3. Exact command replay returns the recorded outcome.
4. Changed content receives a new command identity or a visible collision.
5. Aggregate revisions serialize concurrent lifecycle and custody writers.
6. Instrument bytes retain their source digest through normalization.
7. Scientific quantities retain finite decimal value, observed precision and
   scale, released unit code and system, and source lineage.
8. Custody state points to the complete append-only event that produced it.
9. External timeout ambiguity resolves through authoritative readback before a
   second write becomes eligible.
10. Domain changes and cross-service events commit in one database transaction.
11. Operational rates retain their good-event numerator, valid-event
    denominator, window, and target.
12. Applied schema migrations retain Flyway identity and checksum history.

## Transaction boundaries

`LifecycleService` composes aggregate mutation, domain event, and command
idempotency through one injected atomic executor. `CustodyService` composes the
position, custody event, and outbox message through one executor. The
PostgreSQL `record_custody_transfer` routine supplies the durable custody
compare-and-set and outbox transaction.

The in-memory executors are domain-test adapters. They demonstrate rollback at
the service seam; Flyway and the configured PostgreSQL integration tests prove
the production database behavior. Migration rehearsal belongs to Flyway plus
environment-specific migration tooling rather than a second in-memory
migration product.

## Tenant scope

Application authentication and tenant authorization happen in the selected
deployment identity layer. Once authorized, the database adapter sets one
transaction-local `app.tenant_id`. PostgreSQL row policies use that coordinate
as defense against accidental cross-tenant queries. The coordinate is an
isolation guard and carries no independent authorization meaning.

This posture replaces the prototype's database HMAC capability protocol. It
keeps the reference focused while allowing an adopting system to use its
existing OIDC, IAM, service-mesh, or vendor identity controls.

## Cross-service events

The active outbox is append-only producer data. It contains an event identity,
topic, aggregate identity and revision, tenant, JSON payload, payload digest,
canonicalization profile, and database timestamp. Runtime roles can insert and
read; they cannot update or delete.

Debezium's Outbox Event Router maps these columns to broker key, topic, payload,
and headers. Debezium owns log capture, offsets, publication retries, and
connector restart behavior. Broker-level dead-letter and retention policy stay
with the configured event platform.

## Vendor boundaries

`VendorGateway` separates domain meaning from provider APIs. The concrete
adapter checks its SDK and API versions, provides bounded read retry through
Tenacity, classifies ambiguous writes, verifies readback identity, and traverses
bounded pagination. The LabKey client demonstrates the port through documented
query endpoints and an injected credential-bearing transport.

Vendor selection adds configured-environment tests for API versions, schemas,
permissions, throttling, pagination, artifact transfer, and data exit. These
tests extend the port; they do not require a second internal workflow engine.

## Framework boundaries

| Concern | Selected implementation |
|---|---|
| Database evolution | Flyway Community |
| Runtime model validation | Pydantic |
| Vendor read retry | Tenacity |
| AWS configuration and secrets | AWS Powertools Parameters |
| Cross-service event capture | Debezium Outbox Event Router |
| Telemetry | OpenTelemetry |
| Repository branch controls | GitHub Rulesets |

`machine-node.json` remains a documentation-only map for collaborators. Runtime
packages, migration validation, and deployment authorization do not import it.
