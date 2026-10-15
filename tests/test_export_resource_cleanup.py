"""Acquisition, publication and cleanup faults retain owned storage and control."""

import errno
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from lims_eln_implementation.workbench import export


class ExportResourceCleanupTests(unittest.TestCase):
    def test_setup_interrupt_after_directory_acquisition_releases_it(self):
        for failure in (KeyboardInterrupt(), SystemExit(17), OSError("private setup")):
            acquired = []
            real_open = os.open
            def acquire(*args, **kwargs):
                descriptor = real_open(*args, **kwargs)
                acquired.append(descriptor)
                return descriptor
            with self.subTest(failure=type(failure)), tempfile.TemporaryDirectory() as directory:
                with patch.object(export.os, "open", side_effect=acquire), patch.object(
                    export.secrets, "token_hex", side_effect=failure
                ), patch.object(export.os, "close", wraps=os.close) as close:
                    with self.assertRaises(type(failure)) as caught:
                        export._publish(b"accepted", Path(directory) / "observation.json")
                    self.assertIs(caught.exception, failure)
                    self.assertEqual(close.call_count, 1)
                self.assertEqual(len(acquired), 1)
                with self.assertRaises(OSError) as closed:
                    os.fstat(acquired[0])
                self.assertEqual(closed.exception.errno, errno.EBADF)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_failed_stream_transfer_releases_raw_descriptor_for_read_and_write(self):
        for existing in (False, True):
            acquired = []
            real_open = os.open
            def acquire(*args, **kwargs):
                descriptor = real_open(*args, **kwargs)
                acquired.append(descriptor)
                return descriptor
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "observation.json"
                if existing:
                    export._publish(b"accepted", target)
                with patch.object(export.os, "open", side_effect=acquire), patch.object(
                    export.os, "fdopen", side_effect=OSError("private transfer")
                ), patch.object(export.os, "close", wraps=os.close) as close:
                    with self.assertRaises(OSError):
                        export._publish(b"accepted", target)
                    self.assertEqual(close.call_count, 2)
                self.assertEqual(len(acquired), 2)
                for descriptor in acquired:
                    with self.assertRaises(OSError) as closed:
                        os.fstat(descriptor)
                    self.assertEqual(closed.exception.errno, errno.EBADF)
                self.assertEqual(list(Path(directory).glob(".pending-export-*")), [])
                if existing:
                    self.assertEqual(target.read_bytes(), b"accepted")
                else:
                    self.assertFalse(target.exists())

    def test_primary_and_secondary_failures_preserve_control_and_publication_state(self):
        for primary_type in (OSError, KeyboardInterrupt, SystemExit):
            for cleanup_stage in ("pending_unlink", "directory_sync", "directory_close"):
                primary = primary_type("private primary")
                secondary = OSError("private cleanup")
                real_unlink, real_sync, real_close = os.unlink, os.fsync, os.close
                attempts = []
                def unlink(*args, **kwargs):
                    attempts.append("pending_unlink")
                    if cleanup_stage == "pending_unlink":
                        raise secondary
                    return real_unlink(*args, **kwargs)
                def sync(descriptor):
                    if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                        attempts.append("directory_sync")
                        if cleanup_stage == "directory_sync":
                            raise secondary
                    return real_sync(descriptor)
                def close(descriptor):
                    is_directory = stat.S_ISDIR(os.fstat(descriptor).st_mode)
                    result = real_close(descriptor)
                    if is_directory:
                        attempts.append("directory_close")
                        if cleanup_stage == "directory_close":
                            raise secondary
                    return result
                with self.subTest(primary=primary_type, cleanup=cleanup_stage), tempfile.TemporaryDirectory() as directory:
                    target = Path(directory) / "observation.json"
                    with patch.object(export, "validate_observation_bytes", return_value=None), patch.object(
                        export.os, "link", side_effect=primary
                    ), patch.object(export.os, "unlink", side_effect=unlink), patch.object(
                        export.os, "fsync", side_effect=sync
                    ), patch.object(export.os, "close", side_effect=close):
                        expected = export.ExportError if primary_type is OSError else primary_type
                        with self.assertRaises(expected) as caught:
                            export.export_observation(b"{}", target, tenant_id="SYN-TENANT", run_id="SYN-RUN")
                    observed = caught.exception
                    if primary_type is OSError:
                        self.assertIs(observed.primary_error, primary)
                        self.assertNotIn("private", str(observed))
                    else:
                        self.assertIs(observed, primary)
                    self.assertEqual([f.error for f in observed.cleanup_failures], [secondary])
                    self.assertEqual(observed.publication_state, "unknown")
                    self.assertEqual(observed.pending_state, "reconcile" if cleanup_stage == "pending_unlink" else "absent")
                    self.assertEqual(attempts, ["pending_unlink", "directory_sync", "directory_close"])
                    self.assertFalse(target.exists())

    def test_successful_publication_with_cleanup_failure_preserves_complete_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "observation.json"
            with patch.object(export.os, "unlink", side_effect=OSError("private cleanup")):
                with self.assertRaises(OSError) as caught:
                    export._publish(b"accepted", target)
            self.assertEqual(caught.exception.publication_state, "published")
            self.assertEqual(caught.exception.pending_state, "reconcile")
            self.assertEqual(target.read_bytes(), b"accepted")
            self.assertEqual(target.stat().st_nlink, 2)
            with self.assertRaises(export.ExportHeld):
                export._publish(b"accepted", target)
            pending, = Path(directory).glob(".pending-export-*")
            pending.unlink()
            self.assertEqual(export._publish(b"accepted", target), "reused")

    def test_link_response_loss_records_uncertainty_and_retains_visible_bytes(self):
        real_link = os.link
        def response_lost(*args, **kwargs):
            real_link(*args, **kwargs)
            raise KeyboardInterrupt()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "observation.json"
            with patch.object(export.os, "link", side_effect=response_lost):
                with self.assertRaises(KeyboardInterrupt) as caught:
                    export._publish(b"accepted", target)
            self.assertEqual(caught.exception.publication_state, "unknown")
            self.assertEqual(target.read_bytes(), b"accepted")
            self.assertEqual(target.stat().st_nlink, 1)
            self.assertEqual(export._publish(b"accepted", target), "reused")

    def test_cleanup_control_propagates_after_remaining_directory_release(self):
        for stage in ("unlink", "fsync", "close"):
            for control_type in (KeyboardInterrupt, SystemExit):
                control = control_type()
                real_unlink, real_sync, real_close = os.unlink, os.fsync, os.close
                releases = []
                def unlink(*args, **kwargs):
                    if stage == "unlink":
                        raise control
                    return real_unlink(*args, **kwargs)
                def sync(descriptor):
                    if stat.S_ISDIR(os.fstat(descriptor).st_mode) and stage == "fsync":
                        raise control
                    return real_sync(descriptor)
                def close(descriptor):
                    is_directory = stat.S_ISDIR(os.fstat(descriptor).st_mode)
                    result = real_close(descriptor)
                    if is_directory:
                        releases.append("directory")
                        if stage == "close":
                            raise control
                    return result
                with self.subTest(stage=stage, control=control_type), tempfile.TemporaryDirectory() as directory:
                    target = Path(directory) / "observation.json"
                    with patch.object(export.os, "unlink", side_effect=unlink), patch.object(
                        export.os, "fsync", side_effect=sync
                    ), patch.object(export.os, "close", side_effect=close):
                        with self.assertRaises(control_type) as caught:
                            export._publish(b"accepted", target)
                    self.assertIs(caught.exception, control)
                    self.assertEqual(control.publication_state, "published")
                    self.assertEqual(releases, ["directory"])
                    self.assertEqual(target.read_bytes(), b"accepted")

    def test_stream_close_control_keeps_primary_and_releases_directory(self):
        primary = OSError("private write")
        control = KeyboardInterrupt()
        real_fdopen = os.fdopen
        class InterruptedStream:
            def __init__(self, descriptor, mode):
                self.stream = real_fdopen(descriptor, mode, closefd=False)
                self.close_attempts = 0
            def write(self, payload):
                raise primary
            def close(self):
                self.close_attempts += 1
                self.stream.close()
                raise control
        streams = []
        def open_stream(descriptor, mode, *, closefd):
            self.assertFalse(closefd)
            stream = InterruptedStream(descriptor, mode)
            streams.append(stream)
            return stream
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(export.os, "fdopen", side_effect=open_stream):
                with self.assertRaises(KeyboardInterrupt) as caught:
                    export._publish(b"accepted", Path(directory) / "observation.json")
            self.assertIs(caught.exception, control)
            self.assertIs(control.primary_error, primary)
            self.assertEqual(control.publication_state, "unpublished")
            self.assertEqual(streams[0].close_attempts, 1)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_stream_close_interruption_before_raw_release_keeps_one_fd_owner(self):
        for existing in (False, True):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "observation.json"
                if existing:
                    export._publish(b"accepted", target)
                opened = []
                real_fdopen = os.fdopen
                class InterruptedClose:
                    def __init__(self, descriptor, mode, *, closefd):
                        self.descriptor = descriptor
                        self.stream = real_fdopen(descriptor, mode, closefd=closefd)
                        self.close_attempts = 0
                    def __getattr__(self, name):
                        return getattr(self.stream, name)
                    def close(self):
                        self.close_attempts += 1
                        raise KeyboardInterrupt()
                def construct(descriptor, mode, *, closefd):
                    self.assertFalse(closefd)
                    stream = InterruptedClose(descriptor, mode, closefd=closefd)
                    opened.append(stream)
                    return stream
                with patch.object(export.os, "fdopen", side_effect=construct), patch.object(
                    export.os, "close", wraps=os.close
                ) as close:
                    with self.assertRaises(KeyboardInterrupt) as caught:
                        export._publish(b"accepted", target)
                    self.assertEqual(close.call_count, 2)
                stream, = opened
                self.assertEqual(stream.close_attempts, 1)
                with self.assertRaises(OSError) as closed:
                    os.fstat(stream.descriptor)
                self.assertEqual(closed.exception.errno, errno.EBADF)
                self.assertEqual([f.stage for f in caught.exception.cleanup_failures], ["stream_close"])
                stream.stream.close()
                self.assertEqual(list(Path(directory).glob(".pending-export-*")), [])
                if existing:
                    self.assertEqual(target.read_bytes(), b"accepted")

    def test_partial_stream_construction_keeps_raw_ownership(self):
        wrappers = []
        real_fdopen = os.fdopen
        def partial(descriptor, mode, *, closefd):
            self.assertFalse(closefd)
            wrappers.append(real_fdopen(descriptor, mode, closefd=closefd))
            raise OSError("private constructor failure")
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(export.os, "fdopen", side_effect=partial), patch.object(
                export.os, "close", wraps=os.close
            ) as close:
                with self.assertRaises(OSError):
                    export._publish(b"accepted", Path(directory) / "observation.json")
                self.assertEqual(close.call_count, 2)
            with self.assertRaises(OSError) as closed:
                os.fstat(wrappers[0].fileno())
            self.assertEqual(closed.exception.errno, errno.EBADF)
            wrappers[0].close()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_cli_keeps_interruption_exit_distinct_when_cleanup_also_fails(self):
        script = '''
import sys
from unittest.mock import patch
from lims_eln_implementation.workbench import export
failure = {"control": KeyboardInterrupt(), "ordinary": OSError("private primary"),
           "exit": SystemExit(23)}[sys.argv.pop(1)]
with patch.object(export, "validate_observation_bytes", return_value=None), patch.object(
    export.os, "link", side_effect=failure
), patch.object(export.os, "unlink", side_effect=OSError("private cleanup")):
    raise SystemExit(export.main())
'''
        for kind, expected in (("control", 130), ("ordinary", 1), ("exit", 23)):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                result = subprocess.run(
                    [sys.executable, "-c", script, kind, "--tenant", "SYN-TENANT", "--run", "SYN-RUN",
                     "--output", str(Path(directory) / "observation.json")],
                    input=b"{}", capture_output=True, timeout=10,
                )
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(result.stdout, b"")
                self.assertNotIn(b"private", result.stderr)
                self.assertNotIn(directory.encode(), result.stderr)
