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
available. Escaping interruptions retain their original exception and exit status;
their reserved attempts stay held for explicit recovery. These guards establish
declared identity stability for completed call handling; execution-specific
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

## Carry a reviewed proposal into policy evaluation

The reviewed journey connects a fresh classification to the policy inputs that
actually determine the result:

```bash
python -m lims_eln_implementation.administrative.reviewed_journey
```

The contracts-enabled environment described above supplies Program's typed
models. This entry uses one packaged, authored two-arm example. Review records
are fixture data; an operational receiver supplies its own accountable review
and admission boundary.

| Input and review | Accepted classification | Policy result |
| --- | --- | --- |
| `Commercial`, accepted | Commercial | `policy-outcome:standard_processing` |
| `Commercial + community support bridge`, explicitly revised to both catalog terms | Commercial and Supplemental | `policy-outcome:manual_review` |

Both arms retain the same scientific output. The result contains accepted
classification JSON, proposal/context/catalog/reviewer lineage, policy input
and evaluation identities, and Program's separate interpretation companion.
The companion reports one planned pair, two usable outputs, and one eligible
pair under declared-input comparison. Its expected-pair coverage is zero: the
independent expected policy outcomes live in the focused tests, while the study
itself carries no embedded expected-pair record. A stricter analysis profile can
require those records explicitly.

### Revise a source while retaining the last accepted value

`accept_classification(proposal, context, catalog, request)` is a pure
transition. `ClassificationReviewRequest` names the exact proposal digest,
context digest, catalog binding, and Program `AccountableReview`. An `accept`
action preserves the proposed standing. A `revise` action selects exact catalog
term identities. Unknown, ambiguous, and abstained values retain their distinct
meanings when accepted as such.

The caller retains the earlier `ReviewedClassification` while preparing a
successor. A changed raw label, source identity, context, or catalog requires a
new bound review request. `AdministrativeBoundaryError.code` identifies the
recovery boundary; an unsuccessful transition leaves the earlier immutable
value available. Persisted classification JSON uses Program's existing schema.
The small transition wrapper is process-local.

`evaluate_reviewed_classification` reproduces the transition against its current
sources before evaluation. Service day, evaluation time, review time, policy
version, context effectivity, and jurisdiction each retain a separate check.
The semantic evaluation identifier stays stable across equivalent inputs;
`evaluated_at` records the occurrence. The existing replay ledger binds the
complete run input and adapter identity, returning the original occurrence for
an exact replay.

Catalog preparation builds dictionary indexes once. Exact term lookup has
expected constant cost; bounded review and policy work scale with the selected
source material and prepared predicates. The typed local transition receives
admitted values. Arbitrary external bundles retain a separate byte, identity,
and record-budget intake before this finite example expands.

The ordinary fixture-backed journey remains available through the original
command. Its independent fixture results and the reviewed transition answer
separate questions. Broader administrative adapters, demographic studies,
population inference, and externally executed models retain their own evidence
and authorization routes.

The study's subject and episode identifiers come from the reviewed context;
the full release-scoped context remains bound by its digest. The reviewed
adapter has its own execution identity, including hashes of the four owned
administrative implementation modules. A changed adapter or implementation
therefore receives a different replay fingerprint. These hashes establish
source identity for the local example; the receiving environment retains
responsibility for its installed package and reviewer authority.

## Select a recovery by failure type

The review transition raises `ReviewConflictError` for changed source bindings,
`ReviewSelectionError` for term-selection or disposition choices,
`ReviewEffectivityError` for decision context and time boundaries, and
`ReviewValidationError` for a proposed accepted value that needs contract
reconciliation. Each remains an `AdministrativeBoundaryError`; existing `.code`
and string comparisons retain their fixed values. The `.message`, `.stage`, and
`.recovery` attributes provide authored feedback for a receiving interface.

An expected Pydantic validation failure is translated at accepted-value
construction. Programming failures and interruption retain their original types.
The caller keeps the previous accepted snapshot and can present the relevant
recovery guidance before submitting a fresh request. Automatic retry requires a
separate idempotency and ownership decision. Select fixed feedback for public
returns; complete exceptions and their retained context belong with an authorized
diagnostic receiver.
