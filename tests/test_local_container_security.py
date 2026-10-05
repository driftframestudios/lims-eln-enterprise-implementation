"""Parameterized secret-lifetime and build-boundary counterexamples."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import signal
import stat
import subprocess
import sys
import tempfile
import unittest
import time
from hashlib import sha256
from unittest.mock import patch

from scripts.prepare_local_secrets import NAMES, PreparationError, prepare
from scripts.prepare_container_context import ContextError, member_digests, requirements_admitted, stage_wheels

ROOT = Path(__file__).resolve().parents[1]


class LocalSecretPreparationTests(unittest.TestCase):
    def test_creation_reuse_and_partial_completion_preserve_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "state"
            self.assertEqual(prepare(directory)["created"], 8)
            values = {p.name: p.read_bytes() for p in directory.glob("*.txt")}
            self.assertEqual(prepare(directory), {"status": "prepared", "created": 0, "retained": 8})
            missing = directory / "minio_password.txt"
            missing.unlink()
            self.assertEqual(prepare(directory)["created"], 1)
            for name, value in values.items():
                if name != missing.name:
                    self.assertEqual((directory / name).read_bytes(), value)
                self.assertEqual(stat.S_IMODE((directory / name).stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)

    def test_invalid_existing_files_preserve_other_credentials(self):
        for kind in ("empty", "oversize", "alphabet", "permissions", "symlink", "directory", "fifo", "hardlink"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary) / "state"
                prepare(directory)
                retained = directory / "postgres_password.txt"
                original = retained.read_bytes()
                invalid = directory / "postgres_app_password.txt"
                invalid.unlink()
                if kind == "symlink":
                    invalid.symlink_to(retained)
                elif kind == "directory":
                    invalid.mkdir()
                elif kind == "fifo":
                    os.mkfifo(invalid, 0o600)
                elif kind == "hardlink":
                    os.link(retained, invalid)
                else:
                    value = {"empty": b"", "oversize": b"a" * 1025, "alphabet": b"Z" * 64 + b"\n"}.get(kind, b"a" * 64 + b"\n")
                    invalid.write_bytes(value)
                    invalid.chmod(0o644 if kind == "permissions" else 0o600)
                with self.assertRaises(PreparationError):
                    prepare(directory)
                self.assertEqual(retained.read_bytes(), original)

    def test_directory_boundary_and_interrupted_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            with self.assertRaises(PreparationError):
                prepare(parent / "inside", repository=parent)
            directory = parent / "state"
            directory.mkdir(mode=0o700)
            with patch("scripts.prepare_local_secrets.os.link", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    prepare(directory)
            self.assertEqual(list(directory.glob("*.txt")), [])
            self.assertEqual(list(directory.glob(".pending-*")), [])
            self.assertEqual(prepare(directory)["created"], 8)
            alias = parent / "alias"
            alias.symlink_to(directory, target_is_directory=True)
            with self.assertRaises(PreparationError):
                prepare(alias)
            directory.chmod(0o755)
            with self.assertRaises(PreparationError):
                prepare(directory)

    def test_external_path_error_uses_value_free_cli_diagnostic(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "state"
            prepare(directory)
            canary = secrets.token_hex(32)
            target = directory / "postgres_password.txt"
            target.write_text(canary + "'\n")
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/prepare_local_secrets.py"), str(directory)],
                text=True, capture_output=True, timeout=10,
            )
            self.assertEqual(result.returncode, 1)
            self.assertNotIn(canary, result.stdout + result.stderr)
            self.assertNotIn(str(directory), result.stdout + result.stderr)


FAKE_CLIENT = r'''
import hashlib, json, os, pathlib, re, signal, stat, subprocess, sys, time
root = pathlib.Path(os.environ["LIMS_SECRET_DIR"])
values = [p.read_text().strip() for p in root.iterdir()]
args = sys.argv[1:]
data = sys.stdin.read() if not any(arg.startswith(("--command=", "--file=")) for arg in args) else ""
transport = json.dumps({"args": args, "env": dict(os.environ)})
password_path = os.environ.get("PGPASSFILE")
password = pathlib.Path(password_path).read_text() if password_path else ""
record = {
    "pid": os.getpid(),
    "argv_environment_clear": all(value not in transport for value in values),
    "stdin_received": sum(value in data for value in values),
    "password_file_received": sum(value in password for value in values),
    "password_file_mode": stat.S_IMODE(pathlib.Path(password_path).stat().st_mode) if password_path else None,
}
with open(os.environ["FAKE_RECORD"], "a") as target:
    target.write(json.dumps(record) + "\n")
mode = os.environ["FAKE_MODE"]
if os.environ.get("FAKE_DATABASE") and data:
    match = re.search(r"\\set application_password '([a-f0-9]{64})'", data)
    if match:
        pathlib.Path(os.environ["FAKE_DATABASE"]).write_text(
            hashlib.sha256(match[1].encode()).hexdigest()
        )
if mode == "launcher":
    child = subprocess.Popen(
        [sys.executable, __file__], env={**os.environ, "FAKE_MODE": "stall"}
    )
    raise SystemExit(child.wait())
if mode == "stall":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(60)
if mode in ("failure", "failure-after-commit"):
    print(values[0])
    print(values[0], file=sys.stderr)
    raise SystemExit(17)
if mode == "interrupt":
    os.kill(os.getppid(), signal.SIGTERM)
    raise SystemExit(0)
query = " ".join(args)
if "rolcanlogin" in query:
    print("true:false:false:false:false:false")
elif "pg_auth_members" in query:
    print("false:false:true")
elif "pg_db_role_setting" in query:
    print("role=laboratory_owner")
elif "session_user" in query:
    print("laboratory_migrator:laboratory_owner:laboratory_owner")
elif "select current_user" in query:
    print("laboratory_app|f|f")
'''


SET_SID_CLIENT = "import os, sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])"


class LocalSecretTransportTests(unittest.TestCase):
    def test_clients_receive_protected_input_with_bounded_output_and_cleanup(self):
        scripts = (
            "infra/provision-migrator-identity.sh",
            "infra/postgres-init/010_application_password.sh",
            "infra/run-flyway-with-secret.sh",
            "infra/check-application-identity.sh",
        )
        for script in scripts:
            for mode in ("success", "failure", "interrupt"):
                with self.subTest(script=script, mode=mode), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    secret_dir, binaries, scratch = (root / name for name in ("secrets", "bin", "scratch"))
                    for directory in (secret_dir, binaries, scratch):
                        directory.mkdir(mode=0o700)
                    values = []
                    for name in NAMES:
                        value = secrets.token_hex(32)
                        values.append(value)
                        (secret_dir / name).write_text(value + "\n")
                        (secret_dir / name).chmod(0o600)
                    for name in ("psql", "flyway", "setsid"):
                        executable = binaries / name
                        executable.write_text("#!" + sys.executable + "\n" + (SET_SID_CLIENT if name == "setsid" else FAKE_CLIENT))
                        executable.chmod(0o700)
                    record = root / "record.jsonl"
                    environment = {
                        "PATH": str(binaries) + os.pathsep + "/usr/bin:/bin",
                        "LIMS_SECRET_DIR": str(secret_dir),
                        "LIMS_SECRET_HELPER": str(ROOT / "infra/secret-files.sh"),
                        "TMPDIR": str(scratch), "FAKE_MODE": mode, "FAKE_RECORD": str(record),
                        "POSTGRES_USER": "laboratory_bootstrap", "POSTGRES_DB": "laboratory",
                        "PGPASSWORD": values[0], "FLYWAY_PASSWORD": values[1],
                    }
                    result = subprocess.run(
                        ["/bin/sh", str(ROOT / script)], env=environment, capture_output=True,
                        text=True, timeout=10,
                    )
                    if mode == "success":
                        self.assertEqual(result.returncode, 0, result.stderr)
                    else:
                        self.assertNotEqual(result.returncode, 0)
                    records = [json.loads(row) for row in record.read_text().splitlines()]
                    self.assertTrue(records)
                    self.assertTrue(all(item["argv_environment_clear"] for item in records))
                    self.assertTrue(any(item["stdin_received"] or item["password_file_received"] for item in records))
                    if script.endswith("010_application_password.sh") and mode == "success":
                        self.assertEqual(records[0]["stdin_received"], 5)
                    for item in records:
                        if item["password_file_mode"] is not None:
                            self.assertEqual(item["password_file_mode"], 0o600)
                    for value in values:
                        self.assertNotIn(value, result.stdout + result.stderr + record.read_text())
                    self.assertEqual(list(scratch.iterdir()), [])

    def test_parent_termination_reaps_a_stalled_client_before_cleanup(self):
        for script in (
            "infra/provision-migrator-identity.sh",
            "infra/postgres-init/010_application_password.sh",
            "infra/run-flyway-with-secret.sh",
            "infra/check-application-identity.sh",
        ):
            with self.subTest(script=script), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                binary = root / "bin"
                binary.mkdir()
                scratch = root / "scratch"
                scratch.mkdir()
                secrets_dir = root / "secrets"
                secrets_dir.mkdir()
                for name in NAMES:
                    (secrets_dir / name).write_text(secrets.token_hex(32) + "\n")
                for name in ("psql", "flyway", "setsid"):
                    target = binary / name
                    target.write_text("#!" + sys.executable + "\n" + (SET_SID_CLIENT if name == "setsid" else FAKE_CLIENT))
                    target.chmod(0o700)
                record = root / "record"
                environment = {
                    "PATH": str(binary) + ":/usr/bin:/bin", "TMPDIR": str(scratch),
                    "LIMS_SECRET_DIR": str(secrets_dir),
                    "LIMS_SECRET_HELPER": str(ROOT / "infra/secret-files.sh"),
                    "FAKE_MODE": "launcher", "FAKE_RECORD": str(record),
                    "POSTGRES_USER": "laboratory_bootstrap", "POSTGRES_DB": "laboratory",
                }
                process = subprocess.Popen(
                    ["/bin/sh", str(ROOT / script)], env=environment,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                )
                try:
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        if record.exists() and len(record.read_text().splitlines()) == 2:
                            break
                        time.sleep(0.01)
                    self.assertTrue(record.exists(), "launcher reached its controlled stall")
                    self.assertEqual(len(record.read_text().splitlines()), 2)
                    # The client installs its handler immediately after publishing the record.
                    time.sleep(0.05)
                    process.terminate()
                    output, errors = process.communicate(timeout=8)
                    self.assertEqual(process.returncode, 143, output + errors)
                    for row in record.read_text().splitlines():
                        observation = json.loads(row)
                        with self.assertRaises(ProcessLookupError):
                            os.kill(observation["pid"], 0)
                    self.assertEqual(list(scratch.iterdir()), [])
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)
                    process.stdout.close()
                    process.stderr.close()

    def test_uncertain_rotation_reapplies_prior_values_before_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary, scratch = root / "bin", root / "scratch"
            binary.mkdir()
            scratch.mkdir()
            executable = binary / "psql"
            executable.write_text("#!" + sys.executable + "\n" + FAKE_CLIENT)
            executable.chmod(0o700)
            session = binary / "setsid"
            session.write_text("#!" + sys.executable + "\n" + SET_SID_CLIENT)
            session.chmod(0o700)
            database = root / "database-fingerprint"
            old_value, candidate_value = secrets.token_hex(32), secrets.token_hex(32)
            environment = {
                "PATH": str(binary) + ":/usr/bin:/bin", "TMPDIR": str(scratch),
                "LIMS_SECRET_HELPER": str(ROOT / "infra/secret-files.sh"),
                "FAKE_RECORD": str(root / "record"), "FAKE_DATABASE": str(database),
                "POSTGRES_USER": "laboratory_bootstrap", "POSTGRES_DB": "laboratory",
            }
            for name, value, mode, expected_status in (
                ("candidate", candidate_value, "failure-after-commit", 1),
                ("previous", old_value, "success", 0),
            ):
                directory = root / name
                directory.mkdir()
                for stem in NAMES:
                    (directory / stem).write_text(
                        (value if stem == "postgres_app_password" else "a" * 64) + "\n"
                    )
                result = subprocess.run(
                    ["/bin/sh", str(ROOT / "infra/postgres-init/010_application_password.sh")],
                    env={**environment, "LIMS_SECRET_DIR": str(directory), "FAKE_MODE": mode},
                    text=True, capture_output=True, timeout=10,
                )
                self.assertEqual(result.returncode, expected_status)
                self.assertEqual(database.read_text(), sha256(value.encode()).hexdigest())
                self.assertNotIn(value, result.stdout + result.stderr)
                self.assertEqual(list(scratch.iterdir()), [])
            self.assertEqual(database.read_text(), sha256(old_value.encode()).hexdigest())

    def test_malformed_secret_stops_before_a_client_runs(self):
        for value in ("", "a" * 130, "with space", "with\nnewline", "quote'", "\\escape"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "postgres_migrator_password").write_text(value)
                result = subprocess.run(
                    ["/bin/sh", str(ROOT / "infra/run-flyway-with-secret.sh")],
                    env={"PATH": "/usr/bin:/bin", "TMPDIR": temporary,
                         "LIMS_SECRET_DIR": temporary,
                         "LIMS_SECRET_HELPER": str(ROOT / "infra/secret-files.sh")},
                    text=True, capture_output=True, timeout=10,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(list(root.glob("lims-credentials.*")), [])


class ContainerBuildBoundaryTests(unittest.TestCase):
    def test_hash_requirements_admit_registry_versions_and_reject_locators(self):
        digest = "a" * 64
        for value, expected in (
            ("fastapi==0.142.2 \\\n    --hash=sha256:" + digest, True),
            ("typing-extensions==4.15.0 ; python_version < '3.13'\n--hash=sha256:" + digest, True),
            ("", False), ("package @ https://example.invalid/wheel", False),
            ("--index-url https://example.invalid", False), ("../package", False),
            ("package==1\n--hash=sha256:short", False),
        ):
            with self.subTest(value=value):
                self.assertEqual(requirements_admitted(value), expected)

    def test_context_members_reject_symlinks_and_measure_exact_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "requirements.txt").write_bytes(b"owned")
            self.assertEqual(set(member_digests(root)), {"requirements.txt"})
            (root / "link").symlink_to(root / "requirements.txt")
            with self.assertRaises(ContextError):
                member_digests(root)

    def test_wheel_projection_excludes_housekeeping_and_rejects_surplus_wheels(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "build"
            source.mkdir()
            expected = {"first.whl", "second.whl"}
            for name in expected:
                (source / name).write_bytes(name.encode())
            (source / ".gitignore").write_text("*\n")
            (source / "private-build-note").write_text("local-only")
            target = root / "context"
            stage_wheels(source, target, expected)
            self.assertEqual({path.name for path in target.iterdir()}, expected)
            for name in expected:
                self.assertEqual((target / name).read_bytes(), name.encode())
            (source / "surplus.whl").write_bytes(b"extra")
            with self.assertRaises(ContextError):
                stage_wheels(source, root / "rejected", expected)
            self.assertFalse((root / "rejected").exists())

    def test_application_profile_has_finite_runtime_grants(self):
        compose = (ROOT / "infra/docker-compose.yml").read_text()
        app = compose.split("\n  application:\n", 1)[1].split("\n  object-store:", 1)[0]
        for marker in (
            'profiles: ["workbench"]', "read_only: true", 'cap_drop: ["ALL"]',
            'security_opt: ["no-new-privileges:true"]', "pids_limit: 128",
            "mem_limit: 512m", "size=16m", "127.0.0.1:", "postgres_app_password",
            "postgres_tenant_hmac_key", "service_completed_successfully",
        ):
            self.assertIn(marker, app)
        for marker in ("postgres_password", "postgres_migrator_password", "docker.sock", "privileged:"):
            self.assertNotIn(marker, app)
        dockerfile = (ROOT / "infra/application.Dockerfile").read_text()
        self.assertIn("USER 10001:10001", dockerfile)
        self.assertIn("--require-hashes --only-binary=:all:", dockerfile)
        self.assertIn("--no-access-log", dockerfile)
        self.assertNotIn("COPY . ", dockerfile)
