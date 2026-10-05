---
title: Program package receiving handoff
version: 0.1.0
status: working
audience: human_and_ai_collaborators
source_band: public_possible
task_type: operational_collaboration
---

# Program package receiving handoff

## Desired state and entry

A collaborator installs the exact reviewed Program package in an isolated
Python 3.12 environment, verifies its Git source and packaged resources, and
runs Enterprise's existing Golden Specimen observation test.

Enter after Program accepts a full source commit and scoped digest and
Enterprise authorizes adoption. Program's
`release/contract-package-coordinate.json` owns shared source identity.
Enterprise's `release/external-contract-coordinates.json` owns this receiver's
binding and observed values. Issue #36 owns adapter implementation; Issue #35
owns repeatable handoff procedures.

## Authority and action mode

Program owns shared contract meaning. Enterprise owns installation, runtime
composition, and its observed result. The authorized mode is local installation
and testing. Git authentication uses the configured credential helper; committed
requirements carry the ordinary credential-free repository URL.

The current package `0.4.0` is reviewed integration source. The signed
Enterprise `v0.3.2` baseline and Program's repository release remain separate
subjects. Human-held `main` merges, site-release tags, publication, configured
database operation, and model-provider transmission retain their own decisions.

## Phase 1: Prepare the isolated receiver

**Owner:** Enterprise maintainer. **Checkpoint:** one Python 3.12 environment
with the reviewed `contracts` extra and test dependencies.

From this repository, choose a task-local environment path:

```sh
uv venv --python 3.12 --managed-python <task-environment>
uv pip install --python <task-environment>/bin/python -e ".[test,contracts]"
```

The optional extra selects the exact Program commit. Editable sibling installs
serve local development; PEP 610 Git conformance uses the non-editable pinned
Program requirement above. Dependency locks and maintained platform coverage
continue through Program #54.

**Recovery:** Classify interpreter, source access, dependency resolution, or
installation failure. Retain the accepted coordinate and change the relevant
environment condition before retrying.

## Phase 2: Establish source and installed-resource conformance

**Owner:** Enterprise's existing receiver validator. **Checkpoint:** versions,
distribution ownership, PEP 610 URL/revision/commit, scoped source digest, three
operations, Golden Specimen, both observations, four administrative resources,
and the exact nine-schema inventory agree.

Supply an adjacent Program checkout containing the bound commit:

```sh
<task-environment>/bin/python scripts/validate_received_contracts.py \
  --require-installed-program --program-source <program-checkout>
<task-environment>/bin/python -m unittest \
  tests.test_received_contracts tests.test_shared_contract_binding -v
```

The source digest reads the bound Git object, independently of mutable checkout
files. Resource loaders exercise Program's typed boundaries. The workbench test
retains the implementation's existing measurement profile and its separately
owned scientific mapping question.

**Recovery:** Preserve prior accepted source and observations. Route a package
resource or shared-meaning mismatch to Program; route receiver configuration
or runtime composition to Enterprise. A failed check stays distinguishable
from a completed conformance observation.

## Phase 3: Return and continue

**Owner:** The receiving Issue and reviewable PR. **Checkpoint:** one compact
return states the exact Program commit and digest, Enterprise revision,
Python and materially relevant dependency versions, command, result, and reach.

The return establishes package reception and the process-local typed
observation. Durable restart, container entry, and exported comparisons continue
in Issue #43; administrative adapter execution continues in Issue #36.
Scientific disposition remains with its qualified reviewer.

**Stop:** End this procedure after the bounded receiving result or one named
recovery condition. A changed package source, installed import, dependency
environment, or receiver implementation reopens the affected observation.
