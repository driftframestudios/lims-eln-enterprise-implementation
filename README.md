# LIMS/ELN Enterprise Implementation

This repository is the **actual-implementation member** of the comparative
Site Reading constellation. It provides a principal-level Python reference
system for specimen lifecycle, custody, instrument ingress, vendor projection,
migration, recovery, evidence, security, and operational acceptance.

The repository begins from the public architectural provenance of
`driftframestudios/prototype-exemplars` pull request
[#3](https://github.com/driftframestudios/prototype-exemplars/pull/3):

- source head: `8be1e2c2ce239e51dcd5d1e19d1ff52e9d080b72`;
- merged result: `613f524821a25389748a9cd98d1bb0d303de87cf`;
- source validation floor: 69 synthetic tests on Python 3.12 and 3.13.

This implementation is independently evolved. Runtime code stays within this
repository and consumes versioned contracts rather than simulation code.

## What runs

The standard-library test suite exercises:

- tenant-bound, attributable, revision-checked specimen transitions;
- exact replay and changed-content collision handling;
- custody transfer with an atomic outbox plan;
- byte-preserving instrument ingress and explainable quarantine;
- ambiguous vendor-write reconciliation through authoritative readback;
- resumable migration, semantic reconciliation, rollback, restore, and data exit;
- allowlisted telemetry with recursive sensitive-value replacement;
- service-level indicators with explicit numerator and denominator;
- scientific, Quality, and Regulatory acceptance as separate accountable acts.

Run the complete local proof:

```sh
python3 scripts/validate_repository.py
```

The command validates JSON contracts and manifests, confirms fixture posture,
runs all tests, applies the negation-aware language gate, and emits a
deterministic source digest.

## Evidence ladder

| Stage | Meaning |
|---|---|
| `specified` | A versioned claim, example, and acceptance criterion exist. |
| `verified` | Automated local evidence demonstrates the claim with synthetic fixtures. |
| `qualified` | The named environment and configuration passed the receipt contract. |
| `validated` | The configured system demonstrated fitness for its stated intended use. |
| `accepted` | Named accountable owners approved the bounded use and residual risk. |

Execution and acceptance remain separate dimensions. Local verification creates
a strong proof floor. Configured-vendor qualification, representative migration
and restore rehearsals, production security and observability, and accountable
scientific, Quality, and Regulatory decisions require environment-bound,
date-bound receipts.

## Repository map

- `src/lims_eln_implementation` — canonical domain and application services.
- `contracts` — versioned machine-readable command and receipt contracts.
- `fixtures/synthetic` — synthetic, stable examples for comparison.
- `sql` — PostgreSQL persistence, inbox/outbox, evidence, and tenant controls.
- `infra` — local production-shape services and an AWS recovery baseline.
- `docs` — architecture, GitFlow-like delivery, qualification, and runbooks.
- `receipts` — example manifests whose evidence mode is explicit.
- `scripts` — one-command repository validation.

## Data and authority boundaries

Fixtures carry the `SYN-` namespace and contain invented laboratory values.
Patient data, customer tenant payloads, credentials, and production telemetry
belong in approved operational systems. When an input contains a protected
field, repository examples replace its value with `[REDACTED]` and preserve the
field name for diagnostic utility.

This repository supplies engineering evidence. Scientific meaning, Quality
fitness, Regulatory applicability, and production authorization remain
separate decisions by named accountable owners.

