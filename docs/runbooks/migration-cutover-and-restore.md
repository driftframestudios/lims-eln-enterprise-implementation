# Runbook — migration, cutover, rollback, and restore

## Entry criteria

- intended use and authority map approved;
- representative profile approved by scientific, data, Quality, and operations owners;
- source and target versions frozen;
- semantic and artifact parity queries rehearsed;
- RTO, RPO, freeze window, rollback threshold, and decision owner named;
- clean restore environment and witness scheduled.

## Rehearsal

1. Record source snapshot identity and counts.
2. Export canonical records, revisions, relationships, audits, signatures, and
   artifacts with checksums.
3. Load resumably from stable checkpoints.
4. Capture collisions as reviewable exceptions.
5. Apply delta changes and measure lag.
6. Reconcile identity, revision, payload, relationships, audit, and byte parity.
7. Exercise a controlled rollback before authority transfer.
8. Restore the snapshot into the clean environment.
9. Run the same reconciliation against the restored system.
10. Produce a neutral data-exit bundle and reconstruct selected cases.

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

