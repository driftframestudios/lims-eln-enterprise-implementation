---
name: configured-environment-evidence-binding
description: Admits one configured database, vendor, or runtime observation by binding its exact source, execution environment, scenarios, artifacts, and accountable identities. Applies when environment-dependent evidence is first recorded or when a source, tool, image, runtime, database, migration, run, or artifact coordinate changes.
source_band: public_possible
skill_version: 0.1.0
origin: repository_native
---

# Configured environment evidence binding

## Contract

- **What:** A repository-native route for admitting one configured database,
  vendor, or runtime observation as a typed, exact-coordinate receipt.
- **When:** A configured proof first runs, an existing proof is refreshed, or
  any source, tool, image, environment, scenario, artifact, run, time,
  performer, or reviewer coordinate changes.
- **Boundaries:** The route establishes what happened at the named coordinate.
  It preserves the authority of candidate, observed, verified, qualified,
  validated, accepted, and production-authorized states. It does not diagnose
  a failed run or authorize a retry; recovery routing owns those decisions.
- **Result:** The admitted receipt identifies one exact observation, its
  material coverage, its predecessor and successor boundaries, and the named
  receiver for any later assurance or production decision.

## Rules

### Rule: Bind the complete observation coordinate

Record the exact repository source and commit; dependency, tool, and container
image versions or digests; runtime, database, migration head, vendor, and other
material environment coordinates; workflow run and observation time;
performer and reviewer identities; materially distinguishing scenario IDs;
and content-addressed artifact digests. A receipt with a missing material
coordinate remains a candidate for clarification rather than admitted
evidence.

### Rule: Execute the receipt contract

Validate configured observations against
`contracts/execution-receipt.v1.1.schema.json` and the repository checks that
interpret it. For the retained PostgreSQL family,
`classify_hosted_postgresql_receipt_binding` admits only an exact known source
binding and fails closed when the repository version, commit, or correlated
coordinates are unknown or have drifted.

### Rule: Keep evidence and assurance states distinct

- **Candidate** identifies a prepared artifact or coordinate awaiting
  execution, observation, or admission.
- **Observed** means the named run occurred and produced the bound artifacts.
- **Verified** means the declared checks passed at that exact coordinate.
- **Qualified** means a named receiving authority found the evidence suitable
  for its declared use and environment.
- **Validated** means the named intended-use validation has been completed.
- **Accepted** records an accountable acceptance decision for the stated use.
- **Production-authorized** records a separate production authority decision;
  it is not implied by any earlier state, including acceptance.

Carry `evidence_mode` and `assurance_stage` as declared facts. Advance either
only through the observation or authority that owns the next state.

### Rule: Scenarios distinguish behavior

Choose scenarios that separate consequential implementation paths, such as
migration convergence, privilege boundaries, atomic event handling, fenced
worker recovery, restart and replay behavior, exact scientific quantities, and
artifact identity. A scenario count is supporting inventory; coverage comes
from the behavior each named scenario can distinguish.

### Rule: Secret evidence remains value-free

Bind the presence and role of required secret-backed configuration through
non-secret identifiers, authenticated-role names, or other repository-approved
value-free signals. Keep credentials, tokens, private keys, connection values,
and raw secret-bearing output with their protected owner. A public or
public-possible receipt carries enough information to reproduce the evidence
route without carrying the secret material itself.

### Rule: Preserve lineage in both directions

Retain an earlier admitted receipt at its original evidence and assurance
state. When a tool, image, schema, migration, or source coordinate advances,
create a new observation rather than rewriting history. State which successor
evidence remains open, including restore rehearsal, production security and
observability, accountable domain acceptance, or production authorization.

### Rule: Correlated drift remains visible

Treat a new release label paired with an unrelated commit, a changed image
without its digest, a migrated schema without its migration head, or an
artifact whose digest no longer matches as one unresolved coordinate. Fail
closed and route the smallest missing observation to its evidence owner.

## Operating sequence

1. Name the claim, intended use, receiving authority, and configured system
   whose behavior is being observed.
2. Resolve the exact source commit and every material tool, image, runtime,
   database, migration, and vendor coordinate before admission.
3. Select scenarios that distinguish the consequential behaviors for this
   observation and identify the expected artifacts.
4. Run the configured proof through its authorized environment; record the run,
   observation time, performer, independent reviewer, and artifact digests.
5. Validate the receipt schema, then execute the repository-specific binding
   checks against the exact retained coordinate.
6. Compare the result with its predecessor. Preserve the earlier receipt and
   name the material difference carried by the new observation.
7. State what the receipt establishes first, followed by its coverage boundary
   and any successor evidence or authority still required.
8. Hand the admitted receipt to the owner of the next assurance decision. If
   execution failed or coordinates cannot be resolved, hand the observed
   failure geometry to recovery routing without diagnosing or retrying here.

## Observed basis

The initial repository use staged a Flyway 13.4 configured-database candidate
under Issue #14, then admitted the hosted observation through pull request #24
only after the source commit, container image digest, Python and PostgreSQL
versions, migration head, workflow run, observation time, scenario set,
artifact digests, performer, reviewer, and successor boundaries converged. The
retained earlier receipt kept its original evidence role.

## Completion

Binding completes when the typed receipt and repository-specific checks admit
one exact configured observation; unknown and drifted coordinates remain
closed; materially distinguishing scenarios and artifact identities are
present; secrets remain with their protected owner; predecessor and successor
boundaries are explicit; and the next receiver can advance, hold, or decline
the assurance state without inferring production authority.
