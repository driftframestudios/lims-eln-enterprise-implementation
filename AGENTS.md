# Enterprise Implementation collaboration ground

This repository owns the executable LIMS/ELN reference implementation and its
bounded evidence. Make changes here when runtime behavior, database evolution,
configured-environment evidence, or the implementation member's collaboration
surface needs to change.

## Begin with current source

- Run `git status --short --branch` and read the latest local and remote
  history.
- Read [`README.md`](README.md),
  [`release/repository-role.json`](release/repository-role.json),
  [`machine-node.json`](machine-node.json),
  [`first-receipt.json`](first-receipt.json), and
  [`COORDINATION-HORIZON.json`](COORDINATION-HORIZON.json) before changing
  implementation or evidence behavior.
- Treat runnable source and tests as behavior authority. Treat the signed tag
  and promotion observation as accepted-release evidence. Treat configured
  receipts as observations of their named source and environment.
- Preserve unrelated work already present in the worktree.

Use [`repository-reentry`](.agents/skills/repository-reentry/SKILL.md) when
branch, release, living coordination, configured evidence, and current source
need one reliable starting point.

Use
[`source-authority-mapping`](.agents/skills/source-authority-mapping/SKILL.md)
when a claim crosses Program or Governance contracts, implementation source,
configured observations, selected-future evidence, release records, or a
receiving comparison.

Use
[`proportionate-recovery-routing`](.agents/skills/proportionate-recovery-routing/SKILL.md)
when a failed check, repeated attempt, stale handoff, unavailable source, or
authority mismatch prevents reliable continuation.

Use
[`configured-environment-evidence-binding`](.agents/skills/configured-environment-evidence-binding/SKILL.md)
when a database, vendor, or runtime result has returned and its exact source,
environment, artifact, and assurance reach need to be admitted.

Use
[`contextual-jargon-scan`](.agents/skills/contextual-jargon-scan/SKILL.md) in
stride when public or cross-repository prose may assume local context. Keep
exact code, schema, scientific, regulatory, version, and evidence terms; define
useful compact language and revise shorthand whose object or consequence is
unclear.

These five skills begin as public-possible while repository use and review
establish whether each has a settled public-ready reader job. Source band is a
maturity signal rather than a confidentiality boundary; skills can be
inventoried, published, and refined in public view.

## Keep execution and authority legible

- Program and Governance repositories retain authority for their versioned
  contracts. This repository owns the implementation and its configured
  observations.
- Bind a configured result to the exact repository commit, dependency and
  image coordinates, runtime and database versions, migration head, run,
  scenarios, artifacts, time, performer, reviewer, and declared limitations.
- Keep `verified`, `qualified`, `validated`, `accepted`, and production
  authorization as distinct states. A successful run establishes only its
  named evidence reach.
- Keep simulated selected-future closure and observed configured evidence in
  their separate routes. Each remains inspectable without replacing the other.
- Preserve signed releases and historical candidate receipts. Regenerate the
  living public-inspection manifest from source when a selected current file
  changes.
- Keep credentials, secret values, raw protected output, and private locators
  with their authorized owners. Durable receipts carry value-free identities
  and the smallest decision-changing result.

## Use the accepted branch route

- `main` contains released implementation baselines; `develop` integrates the
  next implementation state.
- Begin bounded work from `develop` on `feature/`, `fix/`, `chore/`,
  `experiment/`, `forecast/`, or `evidence/`, then return it to `develop`
  through review.
- Form `release/<semver>` from `develop` for a release candidate. Form
  `hotfix/<receipt-id>` from `main` for a production correction, then merge the
  accepted result forward into `develop`.
- Let the executable branch checker resolve the complete bot and branch
  contract when a maintenance route differs from ordinary contributor work.

## Write toward the workable state

- Lead with the behavior a collaborator can create or verify.
- Pair a safety, privacy, scope, or authority boundary with the affirmative
  behavior that keeps the implementation useful.
- Use ordinary language around exact technical and regulated terms. Define
  repository shorthand where it first changes a reader's decision.
- State what an observation establishes before its coverage boundary.
- Keep personal attribution in the repository's approved carriers. Commit,
  Issue, pull-request, and review prose stays focused on the change.

## Validate material behavior

Use the configured Python 3.12 environment for the complete source-owned
proof:

```sh
python3 scripts/validate_repository.py
python3 scripts/build_public_inspection_manifest.py --check
python3 scripts/check_branch_flow.py --base develop --head <branch> --author <login>
git diff --check
```

Configured database and vendor exercises retain their own explicit activation,
environment, and secret boundaries. Local skips make that boundary visible;
they do not become evidence that the configured path ran.

## Close with one clear receiver

Return the changed source, the smallest observation that establishes its
behavior, the observation's reach and limit, and the repository or accountable
role that can make the next decision. Name the exact event that reopens a
waiting route.
