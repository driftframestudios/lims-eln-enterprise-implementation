# Quarantined control-plane concepts

The former bounded-caller, acceptance-board, receipt, migration-simulation,
branch-validator, and outbox-recovery implementations are outside the runtime.
Git history preserves their complete source. This page retains the useful
questions and routes each one to an established implementation when an observed
requirement justifies adoption.

| Concern retained from the prototype | Framework or managed service | Adoption trigger |
|---|---|---|
| Typed request validation | Pydantic models at HTTP, queue, and vendor boundaries | A deployed API or consumer receives untrusted documents. |
| Workload authentication and authorization | Deployment identity provider plus cloud IAM; vendor-native permissions at vendor boundaries | A selected hosting and identity architecture names the authenticating principal and policy owner. |
| Idempotent commands | PostgreSQL unique constraints and the existing domain idempotency ledger | A material write can be delivered more than once. |
| Safe read retry | Tenacity around vendor reads | The vendor documents retryable failures and a bounded latency budget exists. |
| Long-running orchestration | Temporal, AWS Step Functions, or the selected vendor workflow engine | A real workflow crosses transactions or services and needs durable timers or compensation. |
| Cross-service domain events | Transactional outbox plus Debezium Outbox Event Router | A selected integration requires asynchronous delivery from committed domain changes. |
| Runtime configuration and secrets | AWS Powertools Parameters backed by Parameter Store and Secrets Manager | The AWS deployment binds exact resource names and workload IAM. |
| Traces, metrics, and logs | OpenTelemetry SDK and Collector | A deployment names its backend, sampling, retention, and sensitive-field policy. |
| Branch and merge controls | GitHub Rulesets and required checks | Repository administrators apply the policy to protected branches. |
| Database evolution | Flyway `migrate`, `validate`, `info`, timestamp versions, and out-of-order execution | A schema change is ready for a PostgreSQL integration test. |
| Scientific or Quality acceptance | The selected organization's QMS/eQMS | Named people, intended use, and accountable procedures exist outside this reference implementation. |

The map is a visitor hub for collaborators: start with the concern, visit the
established framework, and return with configured-environment evidence. It is
documentation rather than an executable dispatcher or authority model.
