# Changelog

## Unreleased — principal data boundaries

- Delegate PostgreSQL migration ordering, locking, transactions, history,
  checksum validation, status, target selection, and replay to the
  version-and-digest-pinned Flyway Community 13.0.0 image.
- Keep cluster-role provisioning outside Flyway and resolve database credentials
  only through runtime secret boundaries.
- Authenticate Flyway through a constrained, non-inheriting migrator login;
  select the no-login schema owner through a database-scoped startup setting;
  and verify the authenticated identity, effective identity, and exact catalog
  binding in a digest-bound connection callback.
- Keep forced row-level security active during cross-tenant evolution and open
  the maintenance path only for the catalog-verified bounded migration session.
- Preserve the segregated outbox ownership boundary through a SET-only,
  non-inheriting, non-admin owner-to-outbox-authority membership; bind the role
  edge, transaction-bounded schema capability, and final table and routine
  owners on clean and successor paths.
- Publish a digest inventory for the Flyway configuration, connection callback,
  cluster-role prerequisite, and every migration; pin all Compose support
  images; and constrain the
  container build context and local-secret exclusions.
- Replace caller-selected tenant state with short-lived signed assertions which
  PostgreSQL verifies against private key material.
- Add finite temporal constraints, exact decimal instrument measurements,
  UCUM-coded units, and raw-to-normalized lineage.
- Add custody compare-and-set, tenant-scoped transfer replay, append-only event
  history, schema-qualified privileged execution, and atomic full-payload outbox
  insertion.
- Bind outbox identity to tenant, verify payload digests at insertion, preserve
  message content through delivery, and govern worker claim, expired-lease
  reclaim, and confirmation through exact tenant/token/fence compare-and-set
  functions with 1-through-900 integer-second lease authority.
- Complete the outbox transition matrix, narrow initial-state insertion,
  separate recovery release authority, and preserve append-only attempt,
  outcome, transport-acknowledgement, and recovery evidence.
- Align message identity bounds across producer and worker paths, and require a
  locked initial-ready provenance boundary before attempt ledgers begin, with
  bounded migration wait and statement budgets.
- Bind measurement scale to the stored numeric value, bind complete inbox
  lineage through one composite foreign key, make projected inbox facts
  append-only, and bind custody positions to complete custody-event coordinates.
- Reuse the PostgreSQL integration scenarios for Flyway target V003, transactional
  V004 rejection, head migration, validation, information, no-op replay, and
  clean-versus-upgrade schema convergence.
- Add the bounded Golden Specimen Workbench with visible call receipts, distinct
  grant-bound scientific and Quality actors, and a separate recovery operation.
- Add V005 instrument-review resolution and security-invoker workbench views
  over the canonical custody and measurement facts.
- Add live, digest-pinned PostgreSQL 17 migration and adversarial data-boundary
  proofs to CI.
- Publish the data-primitive corrective ledger, plan probabilities, remaining
  gaps, interstitials, and upgrade receipt requirements.

## 0.3.1 — 2026-07-28

- Route the golden specimen journey through the bounded caller.
- Fail closed on in-progress lifecycle and vendor reservations.
- Add rollback-capable atomic reference seams for state and evidence.
- Add least-privilege PostgreSQL identities, tenant-scoped acceptance evidence,
  and leased outbox recovery state.
- Bind acceptance to one intended use and release claim.
- Harden AWS response binding and runtime-value log redaction.
- Add a credential-free LabKey JSON API exemplar with bounded reads and pagination.
- Strengthen migration parity, package validation, and the stable CI aggregate.
- Migrate orientation and evidence bindings to governance 2.0.1 and the corrected
  canonical selected-future closure.
- Make the stable implementation aggregate run on every outcome and fail when any
  proof-matrix member differs from success.

## 0.3.0 — 2026-07-28

- Added a typed bounded-caller boundary with task-scoped grants, tenant and
  resource scope, request budgets, exact independent approvals, durable replay
  seams, and attributable call receipts.
- Added service-owned read, idempotent narrow-write, and approval-gated
  broad-write operations with explicit governance effect-class mappings.
- Added version-banded PostgreSQL receipt persistence and vendor SDK adapter
  seams with explicit connection and client lifecycle handling.
- Bound broad approvals to one call and immutable operation contract; evaluated
  expiry and revocation against service time; and canonicalized payload and
  replay snapshots at ingress.
- Added fenced, leased PostgreSQL invocation state plus receipt provenance for
  operation contracts, invocation digests, grants, budget windows, and request
  time. Vendor confirmation mismatches and post-write cleanup enter
  authoritative reconciliation as ambiguous outcomes.
- Added governance schema release 2.0.0 Machine Node, first receipt, and
  Coordination Horizon surfaces. The earlier Machine Node remains documented
  seed lineage under `release/`.
- Added digest-bound source and release manifests, canonical receipt-family
  names, and a separate observed-successor ledger for the four substantive
  receipt families.
- Bound the implementation to the fully closed selected-future simulation
  while preserving environment-observed qualification and organizational
  acceptance as independent evidence.
- Added bot-identity-bound Dependabot and Renovate branch flows, grouped
  GitHub Actions maintenance, and regression coverage for spoofed, malformed,
  partial, and wrong-target coordinates.
- Moved branch-policy execution to base-controlled source and expanded code
  ownership across dependency automation, authority, release, and orientation
  surfaces.
- Snapshotted every authority-bearing container at construction and added
  mutation regressions for grants, budgets, payloads, and resource scopes.
- Added the DB-API PostgreSQL invocation ledger with lease-expiry and
  fencing-token compare-and-set transitions, completed replay, durable recovery
  ownership, and deterministic adapter tests.
- Routed ambiguous write failures to authoritative reconciliation and released
  pre-effect reservations when authorization-receipt persistence fails.
- Restricted qualified driver and SDK versions to complete released
  `major.minor.patch` coordinates.

## 0.2.0 — 2026-07-28

- Added an account- and Region-scoped runtime setting catalog.
- Added dependency-free Parameter Store and Secrets Manager client ports with
  version selectors, bounded caching, explicit refresh, safe errors, and a
  logging redaction guard.
- Added least-privilege Terraform resources and an operational rotation runbook.
- Added repository credential-hygiene and AWS-policy validation.
- Forced tenant row-level security across every tenant-bearing table and added
  a verified transaction-local tenant binding plus migration-admin runbook.
- Recorded immutable container digest qualification as a medium open receipt.

## 0.1.0 — 2026-07-28

- Established the actual-implementation repository boundary.
- Added canonical specimen, custody, instrument, vendor, migration, recovery,
  security, observability, and acceptance services.
- Added versioned contracts, synthetic fixtures, durable SQL, AWS recovery
  baseline, operational runbooks, and GitFlow-like delivery guidance.
- Added a standard-library validation surface and comprehensive unit tests.
- Preserved source provenance from the merged enterprise reference pack.
