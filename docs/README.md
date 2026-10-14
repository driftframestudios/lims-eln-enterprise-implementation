# Use the laboratory workbench

The workbench makes laboratory state and its changes visible: load a Golden
Specimen example, inspect the resulting records, exercise an instrument
handoff, and follow the evidence into an observation export. Choose the state
lifetime that fits the question before starting.

## Start with a process-local session

Use an authorized Enterprise checkout with `uv` available. From the repository
root, prepare the declared environment and start the workbench:

```sh
uv sync --locked --extra contracts --extra postgres --extra test --no-editable
.venv/bin/lims-eln-workbench --adapter process_local
```

Visit <http://127.0.0.1:8000/workbench>. This session keeps application state in
the running process; restarting begins a fresh session. The command uses the
repository's accepted package lock. Initial preparation needs access to the
pinned Program dependency through the configured Git credential helper.
Credentials remain with that helper; shared commands and reports carry
repository-relative references.

Use the workbench's Golden Specimen flow, then inspect the resulting laboratory
records. The [workbench guide](golden-specimen-workbench.md) explains the controls
and observations. The [native entry runbook](runbooks/local-workbench-entry.v0.1.md)
owns health checks, grants, replay, configuration, and recovery.

## Choose the next result

| Goal | Route | State and evidence |
| --- | --- | --- |
| Explore the interface and a first example | Process-local command above | Fresh in-memory state for each process |
| Retain state across restarts | [PostgreSQL native entry](runbooks/local-workbench-entry.v0.1.md) | Explicit database roles, migrations, configuration, and readiness |
| Reproduce the container journey | [Container entry](runbooks/local-container-entry.v0.1.md) | Prepared external secret files, a named Compose project, retained data, and recovery steps |
| Inspect a completed run elsewhere | [Observation export](runbooks/local-observation-export.v0.1.md) | A selected run and its exported observation for a receiving comparison |
| Compare implementation and selected-future behavior | [Comparative Evidence](https://github.com/driftframestudios/lims-eln-comparative-evidence) | Matching JSON/HTML reports with explicit input and evidence standing |

For repeat use, keep the original request identity and payload with the run.
Replay and uncertain-commit recovery use the original endpoint and retained
request, as described in the native entry runbook. A new experiment receives
its own identity. The container route provides the corresponding retained
project and secret-recovery steps.

## Explore administrative and insurance context

Enterprise already receives an exact Program package and its administrative
resources through the [package handoff](runbooks/program-package-handoff.v0.1.md).
That handoff establishes installed contract availability. Program's
[administrative example](https://github.com/driftframestudios/lims-eln-program-specification/blob/main/docs/README.md#try-the-administrative-contract-kit)
can be used now to inspect classifications, policy records, provenance, and an
administrative-only counterfactual.

Connected adapter execution and capability reporting are owned by
[#36](https://github.com/driftframestudios/lims-eln-enterprise-implementation/issues/36).
The insurance classification and assignment service is owned by
[#37](https://github.com/driftframestudios/lims-eln-enterprise-implementation/issues/37).
Those services are the next implementation layer. Today's workbench and
package checks establish their own laboratory and contract behavior; insurance
decisions receive the service-specific acceptance evidence.

## Find the owner of a change

Use the [root capability map](../README.md#capability-map-by-reader-job) to find
the service, persistence, migration, or assurance area for a contribution.
[Infrastructure](../infra/README.md) owns the environment routes. The
[researcher environment guide](https://github.com/driftframestudios/lims-eln-program-specification/blob/develop/docs/RESEARCHER_ENVIRONMENTS.md)
connects the repositories' Python and package choices.

Source review, configured execution, release acceptance, and public publication
each retain their own decision. Choose the smallest existing check that covers
the changed behavior and carry its result to the receiving PR.

Return to the [Enterprise overview](../README.md) or the
[constellation starting guide](https://github.com/driftframestudios/lims-eln-program-specification/blob/main/docs/README.md).

## Offline insurance and administrative study

[Run the offline administrative journey](offline-administrative-journey.md) to
inspect exact catalog lookup, reviewed policy inputs, paired output comparisons,
and complete local replay using the packaged synthetic examples.
