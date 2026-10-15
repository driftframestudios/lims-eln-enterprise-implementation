"""Acquisition, publication and cleanup faults retain owned storage and control."""

import errno
import io
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
                    export.io, "FileIO", side_effect=OSError("private transfer")
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
        real_buffer = io.BufferedWriter
        class InterruptedStream:
            def __init__(self, raw):
                self.stream = real_buffer(raw)
                self.close_attempts = 0
            def write(self, payload):
                raise primary
            def close(self):
                self.close_attempts += 1
                self.stream.close()
                raise control
        streams = []
        def open_stream(raw):
            stream = InterruptedStream(raw)
            streams.append(stream)
            return stream
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(export.io, "BufferedWriter", side_effect=open_stream):
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
                real_buffer = io.BufferedReader if existing else io.BufferedWriter
                class InterruptedClose:
                    def __init__(self, raw):
                        self.descriptor = raw.fileno()
                        self.stream = real_buffer(raw)
                        self.close_attempts = 0
                    def __getattr__(self, name):
                        return getattr(self.stream, name)
                    def close(self):
                        self.close_attempts += 1
                        raise KeyboardInterrupt()
                def construct(raw):
                    self.assertFalse(raw.closefd)
                    stream = InterruptedClose(raw)
                    opened.append(stream)
                    return stream
                with patch.object(export.io, real_buffer.__name__, side_effect=construct), patch.object(
                    export.os, "close", wraps=os.close
                ) as close:
                    with self.assertRaises(KeyboardInterrupt) as caught:
                        export._publish(b"accepted", target)
                    self.assertEqual(close.call_count, 2)
                stream, = opened
                self.assertEqual(stream.close_attempts, 1)
                self.assertTrue(stream.stream.raw.closed)
                with self.assertRaises(OSError) as closed:
                    os.fstat(stream.descriptor)
                self.assertEqual(closed.exception.errno, errno.EBADF)
                self.assertEqual([f.stage for f in caught.exception.cleanup_failures], ["stream_close"])
                stream.stream.close()
                self.assertEqual(list(Path(directory).glob(".pending-export-*")), [])
                if existing:
                    self.assertEqual(target.read_bytes(), b"accepted")

    def test_partial_stream_construction_keeps_raw_ownership(self):
        for existing in (False, True):
            wrappers = []
            descriptors = []
            real_buffer = io.BufferedReader if existing else io.BufferedWriter
            def partial(raw):
                descriptors.append(raw.fileno())
                wrappers.append(real_buffer(raw))
                raise OSError("private constructor failure")
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "observation.json"
                if existing:
                    export._publish(b"accepted", target)
                with patch.object(export.io, real_buffer.__name__, side_effect=partial), patch.object(
                    export.os, "close", wraps=os.close
                ) as close:
                    with self.assertRaises(OSError):
                        export._publish(b"accepted", target)
                    self.assertEqual(close.call_count, 2)
                self.assertTrue(wrappers[0].raw.closed)
                with self.assertRaises(OSError) as closed:
                    os.fstat(descriptors[0])
                self.assertEqual(closed.exception.errno, errno.EBADF)
                wrappers[0].close()
                self.assertEqual(list(Path(directory).glob(".pending-export-*")), [])
                if existing:
                    self.assertEqual(target.read_bytes(), b"accepted")

    def test_late_buffer_release_preserves_the_next_descriptor_owner(self):
        for existing in (False, True):
            for primary_type, secondary_type in (
                (OSError, KeyboardInterrupt), (KeyboardInterrupt, OSError),
                (SystemExit, KeyboardInterrupt), (OSError, OSError),
            ):
                primary = primary_type("private operation")
                secondary = secondary_type("private teardown")
                opened = []
                real_buffer = io.BufferedReader if existing else io.BufferedWriter
                class FailedStream:
                    def __init__(self, raw):
                        self.descriptor = raw.fileno()
                        self.stream = real_buffer(raw)
                    def __getattr__(self, name):
                        return getattr(self.stream, name)
                    def read(self, size):
                        self.stream.peek(1)
                        raise primary
                    def flush(self):
                        raise primary
                    def close(self):
                        raise secondary
                def construct(raw):
                    stream = FailedStream(raw)
                    opened.append(stream)
                    return stream
                with self.subTest(existing=existing, primary=primary_type, secondary=secondary_type), tempfile.TemporaryDirectory() as directory:
                    target = Path(directory) / "observation.json"
                    if existing:
                        export._publish(b"accepted", target)
                    expected = primary_type if primary_type is not OSError else (
                        secondary_type if secondary_type is KeyboardInterrupt else export.ExportError
                    )
                    with patch.object(export, "validate_observation_bytes", return_value=None), patch.object(
                        export.io, real_buffer.__name__, side_effect=construct
                    ):
                        with self.assertRaises(expected) as caught:
                            export.export_observation(b"accepted", target, tenant_id="SYN-TENANT", run_id="SYN-RUN")
                    observed = caught.exception
                    if primary_type is not OSError:
                        self.assertIs(observed, primary)
                    elif secondary_type is KeyboardInterrupt:
                        self.assertIs(observed, secondary)
                        self.assertIs(observed.primary_error, primary)
                    else:
                        self.assertIs(observed.primary_error, primary)
                        self.assertNotIn("private", str(observed))
                    self.assertEqual(observed.publication_state, "unpublished")
                    self.assertEqual(observed.pending_state, "absent")
                    self.assertEqual([f.error for f in observed.cleanup_failures], [secondary])
                    stream, = opened
                    with self.assertRaises(OSError) as closed:
                        os.fstat(stream.descriptor)
                    self.assertEqual(closed.exception.errno, errno.EBADF)
                    later = Path(directory) / "later-owner.bin"
                    later.write_bytes(b"later accepted bytes")
                    descriptor = os.open(later, os.O_RDWR)
                    if descriptor != stream.descriptor:
                        os.dup2(descriptor, stream.descriptor)
                    try:
                        # Exercise late close itself before inspecting implementation state.
                        stream.stream.close()
                        self.assertEqual(later.read_bytes(), b"later accepted bytes")
                        self.assertTrue(stream.stream.raw.closed)
                        os.fstat(stream.descriptor)
                        if existing:
                            self.assertEqual(target.read_bytes(), b"accepted")
                        else:
                            self.assertFalse(target.exists())
                    finally:
                        os.close(stream.descriptor)
                        if descriptor != stream.descriptor:
                            os.close(descriptor)

    def test_raw_close_failure_retains_live_stream_and_descriptor_for_reconciliation(self):
        real_raw, real_buffer = io.FileIO, io.BufferedWriter
        for failure_type in (OSError, KeyboardInterrupt, SystemExit):
            primary = OSError("private flush")
            secondary = OSError("private buffer close")
            failure = failure_type("private raw close")
            acquired = []
            class RetainedRaw(real_raw):
                def close(self):
                    raise failure
            class FailedBuffer:
                def __init__(self, raw):
                    self.stream = real_buffer(raw)
                def __getattr__(self, name):
                    return getattr(self.stream, name)
                def flush(self):
                    raise primary
                def close(self):
                    raise secondary
            def construct(descriptor, mode, *, closefd):
                raw = RetainedRaw(descriptor, mode, closefd=closefd)
                acquired.append(raw)
                return raw
            with self.subTest(failure=failure_type), tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "observation.json"
                try:
                    with patch.object(export, "validate_observation_bytes", return_value=None), patch.object(
                        export.io, "FileIO", side_effect=construct
                    ), patch.object(export.io, "BufferedWriter", side_effect=FailedBuffer), patch.object(
                        export.os, "close", wraps=os.close
                    ) as close:
                        expected = export.ExportError if failure_type is OSError else failure_type
                        with self.assertRaises(expected) as caught:
                            export.export_observation(b"accepted", target, tenant_id="SYN-TENANT", run_id="SYN-RUN")
                        self.assertEqual(close.call_count, 1)  # The directory can still release.
                    owner = caught.exception.primary_error if failure_type is OSError else caught.exception
                    raw, = acquired
                    self.assertIs(owner.retained_stream, raw)
                    self.assertEqual(owner.retained_descriptor, raw.fileno())
                    self.assertFalse(raw.closed)
                    os.fstat(owner.retained_descriptor)
                    self.assertEqual([f.error for f in owner.cleanup_failures], [secondary, failure])
                    self.assertEqual(caught.exception.publication_state, "unpublished")
                    self.assertEqual(caught.exception.pending_state, "absent")
                    self.assertEqual(list(Path(directory).iterdir()), [])
                    if failure_type is not OSError:
                        self.assertIs(caught.exception, failure)
                        self.assertIs(failure.primary_error, primary)
                finally:
                    for raw in acquired:
                        descriptor = raw.fileno()
                        real_raw.close(raw)
                        os.close(descriptor)

    def test_direct_raw_invalidation_follows_interrupted_buffer_owned_close(self):
        real_raw = io.FileIO
        control = KeyboardInterrupt()
        acquired = []
        class InterruptedRaw(real_raw):
            attempts = 0
            def close(self):
                self.attempts += 1
                if self.attempts == 1:
                    raise control
                real_raw.close(self)
        def construct(descriptor, mode, *, closefd):
            raw = InterruptedRaw(descriptor, mode, closefd=closefd)
            acquired.append((raw, descriptor))
            return raw
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(export.io, "FileIO", side_effect=construct), patch.object(
                export.os, "close", wraps=os.close
            ) as close:
                with self.assertRaises(KeyboardInterrupt) as caught:
                    export._publish(b"accepted", Path(directory) / "observation.json")
                self.assertEqual(close.call_count, 2)
            self.assertIs(caught.exception, control)
            raw, descriptor = acquired[0]
            self.assertEqual(raw.attempts, 2)
            self.assertTrue(raw.closed)
            with self.assertRaises(OSError) as closed:
                os.fstat(descriptor)
            self.assertEqual(closed.exception.errno, errno.EBADF)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_raw_close_that_invalidates_then_raises_still_releases_descriptor(self):
        real_raw, real_buffer = io.FileIO, io.BufferedWriter
        control = KeyboardInterrupt()
        descriptors = []
        class ClosedRaw(real_raw):
            def close(self):
                real_raw.close(self)
                raise control
        class FailedBuffer:
            def __init__(self, raw):
                self.stream = real_buffer(raw)
            def __getattr__(self, name):
                return getattr(self.stream, name)
            def close(self):
                raise OSError("private buffer close")
        def construct(descriptor, mode, *, closefd):
            descriptors.append(descriptor)
            return ClosedRaw(descriptor, mode, closefd=closefd)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(export.io, "FileIO", side_effect=construct), patch.object(
                export.io, "BufferedWriter", side_effect=FailedBuffer
            ), patch.object(export.os, "close", wraps=os.close) as close:
                with self.assertRaises(KeyboardInterrupt) as caught:
                    export._publish(b"accepted", Path(directory) / "observation.json")
                self.assertEqual(close.call_count, 2)
            self.assertIs(caught.exception, control)
            self.assertFalse(hasattr(control, "retained_descriptor"))
            with self.assertRaises(OSError) as closed:
                os.fstat(descriptors[0])
            self.assertEqual(closed.exception.errno, errno.EBADF)
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
