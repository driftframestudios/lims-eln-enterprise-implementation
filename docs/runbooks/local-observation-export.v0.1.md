# Local observation export v0.1

## Outcome and boundary

Export one accepted Golden Specimen observation as the existing Program typed
JSON contract. The comparison receiver can inspect this file independently of
the running service. Exact received bytes retain the scenario, classification,
projection, configuration, input digest, source, and producer detail.

This is an operator-owned local artifact. Producer details, governed locators,
and adjacent fields retain their original audience. A public return uses the
normalized status/digest and the receiving decision's reviewed fields.
Classification expresses the producer's declared scope; a publication review
establishes suitability for another audience.

## Entry

Use the locked Python environment with the exact Program contract installed.
Start either the [native entry](local-workbench-entry.v0.1.md) or
[container entry](local-container-entry.v0.1.md), complete a Golden Specimen
run, and retain its run and tenant identities. Use the actual accepted run ID
in both occurrences below. Select the configured loopback port.

~~~sh
STATE_ROOT="$HOME/.local/state/lims-workbench"
mkdir -p "$STATE_ROOT/observations"
chmod 700 "$STATE_ROOT/observations"
(
set -eu
umask 077
TRANSFER=$(mktemp "$STATE_ROOT/observations/.transfer-XXXXXX")
trap 'rm -f "$TRANSFER"' EXIT
curl --fail --silent --show-error --max-time 15 --max-filesize 2097152 \
  --output "$TRANSFER" \
  --header 'X-Tenant-ID: SYN-TENANT-A' \
  'http://127.0.0.1:8000/api/workbench/observations/RUN-EXPORT-001?tenant_id=SYN-TENANT-A'
.venv/bin/python -m lims_eln_implementation.workbench.export \
      --tenant SYN-TENANT-A --run RUN-EXPORT-001 \
      --output "$STATE_ROOT/observations/observation-001.json" < "$TRANSFER"
)
~~~

The command is for Bash or Zsh. Curl retains HTTP fetching and its total deadline;
a protected transfer file is admitted only after curl succeeds. The exporter
reads at most 2 MiB plus one admission byte from standard input.
A failed HTTP fetch, partial document, identity mismatch, or unavailable contract
stops before filesystem publication. Direct file input through standard input is
also supported. The receiving module is packaged with the ordinary application.

## Acceptance and reuse

A successful command reports only publication/reuse status and a SHA-256 digest.
The destination is a 0600 regular file in an owner-held 0700 directory. Strict
contract admission checks the requested tenant, run-derived observation identity,
and canonical scenario. The byte representation is preserved rather than
reserialized.

A repeated export with identical bytes reports reuse. Different bytes at an
existing destination invite a new named artifact and comparison; the accepted
file remains intact. Equivalent JSON formatted differently has a different byte
identity. Cooperative concurrent exporters use exclusive publication, with exact
identity checked after an existing-file result. A brief two-link publication
interval returns a retryable hold (exit 75). Wait for the preceding writer to
complete its cleanup, then repeat the exact export. A persistent extra link
receives operator reconciliation rather than automatic removal.

The observation's implementation field currently names the package/version
coordinate. Exact Git, dependency-lock, migration-image, and installed-build
coordinates remain with their verified build/context receipt. Keep that receipt
alongside the comparison intake through its existing evidence owner. Export
preserves these distinctions; it adds transport integrity rather than a new
source attestation.

## Interruption and recovery

The writer flushes and syncs an owner-only temporary file, publishes by an
exclusive same-directory link, then removes the temporary link and syncs the
directory. Before publication, failure preserves the accepted destination.
After publication, a directory-sync failure can leave a complete visible artifact
whose crash durability awaits confirmation. Retain it and repeat the same export
after storage recovery. Exact-byte reuse retries the directory sync before
reporting success; another sync failure preserves the artifact and remains
unsuccessful.

SIGINT and SIGTERM use cleanup and a bounded status message. Forced termination
or host loss may retain a private pending file. After confirming the earlier
process has stopped, inspect and reconcile the named pending entry locally.
A pending link to the accepted file can be removed while retaining the accepted
name. Existing multiply linked artifacts stay held for that reconciliation.
Directory ownership is a local-operator trust boundary; an administrator or
another process with the same account retains its filesystem authority.

## Focused evidence and handback

~~~sh
.venv/bin/python -m unittest discover -s tests -p 'test_workbench_export.py' -v
~~~

Ordinary fixtures exercise publication, conflict, interruption, storage type and
permission boundaries, concurrent publication, input budgets, and value-free
errors. Installed-contract fixtures exercise actual typed observations and
identity counterexamples. A configured export proves the running adapter's
received bytes, replay, digest, and retained destination after a failed fetch.

Enterprise #43 owns the remaining complete journey; #45 owns the shared
export-recovery acceptance. Return source, dependency/profile, artifact digest,
normalized outcome, and scope through the receiving PR. Detailed payloads and
local storage remain with the operator.
