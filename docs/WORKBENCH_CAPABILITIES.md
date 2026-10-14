# See the active workbench composition

Start with the [workbench guide](README.md), then visit `/workbench`. Its runtime
label follows the selected adapter: process-local state or PostgreSQL-backed
state. The same source-owned projection is available at
`GET /api/workbench/capabilities` for a receiving tool.

## Use the right observation

| Question | Route | Meaning |
| --- | --- | --- |
| Which adapter and operations are composed? | `/api/workbench/capabilities` | Declared composition and current shared-package version compatibility. |
| Can the composed dependencies answer now? | `/health/ready` | A fresh, bounded dependency observation. |
| How can a specimen journey run? | `/api/docs` and the existing workbench form | Explicit tenant context and the operation's admission and transaction rules. |
| How can administrative studies run? | [Documentation entry](README.md) | The offline Python-library journey; the current HTTP operation catalog covers the specimen workbench. |

Both the capability response and the server-rendered page use `no-store`.
The template receives the same projection as the API and remains readable with
JavaScript disabled. The application retains its existing styles, navigation,
security headers, and tenant-scoped operations.

## Interpretation boundaries

The composition root selects the adapter once per application. The package
check reports compatibility with the expected package and contract versions.
Installed-resource validation remains the owner of source provenance and package
behavior. An administrative study still requires its own admitted inputs and
execution evidence.

Database-backed state follows the configured database's lifetime. Disposable,
retained, and externally managed databases have different ownership and cleanup
rules, supplied by the launcher and receiving infrastructure. This record leaves
those choices with their owners. Connection coordinates, credentials, and tenant
data stay in the existing protected configuration and request paths.

The declared access scope is `local_reference`. Remote deployment requires its
own authenticated caller boundary. A capability entry supports discovery;
each operation continues to enforce its authority and input contract.

## Contract and implementation owners

Program owns `workbench-capabilities.v1.schema.json`. The byte-identical local
copy lives in `contracts/`; its source binding records the reviewed Program
commit and schema digest. This standalone contract preserves the installed
Program package coordinate and its existing resource inventory.

`workbench/capabilities.py` owns the explicit, pure projection. Its immutable
operation tuples produce fresh nested records, with constant time and space for
the fixed two-adapter, five-operation vocabulary. The API composition root owns
the version-compatibility observation and supplies the template context.

Focused fixtures exercise the schema, input boundaries, alias isolation, actual
route correspondence, and both adapters' authored wording. They model adapter
selection; configured PostgreSQL execution remains the next persistence and
recovery observation under
[Enterprise #60](https://github.com/driftframestudios/lims-eln-enterprise-implementation/issues/60).
The broader shell and navigation continue under
[Enterprise #62](https://github.com/driftframestudios/lims-eln-enterprise-implementation/issues/62).
