# Configured capability and PostgreSQL proof v0.1

Observe the actual PostgreSQL launcher, matching capability JSON and authored
HTML, dependency readiness, and one nonempty Golden Specimen record across
application restart. Enterprise Issue 68 owns this bounded observation.

## Checkpoint 0: receive the earlier wave and source review

This route is prepared on `codex/configured-postgresql-capability`, stacked on
`codex/database-capability-slice` at `6e7ee392100e147e6e0a66913a09205201f50df2`
(PR 67). Configured execution awaits the parent's earlier Governance 39/52,
Simulation 52, and Comparative 56 handoff and independent review of this source.
The parent names the reviewer and confirms the current Governance claim/evidence
mapping, including the Issue 51 entry and Issue 49 assurance receiver. Commit
the reviewed source before recording a configured observation.

Program Issue 79 owns the future lifecycle profile. Issue 68 permits this first
journey to use the existing declared owned PostgreSQL configuration. Record that
choice explicitly; adoption of the reviewed lifecycle contract is a later
handoff. Keep its future contract identity distinct from today's configuration.

The source owners are `workbench/cli.py`, `runtime.py`, `postgres.py`, `api.py`,
`capabilities.py`, and `shared_contracts.py`. Program owns the capability schema;
`contracts/workbench-capabilities.source.json` binds the unchanged local copy.
Version compatibility and installed package provenance remain separate facts.
The current lock consumes Program 0.6.1; older entry prose naming 0.4.0 describes
an earlier package coordinate. Use the current lock and package handoff checks.

## Checkpoint 1: focused source evidence

Use the repository Python 3.12 environment and its locked `contracts`, `postgres`,
and `test` extras. From the repository root:

```sh
PYTHONPATH=src:tests .venv/bin/python -m unittest \
  test_workbench_capabilities test_workbench_runtime test_workbench_api \
  test_workbench_postgres_adapter test_configured_workbench_capabilities -v
.venv/bin/python scripts/build_public_inspection_manifest.py --check
```

With `LIMS_CONFIGURED_CAPABILITY_PROOF` unset, the configured journey skips.
That result establishes source composition, schema/HTML agreement, `no-store`,
typed rejection, and dependency fault handling through a real adapter with a
connector double. PostgreSQL persistence receives its evidence in checkpoint 3.
The new source checks also distinguish an incompatible package at startup from
a later compatibility observation on an already composed application.

Review the oracle and failure route before activation: the expected specimen
is released at version 5, has five events, receiving custody, and exactly one
`synthetic-dna` measurement of `12.5 ng/uL` with the input byte digest. Empty or
merely equal snapshots cannot satisfy these assertions.

## Checkpoint 2: prepare one owned local database

Use the existing [container entry](local-container-entry.v0.1.md) secret
preparer and Compose/Flyway/bootstrap chain. Select a fresh project named
`lims-issue68-` followed by twelve random lowercase hexadecimal characters.
Give it a fresh protected secret directory and a fresh evidence directory with
mode `0700`. Keep the project name, Docker context, source coordinate, generated
configuration and resource inventory with the local operator.

Start only the PostgreSQL and setup services needed by
`database-role-bootstrap`; the application runs through the native launcher.
The Compose file's existing PostgreSQL service needs an operator-owned override
that publishes database port 5432 on one available loopback host port. Use the
same explicit project and Compose files for every preparation and cleanup step.
Successful role provisioner, Flyway and role bootstrap exit states precede the
journey. Run the existing migrator's `validate` and protected `info` route;
require V001-V005 with head `005` and record actual image IDs and platforms.

For Colima or another VM, explicitly map this owned source/context and output
directory into the VM's available mounts. Confirm the engine can read the
selected source-mounted helpers and secret files. Keep established workbench
projects, volumes, credential directories, VM mounts and defaults intact.
An inaccessible mount is a preparation decision; choose an owned accessible
mapping before continuing.

Select the actual prepared native connection and regular secret files through
the existing `LIMS_WORKBENCH_*` settings. Require `LIMS_WORKBENCH_ADAPTER=postgresql`
and `LIMS_WORKBENCH_DB_HOST=127.0.0.1`. Set the host port to the owned database's
published port. The bootstrap retains its declared `laboratory` database,
ordinary `laboratory_app` login, fixed synthetic tenant and `local-compose-v1`
verifier. The operator confirms that these settings select the owned project.

Activate only after the checkpoint 0 release and successful source checks:

```sh
export LIMS_CAPABILITY_PROJECT="$OWNED_ISSUE68_PROJECT"
export LIMS_CAPABILITY_DATABASE_OWNERSHIP=owned_issue68
export LIMS_CAPABILITY_PROOF_DIR="$OWNED_ISSUE68_EVIDENCE_DIRECTORY"
LIMS_CONFIGURED_CAPABILITY_PROOF=1 PYTHONPATH=src:tests \
  .venv/bin/python -m unittest \
  test_configured_workbench_capabilities.ConfiguredLauncherJourney -v
```

The ownership field is an explicit operator declaration. It is not infrastructure
discovery or authority to use a retained or externally managed database.
Keep connection values and file paths in protected local configuration.

## Checkpoint 3: one configured journey

The test creates one fresh `0700` output directory, records the clean source,
lock, schema, Python/platform and package versions, and preserves the exact
synthetic request before its single transaction. Its real CLI subprocesses use
the checked-out source via `PYTHONPATH`; this is a source launcher observation,
with installed artifact provenance handled by the package receiver.

1. Launch PostgreSQL composition. Require schema-conformant capabilities,
   matching script-independent HTML text and package version, `no-store`, and
   readiness 200. Confirm the new specimen is absent, then post once and assert
   the independently expected record.
2. Stop that application and launch a new process with the same database and
   credentials. Require the expected specimen, exact snapshot equality and a
   schema-valid typed observation from PostgreSQL at migration head `005`.
3. Launch an owned application with its connection endpoint redirected to a
   reserved, non-listening loopback socket. Require readiness 503, continued
   liveness, and unchanged composition JSON and HTML. The database stays running.
4. Restore the original application configuration. Require readiness 200 and
   the same independently expected retained specimen.

This fault observes connection refusal through the actual launcher. The source
test separately observes up/down/up on one existing service instance. Database
crash recovery, in-flight commit loss, restore and failover retain their own
acceptance. HTML parsing observes authored text without executing scripts;
renew browser evidence when visitor layout or interaction changes.

The harness holds a listening loopback socket through child startup, requests
and shutdown. The existing launcher passes its inherited `--fd` to Uvicorn;
the child receives only that descriptor through `pass_fds`. Kernel socket
ownership keeps the HTTP endpoint attached to this invocation before the
Golden transaction. Liveness then observes whether the owned server can answer.
This native inherited-descriptor route uses the existing POSIX local profile.

Each child has a bounded startup and termination wait. Only the test's child
processes are stopped. Logs, request, responses and failure traces remain in
protected output. A failed stage ends the journey and preserves its checkpoint;
the test does not retry a Golden transaction or reset state. Use the existing
[uncertain-commit recovery](local-workbench-entry.v0.1.md#reconcile-an-uncertain-commit)
with the retained exact request. A newly authored defect goes to the parent/user
for approval before a repair or another configured attempt.

If diagnostic storage also fails, the public report retains the bounded stage
failure and names the storage limitation. The original failure remains available
in local exception context; private error text stays outside the public report.

Child cleanup encloses acquisition and parent log closure. Both artifacts and
launcher logs release their raw descriptor when file-object construction fails.
Focused counterexamples cover log-close failure, termination escalation,
descriptor wrapping and competing attempts to bind the owned listener. The
ordinary source composition tests declare exact package and contract versions
through doubles, so the lightweight `test` profile remains sufficient; incompatible
versions keep their explicit cases. Configured execution continues to receive
the real installed Program package and PostgreSQL connection.

## Checkpoint 4: review, assurance handoff and owned cleanup

Give the parent one concise return for Governance Issue 49: exact source commit,
schema binding, lock/package provenance, actual PostgreSQL/Flyway image IDs and
platforms, database version, migration validation/head, run time, performer,
independent reviewer, artifact digests, named passed/failed stages and coverage.
The local checkpoint is a candidate evidence carrier. Admit configured evidence
through `contracts/execution-receipt.v1.1.schema.json` and the existing
configured-environment binding route when the reviewer and coordinates are
complete. Preserve frozen hosted and release receipts at their original bytes.

The successful claim is **Golden Specimen persistence through the configured
PostgreSQL launcher**. Administrative durability/lifecycle belongs to Enterprise
60, remote identity to 38, AWS to 61 and service/public-source hardening to 52.
Scientific qualification, intended-use validation, accountable acceptance and
production authorization remain distinct receiving decisions.

Public evidence carries normalized outcomes and source-safe identities. Keep
URLs, private paths, credentials, tenant/connection values and raw diagnostics
with the protected local owner. Preserve the earlier workbench inventory.

The test preserves the database and its volumes for inspection. After the
parent accepts the local handoff, compare the recorded pre-existing inventory
and remove only containers, network, image/context and volumes created for this
named test project. Retained evidence follows the operator's retention choice.
Re-entry is checkpoint 0 at the committed source; the earlier handoff and
independent review release checkpoint 2. Push, PR creation, merges, tags,
publication, cloud work and external model execution remain held.
