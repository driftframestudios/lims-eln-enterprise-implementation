"""Accepted-artifact retention, bounded admission, and exact observation bytes."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import threading
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from lims_eln_implementation.workbench import export
from lims_eln_implementation.workbench.service import WorkbenchService
from lims_eln_implementation.workbench.shared_contracts import contract_available


class ExportStorageTests(unittest.TestCase):
    def test_exact_replay_and_conflict_keep_accepted_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "observation.json"
            self.assertEqual(export._publish(b"accepted", target), "published")
            self.assertEqual(export._publish(b"accepted", target), "reused")
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            with self.assertRaises(export.ExportError):
                export._publish(b"changed", target)
            self.assertEqual(target.read_bytes(), b"accepted")

    def test_write_flush_and_publication_failures_preserve_sibling_and_retry(self) -> None:
        for operation, failure in (
            ("fsync", OSError("private diagnostic")),
            ("link", OSError("private diagnostic")),
            ("link", KeyboardInterrupt()),
        ):
            with self.subTest(operation=operation, failure=type(failure).__name__):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    accepted = root / "accepted.json"
                    export._publish(b"accepted", accepted)
                    target = root / "next.json"
                    with patch.object(export.os, operation, side_effect=failure):
                        with self.assertRaises((OSError, KeyboardInterrupt)):
                            export._publish(b"candidate", target)
                    self.assertEqual(accepted.read_bytes(), b"accepted")
                    self.assertFalse(target.exists())
                    self.assertEqual(sorted(path.name for path in root.iterdir()), ["accepted.json"])
                    self.assertEqual(export._publish(b"candidate", target), "published")

    def test_post_publication_sync_failure_leaves_a_complete_replayable_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "observation.json"
            real_sync = os.fsync
            def sync(descriptor):
                if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                    raise OSError("private diagnostic")
                real_sync(descriptor)
            with patch.object(export.os, "fsync", side_effect=sync):
                with self.assertRaises(OSError):
                    export._publish(b"accepted", target)
            self.assertEqual(target.read_bytes(), b"accepted")
            with patch.object(export.os, "fsync", side_effect=OSError("still unavailable")) as attempt:
                with self.assertRaises(OSError):
                    export._publish(b"accepted", target)
                attempt.assert_called_once()
            with patch.object(export.os, "fsync", wraps=real_sync) as attempt:
                self.assertEqual(export._publish(b"accepted", target), "reused")
                attempt.assert_called_once()
            self.assertEqual(target.read_bytes(), b"accepted")

    def test_competing_publication_requires_exact_bytes(self) -> None:
        for contender in (b"accepted", b"different"):
            with self.subTest(contender=contender):
                with tempfile.TemporaryDirectory() as directory:
                    target = Path(directory) / "observation.json"
                    def competing_link(*args, **kwargs):
                        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                        with os.fdopen(descriptor, "wb") as stream:
                            stream.write(contender)
                        raise FileExistsError()
                    with patch.object(export.os, "link", side_effect=competing_link):
                        if contender == b"accepted":
                            self.assertEqual(export._publish(b"accepted", target), "reused")
                        else:
                            with self.assertRaises(export.ExportError):
                                export._publish(b"accepted", target)
                    self.assertEqual(target.read_bytes(), contender)

    def test_storage_types_permissions_and_aliases_have_independent_boundaries(self) -> None:
        for kind in ("symlink", "fifo", "directory", "hardlink", "permissions", "oversize"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target = root / "observation.json"
                reference = root / "reference"
                reference.write_bytes(b"accepted")
                reference.chmod(0o600)
                if kind == "symlink":
                    target.symlink_to(reference)
                elif kind == "fifo":
                    os.mkfifo(target, 0o600)
                elif kind == "directory":
                    target.mkdir()
                elif kind == "hardlink":
                    os.link(reference, target)
                elif kind == "permissions":
                    target.write_bytes(b"accepted")
                    target.chmod(0o644)
                else:
                    with target.open("wb") as stream:
                        stream.truncate(export.MAX_OBSERVATION_BYTES + 1)
                    target.chmod(0o600)
                with self.assertRaises((OSError, export.ExportError)):
                    export._publish(b"accepted", target)
                self.assertEqual(reference.read_bytes(), b"accepted")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o755)
            with self.assertRaises(export.ExportError):
                export._publish(b"accepted", root / "observation.json")
            root.chmod(0o700)
            alias = root / "alias"
            alias.symlink_to(root, target_is_directory=True)
            with self.assertRaises(OSError):
                export._publish(b"accepted", alias / "observation.json")

    def test_admission_precedes_filesystem_and_input_is_bounded(self) -> None:
        with patch.object(export, "_publish") as publish:
            for payload in (b"", b"x" * (export.MAX_OBSERVATION_BYTES + 1), "text"):
                with self.subTest(kind=type(payload).__name__):
                    with self.assertRaises(export.ExportError):
                        export.export_observation(payload, Path("unused"), tenant_id="TEN", run_id="RUN")
            with patch.object(export, "validate_observation_bytes", side_effect=ValueError("private-canary")):
                with self.assertRaises(export.ExportError) as error:
                    export.export_observation(b"{}", Path("unused"), tenant_id="TEN", run_id="RUN")
                self.assertNotIn("private-canary", str(error.exception))
            publish.assert_not_called()

    def test_cli_retains_signal_handler_and_emits_value_free_failure(self) -> None:
        previous = signal.getsignal(signal.SIGTERM)
        for failure, expected in ((export.ExportError("private-canary"), 1), (export.ExportHeld("private-canary"), 75), (KeyboardInterrupt(), 130)):
            with self.subTest(expected=expected), patch(
                "sys.argv", ["export", "--tenant", "TEN", "--run", "RUN", "--output", "unused"]
            ), patch.object(export.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"{}"))), patch.object(
                export, "export_observation", side_effect=failure
            ), patch.object(export.sys, "stderr", new_callable=io.StringIO) as output:
                self.assertEqual(export.main(), expected)
                self.assertNotIn("private-canary", output.getvalue())
            self.assertEqual(signal.getsignal(signal.SIGTERM), previous)
        with self.assertRaises(KeyboardInterrupt):
            export._terminate(signal.SIGTERM, None)

    def test_real_two_link_overlap_holds_then_reuses_after_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "observation.json"
            linked, release = threading.Event(), threading.Event()
            outcomes = []
            real_link = os.link
            def pause_link(*args, **kwargs):
                real_link(*args, **kwargs)
                linked.set()
                if not release.wait(5):
                    raise TimeoutError("fixture release deadline")
            def publish():
                try:
                    outcomes.append(export._publish(b"accepted", target))
                except BaseException as error:
                    outcomes.append(error)
            with patch.object(export.os, "link", side_effect=pause_link):
                worker = threading.Thread(target=publish, daemon=True)
                worker.start()
                try:
                    self.assertTrue(linked.wait(5))
                    self.assertEqual(target.stat().st_nlink, 2)
                    with self.assertRaises(export.ExportHeld):
                        export._publish(b"accepted", target)
                    self.assertEqual(target.read_bytes(), b"accepted")
                finally:
                    release.set()
                    worker.join(5)
                self.assertFalse(worker.is_alive())
            self.assertEqual(outcomes, ["published"])
            self.assertEqual(target.stat().st_nlink, 1)
            self.assertEqual(export._publish(b"accepted", target), "reused")

    def test_documented_fetch_waits_for_success_even_after_complete_json(self) -> None:
        guide = (Path(__file__).resolve().parents[1] / "docs/runbooks/local-observation-export.v0.1.md").read_text()
        command = guide.split("~~~sh\n", 1)[1].split("\n~~~", 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = root / "commands"
            commands.mkdir()
            curl = commands / "curl"
            curl.write_text(
                "#!/bin/sh\nwhile [ \"$#\" -gt 0 ]; do\n"
                "if [ \"$1\" = --output ]; then shift; output=$1; fi\nshift\ndone\n"
                "printf '%s' '{\"complete\":\"fixture\"}' > \"$output\"\nexit 7\n"
            )
            curl.chmod(0o700)
            receiver = root / ".venv/bin/python"
            receiver.parent.mkdir(parents=True)
            receiver.write_text("#!/bin/sh\nprintf contacted > \"$RECEIVER_MARK\"\n")
            receiver.chmod(0o700)
            storage = root / ".local/state/lims-workbench/observations"
            storage.mkdir(parents=True, mode=0o700)
            accepted = storage / "observation-001.json"
            accepted.write_bytes(b"accepted")
            marker = root / "receiver-called"
            result = subprocess.run(
                ["bash", "-c", command], cwd=root, capture_output=True, timeout=5,
                env={**os.environ, "HOME": str(root), "PATH": str(commands) + os.pathsep + os.environ["PATH"],
                     "RECEIVER_MARK": str(marker)},
            )
            self.assertEqual(result.returncode, 7)
            self.assertFalse(marker.exists())
            self.assertEqual(accepted.read_bytes(), b"accepted")
            self.assertEqual(sorted(path.name for path in storage.iterdir()), ["observation-001.json"])


@unittest.skipUnless(contract_available(), "typed export requires the exact Program contract")
class TypedExportTests(unittest.TestCase):
    def observation(self):
        now = datetime(2026, 10, 5, tzinfo=timezone.utc)
        result = WorkbenchService(clock=lambda: now).run_golden_specimen(
            run_id="RUN-EXPORT-001", tenant_id="SYN-TENANT-A", specimen_id="SYN-EXPORT-001",
            actor_id="SYN-ACTOR-01", scientist_id="SYN-SCIENTIST-01",
            quality_actor_id="SYN-QUALITY-01", occurred_at=now,
            raw_instrument_json=b'{"analyte":"synthetic-dna","value":"12.5","unit":"ng/uL"}',
            vendor_payload={"status": "released"},
        )
        return result["observation"]

    def test_typed_observation_preserves_exact_json_and_provenance(self) -> None:
        observation = self.observation()
        payload = (json.dumps(observation, indent=3) + "\n").encode("utf-8")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "observation.json"
            result = export.export_observation(
                payload, target, tenant_id="SYN-TENANT-A", run_id="RUN-EXPORT-001"
            )
            self.assertEqual(result, {"status": "published", "sha256": sha256(payload).hexdigest()})
            self.assertEqual(target.read_bytes(), payload)
            self.assertEqual(json.loads(target.read_bytes()), observation)
            self.assertEqual(export.export_observation(
                payload, target, tenant_id="SYN-TENANT-A", run_id="RUN-EXPORT-001"
            )["status"], "reused")

    def test_malformed_contract_and_identity_counterexamples_preserve_accepted_file(self) -> None:
        observation = self.observation()
        payload = json.dumps(observation).encode()
        cases = [
            (payload, "SYN-TENANT-B", "RUN-EXPORT-001"),
            (payload, "SYN-TENANT-A", "RUN-EXPORT-002"),
            (payload, "SYN-TENANT-A", "a" * 129),
            (b"{}", "SYN-TENANT-A", "RUN-EXPORT-001"),
            (b"\xff", "SYN-TENANT-A", "RUN-EXPORT-001"),
            (b'{"observation_id":1,"observation_id":2}', "SYN-TENANT-A", "RUN-EXPORT-001"),
        ]
        altered = dict(observation, scenario_digest="sha256:" + "0" * 64)
        cases.append((json.dumps(altered).encode(), "SYN-TENANT-A", "RUN-EXPORT-001"))
        for candidate, tenant, run in cases:
            with self.subTest(length=len(candidate), tenant=tenant, run=run):
                with tempfile.TemporaryDirectory() as directory:
                    target = Path(directory) / "observation.json"
                    export._publish(b"accepted", target)
                    with self.assertRaises(export.ExportError):
                        export.export_observation(candidate, target, tenant_id=tenant, run_id=run)
                    self.assertEqual(target.read_bytes(), b"accepted")


if __name__ == "__main__":
    unittest.main()
