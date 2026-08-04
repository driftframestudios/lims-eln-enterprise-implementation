# Runbook — migration, cutover, rollback, and restore

## Entry criteria

- intended use and authority map approved;
- representative profile approved by scientific, data, Quality, and operations owners;
- source and target versions frozen;
- semantic and artifact parity queries rehearsed;
- RTO, RPO, freeze window, rollback threshold, and decision owner named;
- clean restore environment and witness scheduled.

## Rehearsal

1. Assume the approved migration workload identity and its dedicated database
   role. The repository role remains `NOBYPASSRLS`, receives a signed tenant
   context for each partition, produces session audit events, and remains
   separate from application and interactive identities. Schema DDL uses the
   separately controlled bootstrap identity through the checksum-bound runner.
2. Record source snapshot identity, tenant partitions, and counts.
3. Export canonical records, revisions, relationships, audits, signatures, and
   artifacts with checksums.
4. Load resumably from stable checkpoints while each work item carries its
   explicit tenant identity.
5. Capture collisions as reviewable exceptions.
6. Apply delta changes and measure lag.
7. Reconcile identity, revision, payload, relationships, audit, and byte parity
   within every tenant partition and across the aggregate totals.
8. Exercise a controlled rollback before authority transfer.
9. Restore the snapshot into the clean environment.
10. Run the same reconciliation against the restored system.
11. Produce a neutral data-exit bundle and reconstruct selected cases.
12. Close the privileged database session, expire the assumed workload session,
    and reconcile its CloudTrail and database audit events.

## Tenant session boundary

Ordinary application and worker roles remain subject to forced row-level
security. Each database transaction begins by calling
`PostgresTenantBinding.bind()`, which submits a parameterized, short-lived
signed assertion. PostgreSQL verifies its exact fields, active private key,
validity window, and signature, then returns the authorized tenant. Connections
return to the pool after transaction completion.

Tenant-by-tenant migration and restore work uses the signed path above. A
separately governed administrative extraction or restore identity can hold
cross-tenant authority when the approved recovery procedure requires it. That
identity sits outside ordinary runtime and has time-bounded workload access.
The change record names the operator, reviewer, scope, source and target
snapshots, tenants, start and expiry times, and recovery owner. Database and
CloudTrail audit records become receipt artifacts. Application identities
retain forced RLS as their constitutive posture throughout the rehearsal.

## Decision

The cutover owner selects:

- `proceed` when all critical invariants hold and residual exceptions carry
  approved dispositions;
- `proceed_with_conditions` when bounded conditions have owners and expiry;
- `return_for_evidence` when the source system should retain authority while
  the team resolves parity, timing, recovery, or acceptance questions.

## Receipt

Bind source/target versions, fixture profile, volume, timings, counts, semantic
digests, artifact digests, exception ledger, operator, witness, approvals, and
limitations.
