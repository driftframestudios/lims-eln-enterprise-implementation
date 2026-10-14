"""Source composition checks and one explicitly selected local launcher journey."""

from base64 import b64encode
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from html.parser import HTMLParser
from importlib.metadata import version
import io
import json
import os
from pathlib import Path
import platform
import re
import socket
import stat
import subprocess
import sys
import tempfile
import time
import traceback
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from lims_eln_implementation.workbench import cli, runtime, shared_contracts
from lims_eln_implementation.workbench.postgres import PostgresWorkbenchService
from test_workbench_runtime import ReadinessCursor
from test_workbench_postgres_adapter import RecordingConnection


ROOT = Path(__file__).resolve().parents[1]
RAW = b'{"analyte":"synthetic-dna","value":"12.5","unit":"ng/uL"}'
SCHEMA = ROOT / "contracts/workbench-capabilities.v1.schema.json"


class AuthoredReading(HTMLParser):
    """Read server-authored text independently of script execution."""

    def __init__(self):
        super().__init__()
        self.hidden_depth = 0
        self.words = []
        self.package_versions = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden_depth += 1
        for key, value in attrs:
            if key == "data-expected-package-version":
                self.package_versions.append(value)

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden_depth -= 1

    def handle_data(self, data):
        if not self.hidden_depth:
            self.words.append(data)


def assert_composition(case, get, *, compatible=True):
    response = get("/api/workbench/capabilities")
    case.assertEqual(response.status_code, 200)
    case.assertEqual(response.headers["cache-control"], "no-store")
    document = response.json()
    Draft202012Validator(json.loads(SCHEMA.read_text())).validate(document)
    case.assertEqual(document["runtime"], {
        "state_adapter": "postgresql", "state_lifetime": "database",
        "access_scope": "local_reference",
    })
    case.assertEqual(document["shared_contracts"], {
        "expected_package_version": shared_contracts.EXPECTED_PACKAGE_VERSION,
        "expected_contract_version": shared_contracts.EXPECTED_CONTRACT_VERSION,
        "version_compatible": compatible,
    })
    case.assertNotIn(runtime.TENANT_ID, response.text)
    page = get("/workbench")
    case.assertEqual(page.status_code, 200)
    case.assertEqual(page.headers["cache-control"], "no-store")
    reading = AuthoredReading()
    reading.feed(page.text)
    text = " ".join(" ".join(reading.words).split())
    case.assertIn("PostgreSQL-backed state", text)
    case.assertNotIn("Process-local state", text)
    posture = "version compatible" if compatible else "compatible package needed"
    case.assertIn(f"Shared contracts {shared_contracts.EXPECTED_PACKAGE_VERSION}: {posture}", text)
    case.assertEqual(reading.package_versions, [shared_contracts.EXPECTED_PACKAGE_VERSION])
    case.assertIn('href="/api/workbench/capabilities"', page.text)
    return document


def assert_expected_specimen(case, document, specimen_id):
    """Literal expected content prevents empty-before/empty-after persistence claims."""
    case.assertEqual(document["tenant_id"], "SYN-TENANT-A")
    case.assertEqual(document["specimen_id"], specimen_id)
    case.assertEqual(document["state"], "released")
    case.assertEqual(document["version"], 5)
    case.assertEqual(len(document["events"]), 5)
    case.assertEqual(document["events"][-1]["event_type"], "specimen.release")
    case.assertEqual(document["custody"]["location"], "SYN-LAB-A/RECEIVING")
    case.assertEqual(len(document["instrument_receipts"]), 1)
    receipt = document["instrument_receipts"][0]
    case.assertEqual(receipt["raw_sha256"], sha256(RAW).hexdigest())
    measurement = receipt["normalized_observation"]
    case.assertEqual(
        (measurement["analyte"], measurement["value"], measurement["unit"]),
        ("synthetic-dna", "12.5", "ng/uL"),
    )
    case.assertIs(document["projection"]["reconciled"], True)


class LauncherCompositionTests(unittest.TestCase):
    @contextmanager
    def configured_factory(self, connect):
        with tempfile.TemporaryDirectory() as directory:
            password = Path(directory) / "password"
            key = Path(directory) / "key"
            password.write_text("capability-password-canary", encoding="ascii")
            key.write_text("a1" * 32, encoding="ascii")
            environment = {
                "LIMS_WORKBENCH_ADAPTER": "postgresql",
                "LIMS_WORKBENCH_DB_HOST": "capability-host.invalid",
                "LIMS_WORKBENCH_DB_NAME": "capability_database_canary",
                "LIMS_WORKBENCH_DB_PASSWORD_FILE": str(password),
                "LIMS_WORKBENCH_TENANT_KEY_FILE": str(key),
            }
            with patch.dict(os.environ, environment, clear=True), patch.dict(
                sys.modules, {"psycopg": SimpleNamespace(connect=connect)}
            ):
                yield runtime.create_configured_app(), environment

    def test_real_factory_keeps_composition_stable_through_dependency_up_down_up(self):
        first = RecordingConnection(ReadinessCursor())
        recovered = RecordingConnection(ReadinessCursor())
        connect = Mock(side_effect=[first, OSError("protected-outage-canary"), recovered])
        with self.configured_factory(connect) as (app, environment), TestClient(app) as client:
            self.assertIsInstance(app.state.workbench, PostgresWorkbenchService)
            document = assert_composition(self, client.get)
            connect.assert_not_called()
            for status, posture in ((200, "ready"), (503, "waiting_for_dependencies"), (200, "ready")):
                response = client.get("/health/ready")
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertEqual(response.json(), {"status": posture, "state_adapter": "postgresql"})
                self.assertNotIn("protected-outage-canary", response.text)
                self.assertEqual(client.get("/health/live").status_code, 200)
                self.assertEqual(assert_composition(self, client.get), document)
            self.assertEqual(connect.call_count, 3)
            self.assertTrue(first.closed and recovered.closed)
            for secret in (
                "capability-password-canary", "a1" * 32,
                environment["LIMS_WORKBENCH_DB_HOST"],
                environment["LIMS_WORKBENCH_DB_NAME"],
                environment["LIMS_WORKBENCH_DB_PASSWORD_FILE"],
                environment["LIMS_WORKBENCH_TENANT_KEY_FILE"],
            ):
                self.assertNotIn(secret, client.get("/api/workbench/capabilities").text)
                self.assertNotIn(secret, client.get("/workbench").text)

    def test_incompatible_package_and_contract_stop_before_credentials_or_connection(self):
        for package_version, contract_version in (
            ("0.0.0", shared_contracts.EXPECTED_CONTRACT_VERSION),
            (shared_contracts.EXPECTED_PACKAGE_VERSION, "0.0.0"),
        ):
            with self.subTest(package=package_version, contract=contract_version):
                package = SimpleNamespace(__version__=package_version, CONTRACT_VERSION=contract_version)
                connect = Mock()
                with patch.object(shared_contracts, "import_module", return_value=package), patch.object(
                    runtime, "_read_secret"
                ) as read_secret:
                    with self.assertRaises(runtime.RuntimeConfigurationError) as caught:
                        with self.configured_factory(connect):
                            self.fail("incompatible factory requires a configuration decision")
                    self.assertEqual(str(caught.exception), "PostgreSQL entry requires the reviewed contracts extra")
                    read_secret.assert_not_called()
                    connect.assert_not_called()

    def test_changed_package_reports_compatibility_separately_from_dependency(self):
        connect = Mock(return_value=RecordingConnection(ReadinessCursor()))
        with self.configured_factory(connect) as (app, _), TestClient(app) as client:
            with patch.object(shared_contracts, "import_module", return_value=SimpleNamespace(
                __version__="0.0.0", CONTRACT_VERSION=shared_contracts.EXPECTED_CONTRACT_VERSION
            )):
                assert_composition(self, client.get, compatible=False)
                self.assertEqual(client.get("/health/ready").status_code, 200)
            self.assertEqual(connect.call_count, 1)

    def test_unsupported_runtime_and_launcher_configuration_are_bounded(self):
        value = "unsupported-configuration-canary"
        with patch.dict(os.environ, {"LIMS_WORKBENCH_ADAPTER": value}, clear=True):
            with self.assertRaises(runtime.RuntimeConfigurationError) as caught:
                runtime.create_configured_app()
            self.assertNotIn(value, str(caught.exception))
            stderr = io.StringIO()
            with patch("sys.argv", ["lims-eln-workbench"]), patch("sys.stderr", stderr), patch.object(
                cli.uvicorn, "run"
            ) as run, self.assertRaises(SystemExit) as stopped:
                cli.main()
            self.assertEqual(stopped.exception.code, 2)
            self.assertIn("requires process_local or postgresql", stderr.getvalue())
            self.assertNotIn(value, stderr.getvalue())
            run.assert_not_called()


class LocalOnlyRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise RuntimeError("configured proof expects direct local responses")


@unittest.skipUnless(
    os.environ.get("LIMS_CONFIGURED_CAPABILITY_PROOF") == "1",
    "configured launcher journey awaits the Issue 68 handoff and owned local database",
)
class ConfiguredLauncherJourney(unittest.TestCase):
    """One Golden transaction; own child processes, preserve database and recovery artifacts."""

    def private_artifact(self, name, payload):
        descriptor = os.open(self.output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)

    def checkpoint(self, name, document):
        self.private_artifact(name + ".json", json.dumps(document, sort_keys=True, indent=2).encode())

    def request(self, path, *, payload=None, tenant=False):
        headers = {"X-Tenant-ID": runtime.TENANT_ID} if tenant else {}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = Request(self.origin + path, data=payload, headers=headers)
        try:
            response = self.opener.open(request, timeout=12)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read(2_000_001)
            self.assertLessEqual(len(raw), 2_000_000)
            return SimpleNamespace(
                status_code=response.code, headers=response.headers,
                text=raw.decode("utf-8"), json=lambda: json.loads(raw),
            )

    @contextmanager
    def launcher(self, label, environment):
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        self.origin = f"http://127.0.0.1:{port}"
        descriptor = os.open(self.output / (label + ".log"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "lims_eln_implementation.workbench.cli",
                 "--adapter", "postgresql", "--host", "127.0.0.1", "--port", str(port)],
                cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT,
            )
        primary = None
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("launcher exited before liveness")
                try:
                    if self.request("/health/live").status_code == 200:
                        break
                except (URLError, TimeoutError):
                    time.sleep(0.1)
            else:
                raise RuntimeError("launcher liveness deadline elapsed")
            yield
        except BaseException as error:
            primary = error
            raise
        finally:
            try:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
            except Exception:
                if primary is not None:
                    primary.add_note("Owned launcher cleanup requires operator inspection.")
                else:
                    raise RuntimeError("owned launcher cleanup remains unresolved") from None

    def ready(self, status):
        response = self.request("/health/ready")
        self.assertEqual(response.status_code, status)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.json(), {
            "status": "ready" if status == 200 else "waiting_for_dependencies",
            "state_adapter": "postgresql",
        })

    def test_launcher_composition_readiness_and_golden_persistence(self):
        self.stage = "configuration_admission"
        self.output = None
        try:
            self.journey()
        except Exception:
            failure = AssertionError(
                f"Issue 68 stopped at {self.stage}; preserve the owned database and local checkpoint."
            )
            if self.output is not None:
                try:
                    self.private_artifact("failure.txt", traceback.format_exc().encode())
                except Exception:
                    failure.add_note(
                        "Protected diagnostic storage is unavailable; "
                        "the original failure remains in local exception context."
                    )
            raise failure from None

    def journey(self):
        self.assertEqual(os.environ.get("LIMS_CAPABILITY_DATABASE_OWNERSHIP"), "owned_issue68")
        self.assertRegex(os.environ.get("LIMS_CAPABILITY_PROJECT", ""), r"\Alims-issue68-[a-f0-9]{12}\Z")
        self.assertEqual(os.environ.get("LIMS_WORKBENCH_ADAPTER"), "postgresql")
        self.assertEqual(os.environ.get("LIMS_WORKBENCH_DB_HOST"), "127.0.0.1")
        settings = runtime.settings_from_environment(os.environ)
        output_root = Path(os.environ["LIMS_CAPABILITY_PROOF_DIR"])
        info = output_root.lstat()
        self.assertTrue(stat.S_ISDIR(info.st_mode))
        self.assertEqual(info.st_uid, os.getuid())
        self.assertEqual(stat.S_IMODE(info.st_mode), 0o700)
        self.output = Path(tempfile.mkdtemp(prefix="journey-", dir=output_root))
        self.opener = build_opener(ProxyHandler({}), LocalOnlyRedirects())
        source = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, check=True,
            capture_output=True, text=True, timeout=5,
        ).stdout
        self.assertEqual(dirty, "", "configured proof requires a checkpointed clean source")
        self.assertTrue(shared_contracts.contract_available())
        self.checkpoint("00-source", {
            "source_commit": source, "python": platform.python_version(),
            "platform": platform.system(), "architecture": platform.machine(),
            "schema_sha256": sha256(SCHEMA.read_bytes()).hexdigest(),
            "lock_sha256": sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
            "packages": {name: version(name) for name in (
                "lims-eln-program-specification", "psycopg", "fastapi", "uvicorn",
            )},
            "started_at": datetime.now(UTC).isoformat(),
            "evidence_state": "candidate_local_checkpoint",
        })
        environment = {key: value for key, value in os.environ.items() if key in {
            "PATH", "LANG", "LC_ALL", "LIMS_WORKBENCH_ADAPTER", "LIMS_WORKBENCH_DB_HOST",
            "LIMS_WORKBENCH_DB_PORT", "LIMS_WORKBENCH_DB_NAME",
            "LIMS_WORKBENCH_DB_PASSWORD_FILE", "LIMS_WORKBENCH_TENANT_KEY_FILE",
            "LIMS_WORKBENCH_TENANT_KEY_ID",
        }}
        environment.update(PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1")
        suffix = uuid4().hex.upper()
        run_id, specimen_id = f"SYN-ISSUE68-RUN-{suffix}", f"SYN-ISSUE68-SPECIMEN-{suffix}"
        payload = json.dumps({
            "run_id": run_id, "specimen_id": specimen_id, "tenant_id": runtime.TENANT_ID,
            "actor_id": "SYN-ACTOR-01", "scientist_id": "SYN-SCIENTIST-01",
            "quality_actor_id": "SYN-QUALITY-01", "occurred_at": "2026-08-17T14:30:00+00:00",
            "raw_instrument_payload_base64": b64encode(RAW).decode("ascii"),
            "vendor_payload": {"status": "under_review"},
        }, sort_keys=True, separators=(",", ":")).encode()
        self.private_artifact("01-request.json", payload)
        specimen_path = f"/api/workbench/specimens/{specimen_id}?tenant_id={runtime.TENANT_ID}"
        self.stage = "initial_launcher"
        with self.launcher("initial", environment):
            composition = assert_composition(self, self.request)
            self.ready(200)
            self.assertEqual(self.request(specimen_path, tenant=True).status_code, 404)
            self.stage = "golden_transaction"
            created = self.request("/api/workbench/golden-runs", payload=payload, tenant=True)
            self.assertEqual(created.status_code, 201)
            original = created.json()["specimen"]
            assert_expected_specimen(self, original, specimen_id)
            self.checkpoint("02-created", created.json())
        self.stage = "application_restart"
        with self.launcher("restarted", environment):
            self.ready(200)
            self.assertEqual(assert_composition(self, self.request), composition)
            response = self.request(specimen_path, tenant=True)
            self.assertEqual(response.status_code, 200)
            assert_expected_specimen(self, response.json(), specimen_id)
            self.assertEqual(response.json(), original)
            observation = self.request(
                f"/api/workbench/observations/{run_id}?tenant_id={runtime.TENANT_ID}", tenant=True,
            )
            self.assertEqual(observation.status_code, 200)
            shared_contracts.validate_observation_bytes(
                observation.text.encode(), tenant_id=runtime.TENANT_ID, run_id=run_id,
            )
            detail = observation.json()["result"]["producer_detail"]["configuration"]
            self.assertEqual((detail["state_adapter"], detail["migration_head"]), ("postgresql", "005"))
            self.checkpoint("03-restarted", response.json())
        self.stage = "unavailable_dependency"
        with socket.socket() as unavailable:
            # A bound, non-listening socket reserves a refused loopback endpoint.
            unavailable.bind(("127.0.0.1", 0))
            refused_port = unavailable.getsockname()[1]
            self.assertNotEqual(refused_port, settings.port)
            fault_environment = {**environment, "LIMS_WORKBENCH_DB_PORT": str(refused_port)}
            with self.launcher("unavailable", fault_environment):
                self.ready(503)
                self.assertEqual(assert_composition(self, self.request), composition)
                self.assertEqual(self.request("/health/live").status_code, 200)
        self.stage = "restored_dependency"
        with self.launcher("restored", environment):
            self.ready(200)
            self.assertEqual(assert_composition(self, self.request), composition)
            response = self.request(specimen_path, tenant=True)
            self.assertEqual(response.status_code, 200)
            assert_expected_specimen(self, response.json(), specimen_id)
            self.assertEqual(response.json(), original)
        self.checkpoint("04-completed", {
            "result": "passed", "coverage": "configured_launcher_golden_specimen_persistence",
            "dependency_fault": "owned_application_connection_endpoint",
            "database_cleanup": "retained_for_named_owner",
            "completed_at": datetime.now(UTC).isoformat(),
        })


class ConfiguredProofFailureTests(unittest.TestCase):
    def stopped_case(self):
        case = ConfiguredLauncherJourney(
            "test_launcher_composition_readiness_and_golden_persistence"
        )
        primary = ValueError("primary-protected-canary")

        def fail_journey():
            case.stage = "golden_transaction"
            case.output = Path("protected-output-canary")
            raise primary

        return case, primary, fail_journey

    def test_diagnostic_write_failure_preserves_primary_context_and_bounded_report(self):
        case, primary, fail_journey = self.stopped_case()
        with patch.object(case, "journey", side_effect=fail_journey), patch.object(
            case, "private_artifact", side_effect=OSError("diagnostic-protected-canary")
        ), self.assertRaises(AssertionError) as stopped:
            case.test_launcher_composition_readiness_and_golden_persistence()
        failure = stopped.exception
        self.assertIs(failure.__context__, primary)
        self.assertTrue(failure.__suppress_context__)
        self.assertEqual(str(failure), (
            "Issue 68 stopped at golden_transaction; "
            "preserve the owned database and local checkpoint."
        ))
        self.assertEqual(failure.__notes__, [
            "Protected diagnostic storage is unavailable; "
            "the original failure remains in local exception context."
        ])
        public_report = "".join(traceback.format_exception(failure))
        for canary in (
            "primary-protected-canary", "diagnostic-protected-canary", "protected-output-canary",
        ):
            self.assertNotIn(canary, public_report)

    def test_successful_diagnostic_retains_private_detail_and_bounded_report(self):
        case, primary, fail_journey = self.stopped_case()
        with patch.object(case, "journey", side_effect=fail_journey), patch.object(
            case, "private_artifact"
        ) as record, self.assertRaises(AssertionError) as stopped:
            case.test_launcher_composition_readiness_and_golden_persistence()
        self.assertIs(stopped.exception.__context__, primary)
        record.assert_called_once()
        name, payload = record.call_args.args
        self.assertEqual(name, "failure.txt")
        self.assertIn(b"primary-protected-canary", payload)
        self.assertEqual(getattr(stopped.exception, "__notes__", []), [])
        self.assertNotIn(
            "primary-protected-canary", "".join(traceback.format_exception(stopped.exception))
        )


if __name__ == "__main__":
    unittest.main()
