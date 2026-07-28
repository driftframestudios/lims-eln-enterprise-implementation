# Qualification and acceptance boundaries

## Proof classes

### Configured vendor environments

For Sapio, Benchling, and LabKey, record the exact tenant or sandbox identifier,
vendor build, SDK, schemas, modules, permission fingerprint, feature flags,
adapter commit, fixtures, scenario IDs, results, traces, limitations, and
reviewers.

The conformance tranche includes:

- create/update/readback parity;
- exact replay and changed-content collision;
- stale revision handling;
- timeout before commit and timeout after commit;
- event duplication, lateness, and reordering where applicable;
- permission-restricted reads and writes;
- pagination, throttling, retry, and recovery;
- artifact byte parity;
- clean fixture teardown.

### Representative migration and restore

The approved profile covers volume, lineage depth, revision distribution,
custody history, result values and units, controlled vocabulary, ELN revisions,
attachments, audit events, identities, roles, retention, and exception rates.

Cutover readiness requires:

- identity, revision, relationship, semantic, audit, and artifact parity;
- measured snapshot, delta, freeze, authority transfer, and rollback timing;
- a clean-environment restore performed by one operator and witnessed by another;
- observed RTO and RPO inside approved objectives;
- a data-exit bundle that a neutral reader can reconstruct.

### Production security and observability

The evidence program exercises tenant authorization, joiner/mover/leaver timing,
separation of release and signature authority, break-glass lifecycle, credential
rotation, event replay, audit protection, protected-data redaction, telemetry
failure, queue saturation, collector recovery, and on-call response.

Every service-level indicator states its good-event numerator, valid-event
denominator, window, target, exclusions, and observed value.

### Accountable acceptance

Scientific acceptance covers specimen meaning, lineage, units, calculations,
flags, reference intervals, revisions, corrections, and downstream interpretation.

Quality acceptance covers requirements, risks, tests, raw results, deviations,
procedures, training, support, change control, and periodic review.

Regulatory acceptance determines applicability by intended use, jurisdiction,
record, and signature and reviews retention, reconstruction, inspection copies,
and signature meaning.

Each decision binds named evidence. Each approver retains the authority to
approve, approve with conditions, or return the package for additional evidence.

## Promotion rule

```text
specified → verified → qualified → validated → accepted
```

The current stage names the strongest completed evidence. Open work remains
visible through the replacement action that advances it.

