# Runbook — migration, cutover, rollback, and restore

## Entry criteria

- intended use and authority map approved;
- representative profile approved by scientific, data, Quality, and operations owners;
- source and target versions frozen;
- semantic and artifact parity queries rehearsed;
- RTO, RPO, freeze window, rollback threshold, and decision owner named;
- clean restore environment and witness scheduled.

## Rehearsal

1. Assume the approved migration workload role and its dedicated database role.
   The role carries time-bounded `BYPASSRLS` authority, produces session audit
   events, and remains separate from application and interactive identities.
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
`PostgresTenantBinding.bind()`, which uses a parameterized,
transaction-local `app.tenant_id` setting and verifies the returned value.
Connections return to the pool after transaction completion.

Cross-tenant migration and restore work uses the named migration path above.
Its `BYPASSRLS` capability exists only on the dedicated database role and is
reachable through the approved, time-bounded workload identity. The change
record names the operator, reviewer, scope, source and target snapshots,
tenants, start and expiry times, and recovery owner. Database and CloudTrail
audit records become receipt artifacts. Application identities retain forced
RLS as their constitutive posture throughout the rehearsal.

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
