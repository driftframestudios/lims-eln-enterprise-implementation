# Receive a database lifecycle record

Choose a disposable, retained, or externally owned database profile, then check
its documentary history before handing it to a launcher owner. This source-only
receiver selects the exact Program package and schema in
[`database-lifecycle-profile.source.json`](../contracts/database-lifecycle-profile.source.json).
Program's packaged admission API owns the lifecycle semantics. Enterprise owns
the source selection, local receiving boundary, and independent expectations.

| Profile | Documentary authority | Runtime receiver |
| --- | --- | --- |
| Disposable | Successful creation by the current invocation establishes cleanup authority for that resource instance. | The launcher verifies live ownership before acting. |
| Retained | The named resource owner supplies the explicit restore or cleanup decision. | The retained-project owner resolves the decision and preserves unrelated resources. |
| External | The external owner retains lifecycle authority; an invocation actor cannot claim owner cleanup. | The external team authenticates the operation through its own environment. |

The five [synthetic records](../fixtures/synthetic/) cover all three profiles,
failed cleanup, and an unresolved creation. Their PostgreSQL 17/V007 references
express intended compatibility. Their authored events establish source examples;
the separately admitted database receipts retain executed-environment evidence.

## Use the dedicated receiving profile

From an authorized checkout, select the isolated Python 3.12 profile. The exact
Git dependency uses the existing credential helper; credentials stay there.

```sh
uv run --isolated --no-project --python 3.12 \
  --with-requirements requirements-lifecycle.txt \
  -- python scripts/receive_database_lifecycle.py --verify-installation \
  --program-source ../lims-eln-program-specification

uv run --isolated --no-project --python 3.12 \
  --with-requirements requirements-lifecycle.txt \
  -- python scripts/receive_database_lifecycle.py \
  fixtures/synthetic/database-lifecycle-disposable.json
```

The first command checks package version, wheel and exact Git provenance,
distribution-owned import paths, both installed schema byte sequences, and the
package-scoped digest from the exact selected Git object. Supply an authorized
Program checkout containing that object; its working branch may differ. The second checks the record against the receiver's
trusted source revision and schema identity. The caller supplies `--capabilities`
with the exact raw response bytes when the record declares observed composition.
A PostgreSQL composition can carry `version_compatible=false`; capability v1
keeps that package observation separate from lifecycle, readiness, and execution.

The admitted summary reports the final resource state, unresolved-resource
count, and recorded executed/requested operation counts. It always reports zero
database actions performed by this receiver. An admitted unresolved record stays
unresolved: retain its history and route `recovery_ref` to the resource owner.
The receiver reads at most 128 KiB per regular input file; the contract bounds
history to 64 events. Raw input and local file coordinates remain local.

## Run the independent receiving checks

```sh
PYTHONPATH=src uv run --isolated --no-project --python 3.12 \
  --with-requirements requirements-lifecycle.txt \
  -- python -m unittest tests.test_database_lifecycle_receiver -v
```

Enterprise authored these fixtures and expected outcomes independently. The
checks cover the three profiles, wrong owner, source/schema/version drift,
external cleanup, failed cleanup, unresolved resources, new resource instances,
compatibility and capability-v1 combinations. They also exercise the existing
Enterprise capability producer. Program's test data and test implementation
remain with their defining owner.

This tool profile selects Program 0.7.0 with its lifecycle extra. The application
retains its own Program 0.6.1 dependency and lock. The complete application proof
runs the receiving binding controls and explicitly skips lifecycle semantic
checks when that separate profile is absent. The dedicated command above is the
required observation for lifecycle receipt acceptance. An unexpected installed
version or source produces a failing check.

## Route a finding and the next action

| Finding family | Next useful move |
| --- | --- |
| Dependency version/provenance or source/schema/version | Prepare the exact selected profile and reviewed source coordinate. |
| Owner, action, destructive authority or external cleanup | Reconcile the named resource and obtain its owner's action-specific decision. |
| Transition, compatibility or event evidence | Preserve history and append the executor's resolved observation. |
| Composition reference, digest or contract | Supply the exact separately admitted capability-v1 response. |
| Unresolved-resource mismatch | Preserve the unresolved resource and route inspection or recovery to its owner. |

The receiver checks documentary consistency. Actual resource identity,
authentication, launch, migration, cleanup and administrative persistence remain
with [Enterprise #60](https://github.com/driftframestudios/lims-eln-enterprise-implementation/issues/60)
and [#68](https://github.com/driftframestudios/lims-eln-enterprise-implementation/issues/68).
[Governance #49](https://github.com/driftframestudios/site-reading-governance/issues/49)
owns independent claim review and accountable acceptance. A changed package or
schema coordinate receives a reviewed pin and another independent receiving run.

Return to the [capability guide](WORKBENCH_CAPABILITIES.md) or
[workbench entry](README.md).
