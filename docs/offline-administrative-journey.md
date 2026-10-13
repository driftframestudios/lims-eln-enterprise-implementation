# Explore an insurance and administrative comparison locally

The offline journey combines a versioned insurance catalog, exact and ambiguous
label lookup, reviewed synthetic policy inputs, and paired output observations.
It uses packaged synthetic examples and an authored proposal adapter. A local
run produces a complete JSON document through standard output.

From an isolated environment with this repository and its exact reviewed
`contracts` dependency installed:

```sh
python -m lims_eln_implementation.administrative
```

## Read the result

- `study` preserves every planned arm, actual output and expected outcome.
- `comparison` reports changed and unchanged output text, complete denominators
  and comparability findings.
- `classification_proposals` preserves the original label beside catalog terms.
- `reviewed_policy_evaluations` exercises the existing Program policy-input
  profile against independently authored, reviewed synthetic records.

One authored scenario deliberately changes its scientific summary. Another
returns an unchanged summary after an administrative input change. These controls
exercise the harness; observed model behavior is a later, separately executed
study. Population effects and substantive scoring retain their own evidence.

Insurance descriptions and diagnosis-code reportability occupy separate maps.
The small diagnosis vocabulary is authored for the example. Official vocabulary
intake belongs to a source/version/rights-reviewed catalog extension.

## Reuse the components

`CatalogSnapshot` owns immutable exact-term, alias and code indexes.
`PreparedPolicy` prepares one source-owned ruleset and evaluates its predicates
without mutating the inputs. Policy input material comes from Program's existing
review-aware helper. Classification proposals retain their pending review state;
the policy example uses already reviewed inputs from the same declared context.
Each run binds its raw insurance label, reviewed source digests, service date,
and diagnosis-code metadata. The two scenarios use different reviewed contexts;
within each pair, diagnosis-code reportability changes while source evidence
stays fixed. The small alias catalog may leave a complex source label unknown;
its fresh proposal and the fixture's existing reviewed classification remain
distinct records.

Policy replay retains the fixture's recorded evaluation time within its source
policy interval. Study observations record the current execution time separately.
Code selection follows the declared reportability factor. Overlapping policy
rules retain declaration order; the policy's precedence selects a winner when
its conflict behavior permits assignment.

`ProposalPort` allows a later local or approved provider adapter to receive the
same immutable run. One journey uses a fixed declared execution identity, checked
before and after each proposal call, including handled failures. Observable
identity drift stops the journey with `proposal_identity_changed`; an unreadable
or invalid identity uses `proposal_identity_unavailable`. The affected reserved
attempt remains held for explicit recovery, and earlier retained results remain
available. These guards establish declared identity stability; execution-specific
provider evidence belongs to the separately authorized adapter route. The command
chooses only the offline implementation and has no endpoint or credential
settings. External execution remains held.

`OfflineReplayLedger` is bounded and owned by one executor. Reusing a ledger
preserves complete results, including classification and policy companions.
Changed input/configuration requires a new tenant/run identity. Timeout,
abstention, cancellation, invalid responses, and adapter failures retain their
first attempt and replay it; this entry performs one attempt per planned run.
Capacity is reserved before execution. Interruption after reservation keeps
that run held as `replay_attempt_unsettled` for explicit recovery. A new process
starts a new local ledger. Durable
restart, concurrent writers and a live FHIR capability probe retain their named
implementation and configured-evidence routes in Enterprise #36/#37.

## Scope and recovery

Artifact review and generator/source lineage establish synthetic provenance.
The CLI admits only the packaged example; real-person records remain outside
this repository's intake. Domain failures use fixed recovery codes and retain
source data with the caller. The existing Golden Specimen workbench, database
credentials, released receipts and publication settings retain their roles.

Program #71 owns study meaning. Simulation #38 owns larger independent scenario
packs, Comparative #41 owns measured effects, and Governance #38 owns assurance.
Source acceptance, main promotion, release tags and publication remain separate.
