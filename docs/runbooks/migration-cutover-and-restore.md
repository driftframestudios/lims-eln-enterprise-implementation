# Migration cutover and restore

## Preparation

1. Select representative tenants, specimen lifecycles, custody depth,
   instrument messages, quantities, units, vendor records, and artifacts.
2. Record source and target versions, extensions, schemas, and export tools.
3. Create a recoverable source snapshot and verify restoration in an isolated
   target.
4. Apply the Flyway chain to a fresh PostgreSQL target.
5. Establish measured RTO, RPO, cutover window, and rollback point.

## Rehearsal

1. Export through the vendor-supported interface.
2. Load tenant-scoped batches with stable source identities.
3. Compare row identities, revisions, relationships, JSON meaning, timestamps,
   decimals, units, audit facts, and artifact bytes.
4. Repeat the load to prove idempotent outcomes.
5. Apply captured deltas and measure convergence time.
6. Exercise application reads and representative writes on the target.
7. Roll back to the retained snapshot and measure recovery.
8. Restore a clean target and repeat the comparison.

## Cutover

Freeze source writes for the measured final-delta window, apply the delta,
complete reconciliation, switch application configuration, and observe domain
and integration health. The source remains recoverable through the selected
rollback window.

## Outputs

- Flyway `validate`, `info`, and `migrate` output;
- source and target row and artifact counts;
- semantic differences with disposition;
- snapshot, delta, cutover, rollback, and restore durations;
- RTO and RPO results; and
- monitoring, incident, and support references in the organization's existing
  operational systems.
