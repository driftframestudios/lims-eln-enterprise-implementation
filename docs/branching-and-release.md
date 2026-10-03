# GitFlow-like branching and release

## Long-lived branches

- `main` contains released, receipt-bound versions.
- `develop` is the lean integration branch for the next release and remains
  deployable to the shared qualification environment.

## Short-lived branches

| Pattern | Starts from | Returns to | Purpose |
|---|---|---|---|
| `feature/<claim-or-receipt>` | `develop` | `develop` | Capability, specification, test, or receipt work |
| `fix/<claim-or-receipt>` | `develop` | `develop` | Correction to the current development carrier |
| `chore/<bounded-maintenance>` | `develop` | `develop` | Bounded repository maintenance |
| `release/<semver>` | `develop` | `main` and `develop` | Frozen release candidate and evidence assembly |
| `hotfix/<receipt-id>` | `main` | `main` and `develop` | Production correction with bounded evidence |
| `experiment/<question>` | `develop` | `develop` when promoted, or archived tag | Time-boxed exploration with an explicit learning record |
| `forecast/<year>-q<quarter>-r<revision>` | `develop` | `develop` | Versioned planning evidence ready to enter the living carrier |
| `evidence/<claim-or-receipt>` | `develop` | `develop` | Observed evidence and its exact binding |

## Local and hosted proof

`python3 scripts/validate_repository.py` is the standing repository proof.
The repository allocates 100–300 hosted runner minutes per month. One
read-only, cancellable Python 3.12 proof accompanies pull requests into
`develop` and `main`. The manually dispatched `implementation-proof` preserves
the two-version and PostgreSQL evidence for a named receiver who sets
`ENABLE_GITHUB_ACTIONS=true` and selects `confirm_run`.

`.github/dependabot.yml` supplies monthly version updates into `develop` with a
two-open-pull-request limit for each configured ecosystem. Minor and patch
updates share a reviewable group when available. Maintenance branches retain
their bounded coordinate contract:

- Dependabot uses the complete
  `dependabot/<ecosystem>/<dependency-update>` grammar and the
  `dependabot[bot]` pull-request identity.
- Renovate uses the complete `renovate/<dependency-update>` grammar and the
  `renovate[bot]` pull-request identity.
- Dependabot version updates target `develop`; default-branch security updates
  retain their `main` route. Renovate retains its reviewed `main` or `develop`
  target. Branch grammar, bot identity, and target agree.

Each maintenance pull request continues through local validation, human review,
and the ordinary merge controls. The repository-local branch checker remains a
review aid. Its checker, tests, dependency-activation template, bounded-caller
sources, release manifests, and governance orientation surfaces retain explicit
ownership. Default-branch security updates are merged forward to `develop` so
both long-lived branches retain the correction.

## Repository-owned inspection identity

`release/public-inspection-manifest.json` records the exact repository bytes
in the post-release development carrier. Its `release_subject` names the
immutable v0.3.2 tag object and accepted source coordinate separately. The
current inventory carries the exact Flyway 13.8.1 source and its observed
hosted database receipt without adding those post-release bytes to the signed
release subject. The
ordered inventory covers runtime source,
Flyway V001 through V005, local contracts and synthetic inputs, consequential
behavior proofs, operational configuration, evidence records, and public
orientation. The root manifest and release-role manifest carry the current
inventory SHA-256. The immutable candidate receipt retains the earlier candidate
inventory SHA-256 and remains outside the inventory. The promotion-observation
receipt sits inside the current inventory and binds the accepted release to
that candidate, so the content-addressed route stays acyclic.

Run `python3 scripts/build_public_inspection_manifest.py --check` to establish
that every selected path, file size, file digest, group digest, and aggregate
identity matches the working tree. A source change receives a regenerated
inventory in the same reviewed change.

The signed annotated `v0.3.1` tag identifies the prior accepted source release.
Its later evidence commit carries
[`receipts/promotion-receipt.json`](../receipts/promotion-receipt.json), which
records the tag object, accepted commit and tree, tagged archive SHA-256,
hosted checks, merge and tag signature results, and where human approval was
recorded alongside GitHub's review state. This ordering lets the receipt
observe an already immutable release. The
[`receipts/promotion-candidate.json`](../receipts/promotion-candidate.json)
surface separately binds the reviewed 0.3.2 inventory and accepted
selected-future closure. The
[`receipts/promotion-observation-v0.3.2.json`](../receipts/promotion-observation-v0.3.2.json)
surface records the accepted 0.3.2 subject, successful hosted validation, valid
merge and tag verifications, configured ordinary bypass, and deputized
independent review. The repository-owned inspection state also carries the
accepted Program and Governance Git
coordinates through
[`release/external-contract-coordinates.json`](../release/external-contract-coordinates.json).
The Program binding includes its exact package source digest and clean Python
3.12 consumer observation. The Governance binding includes its annotated tag
object, commit, tree, and archive digest. The Simulation and Comparative
bindings identify the two signed sources that reproduce the canonical
selected-future closure. Configured-system observations remain
in evidence receipts with their environment and assurance boundaries, so
release assembly can examine each authority independently.

## Pull-request review material

Every pull request carries:

- stable claim and scenario IDs;
- success, failure twin, and recovery evidence;
- data-classification and privacy effect;
- migration and compatibility effect;
- operational signal and denominator;
- explicit assurance stage and limitations;
- independent engineering review.

Paths under `contracts/`, `sql/`, `infra/`, `security`, `migration`, `receipts/`,
and `acceptance` receive domain-specific review.

## Release sequence

1. Cut `release/<version>` from a passing `develop`.
2. Freeze contract and fixture digests.
3. Run repository validation and the source-owned synthetic database proof,
   then bind each observed result to the exact candidate.
4. Keep configured-vendor, representative migration/restore,
   production-shape security/observability, and accountable Scientific,
   Quality, and Regulatory encounters with their named successor receipts and
   environment owners.
5. Receive the required human and code-owner review for the source release.
6. Merge the accepted release to `main` and create the signed annotated
   `v<version>` tag at that accepted commit.
7. Record the observed tag object, commit, tree, archive digest, checks,
   signatures, and review boundary in a later evidence commit.
8. Merge the complete release result back to `develop`.
9. Publish the release manifest, source digest, evidence locators, and open receipts.

Git approval is an engineering act. Each organizational acceptance appears in
its own signed decision record.

## Branch protection target

Configure the GitHub ruleset for `main` so that:

- `main` receives pull requests and the bounded pull-request proof after
  repository settings activate it;
- each pull request receives one approval, including code-owner review where a
  covered path changes;
- changes without an attributed author receive the configured extra approval;
- stale approvals are dismissed, the last push receives approval from another
  contributor, and review threads reach resolution;
- deletion and non-fast-forward protections preserve branch history;
- merge, squash, and rebase merge methods remain available;
- contract, fixture, migration, security, and expected-result changes receive
  an independent reviewer;
- the manual full-proof workflow retains read-only permission, the repository-variable
  gate, dispatch confirmation, and a bounded timeout;
- any later reusable workflow is caller-owned and pinned by immutable commit SHA.

The current release-role manifest keeps required hosted contexts empty and
records the successful `Repository validation` job that accompanied pull
request 27. The configured ordinary bypass admitted the merge after deputized
independent review; GitHub's review collection records no formal submitted
review for that pull request. Deletion and non-fast-forward protections remain
recorded separately, and GitHub reports valid verification for the accepted
merge and release tag.

`develop` remains a lean integration branch. Pull requests into `develop` can
still receive the bounded proof, while the `main` ruleset carries release
protection. `release/<version>` remains a short-lived route from `develop` to
`main` and back to `develop` after acceptance.
