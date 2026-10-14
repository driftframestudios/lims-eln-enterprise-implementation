"""Independent Enterprise expectations for Program's lifecycle receiving contract.

Fixtures and counterexamples follow the field-owner and transition guide. The
Program implementation supplies admission; expected outcomes are authored here.
"""

from copy import deepcopy
from hashlib import sha256
from importlib import metadata
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
import tempfile
from unittest.mock import patch

from scripts import receive_database_lifecycle as receiver

ROOT = Path(__file__).resolve().parents[1]


def fixture(name):
    return json.loads((ROOT / f"fixtures/synthetic/database-lifecycle-{name}.json").read_text())


def encoded(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def event(record, action, before, after, outcome="succeeded"):
    """Author an event from Enterprise's declared owner and synthetic observation."""
    disposition = record["requested_profile"]["disposition"]
    owner = record["resource"]["creation_owner_ref" if action == "create" else "owner_ref"]
    compatibility = {"state": "not_observed", "engine_major": None,
                     "migration_ref": None, "observation_ref": None}
    if action in {"migrate", "restore"} and outcome == "succeeded":
        compatibility = {"state": "compatible", "engine_major": 17,
                         "migration_ref": "ref:enterprise-flyway-v-seven",
                         "observation_ref": "ref:enterprise-compatibility-proof"}
    return {
        "operation_ref": f"ref:enterprise-independent-event-{len(record['operations']) + 1}",
        "action": action, "from_state": before, "to_state": after, "outcome": outcome,
        "authority": {
            "owner_ref": owner,
            "actor_ref": owner if disposition == "external" and action not in {"inspect", "stop"}
            else record["invocation"]["owner_ref"],
            "decision_ref": "ref:enterprise-explicit-event-decision",
            "basis": "invocation_owned" if disposition == "disposable" else "explicit_owner_decision",
            "destructive_authorized": action in {"restore", "cleanup"},
        },
        "compatibility": compatibility,
        "evidence_ref": None if outcome == "requested" else "ref:enterprise-recorded-result",
        "failure_code": f"{action}_failed" if outcome == "failed" else
        "resource_unresolved" if outcome == "unresolved" else None,
    }


def append(record, action, before, after, outcome="succeeded"):
    record["operations"].append(event(record, action, before, after, outcome))
    record["resource"]["state"] = after
    record["unresolved_resource_refs"] = [record["resource"]["resource_ref"]] if after == "unresolved" else []


def capability(adapter="postgresql", compatible=False):
    return {
        "contract_id": "urn:driftframe:lims-eln:workbench-capabilities:1.0.0",
        "runtime": {"state_adapter": adapter,
                    "state_lifetime": "database" if adapter == "postgresql" else "process",
                    "access_scope": "local_reference"},
        "shared_contracts": {"expected_package_version": "0.6.1", "expected_contract_version": "1.0.0",
                             "version_compatible": compatible},
        "operations": {
            "summary": {"method": "GET", "path": "/api/workbench/summary", "tenant_context": "header_and_query"},
            "specimen": {"method": "GET", "path": "/api/workbench/specimens/{specimen_id}", "tenant_context": "header_and_query"},
            "observation": {"method": "GET", "path": "/api/workbench/observations/{run_id}", "tenant_context": "header_and_query"},
            "golden_specimen": {"method": "POST", "path": "/api/workbench/golden-runs", "tenant_context": "header_and_body"},
            "instrument_recovery": {"method": "POST", "path": "/api/workbench/instrument-recovery-runs", "tenant_context": "header_and_body"},
        },
        "administrative_interface": "python_library", "readiness_path": "/health/ready",
    }


def bind_composition(record, payload):
    record["composition"] = {"state": "observed", "capability_ref": "ref:enterprise-capability-observation",
                             "capability_digest": "sha256:" + sha256(payload).hexdigest()}


def lifecycle_profile_selected():
    try:
        installed = metadata.version("lims-eln-program-specification")
    except metadata.PackageNotFoundError:
        return False
    # The application retains its accepted 0.6.1 profile. Every other installed
    # version enters the receiving checks so an unexpected version stays visible.
    return installed != "0.6.1"


class LifecycleReceiverBindingTests(unittest.TestCase):
    def test_local_schema_and_source_binding_match_the_selected_contract(self):
        receiver.verify_schema_binding()
        self.assertEqual(
            sha256((ROOT / "contracts/database-lifecycle-profile.v1.schema.json").read_bytes()).hexdigest(),
            "baf035a23aee30c09f410ec157268a42559a4dde824772ead080ece0f56478ca",
        )
        requirement = "lims-eln-program-specification[lifecycle] @ git+" + receiver.PROGRAM_URL + "@" + receiver.PROGRAM_COMMIT
        self.assertIn(requirement, (ROOT / "requirements-lifecycle.txt").read_text().splitlines())

    def test_known_application_profile_has_an_explicit_receiving_version_finding(self):
        distribution = SimpleNamespace(version="0.6.1")
        with patch.object(receiver.metadata, "distribution", return_value=distribution):
            with self.assertRaises(receiver.LifecycleReceiptError) as finding:
                receiver.receive_profile(encoded(fixture("external")))
        self.assertEqual(finding.exception.code, "dependency_version")

    def test_missing_distribution_is_an_explicit_receiving_finding(self):
        with patch.object(receiver.metadata, "distribution", side_effect=metadata.PackageNotFoundError):
            with self.assertRaises(receiver.LifecycleReceiptError) as finding:
                receiver.receive_profile(encoded(fixture("external")))
        self.assertEqual(finding.exception.code, "dependency_unavailable")

    def test_unpinned_or_changed_installations_fail_before_semantic_admission(self):
        expected = {"url": receiver.PROGRAM_URL, "vcs_info": {
            "vcs": "git", "requested_revision": receiver.PROGRAM_COMMIT, "commit_id": receiver.PROGRAM_COMMIT}}
        for provenance in ({}, [], expected | {"url": "https://example.invalid/unselected.git"},
                           expected | {"dir_info": {"editable": True}},
                           expected | {"vcs_info": expected["vcs_info"] | {"commit_id": "2" * 40}}):
            with self.subTest(provenance=provenance):
                distribution = SimpleNamespace(version=receiver.PROGRAM_VERSION,
                                               read_text=lambda name: "Wheel-Version: 1.0" if name == "WHEEL" else json.dumps(provenance))
                with patch.object(receiver.metadata, "distribution", return_value=distribution):
                    with self.assertRaises(receiver.LifecycleReceiptError) as finding:
                        receiver.receive_profile(encoded(fixture("external")))
                self.assertEqual(finding.exception.code, "dependency_provenance")

    def test_wheel_metadata_is_required_for_receiving_provenance(self):
        distribution = SimpleNamespace(version=receiver.PROGRAM_VERSION, read_text=lambda name: None)
        with patch.object(receiver.metadata, "distribution", return_value=distribution):
            with self.assertRaises(receiver.LifecycleReceiptError) as finding:
                receiver.receive_profile(encoded(fixture("external")))
        self.assertEqual(finding.exception.code, "dependency_provenance")

    def test_shadowed_package_or_api_cannot_borrow_distribution_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            installed = Path(directory) / "installed/lims_eln_contracts"
            installed.mkdir(parents=True)
            package_path = installed / "__init__.py"; package_path.write_text("")
            api_path = installed / "database_lifecycle.py"; api_path.write_text("")
            shadow = Path(directory) / "shadow.py"; shadow.write_text("")
            provenance = {"url": receiver.PROGRAM_URL, "vcs_info": {
                "vcs": "git", "requested_revision": receiver.PROGRAM_COMMIT, "commit_id": receiver.PROGRAM_COMMIT}}
            distribution = SimpleNamespace(
                version=receiver.PROGRAM_VERSION,
                locate_file=lambda path: installed.parent / path,
                read_text=lambda name: "Wheel-Version: 1.0" if name == "WHEEL" else json.dumps(provenance),
            )
            for target in ("package_spec", "package_module", "api_spec", "api_module"):
                with self.subTest(target=target):
                    def selected_spec(name):
                        selected = package_path if name == "lims_eln_contracts" else api_path
                        if target == ("package_spec" if name == "lims_eln_contracts" else "api_spec"):
                            selected = shadow
                        return SimpleNamespace(origin=str(selected))
                    def selected_module(name):
                        selected = package_path if name == "lims_eln_contracts" else api_path
                        if target == ("package_module" if name == "lims_eln_contracts" else "api_module"):
                            selected = shadow
                        return SimpleNamespace(__file__=str(selected), __version__=receiver.PROGRAM_VERSION)
                    with patch.object(receiver.metadata, "distribution", return_value=distribution), \
                            patch.object(receiver, "find_spec", side_effect=selected_spec), \
                            patch.object(receiver, "import_module", side_effect=selected_module):
                        with self.assertRaises(receiver.LifecycleReceiptError) as finding:
                            receiver.receive_profile(encoded(fixture("external")))
                    self.assertEqual(finding.exception.code, "dependency_provenance")

    def test_input_failure_emits_only_a_fixed_code(self):
        with patch.object(receiver, "_read_input", side_effect=OSError("SYN-PRIVATE-INPUT")), \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(receiver.main(["SYN-LOCAL-INPUT"]), 1)
        self.assertEqual(output.getvalue(), "input_unavailable\n")


@unittest.skipUnless(lifecycle_profile_selected(), "dedicated requirements-lifecycle.txt profile enables semantic receiving proof")
class LifecycleReceiverSemanticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        receiver._verified_api()

    def admit(self, record, capability_payload=None):
        return receiver.receive_profile(encoded(record), capability_payload=capability_payload)

    def reject(self, record, code, capability_payload=None):
        with self.assertRaises(receiver.LifecycleReceiptError) as finding:
            self.admit(record, capability_payload)
        self.assertEqual(finding.exception.code, code)
        self.assertEqual(str(finding.exception), code)

    def test_three_profiles_keep_their_independently_expected_state_and_counts(self):
        for name, state, executed, requested in (
            ("disposable", "removed", 3, 0), ("retained", "retained", 2, 1), ("external", "present", 2, 0),
        ):
            with self.subTest(profile=name):
                record = fixture(name)
                result = self.admit(record)
                self.assertEqual((result.resource_state, result.executed_operations, result.requested_operations),
                                 (state, executed, requested))
                self.assertEqual(result.unresolved_resource_refs, ())
                self.assertEqual(json.loads(result.canonical_bytes), record)

    def test_failed_cleanup_and_stopping_preserve_the_unresolved_resource(self):
        result = self.admit(fixture("cleanup-failed"))
        self.assertEqual(result.resource_state, "unresolved")
        self.assertEqual(result.unresolved_resource_refs, ("ref:enterprise-synthetic-database",))
        self.assertEqual(result.executed_operations, 3)
        record = fixture("cleanup-failed")
        record["unresolved_resource_refs"] = []
        self.reject(record, "unresolved_resources")

    def test_uncertain_creation_stays_distinct_from_requested_inspection(self):
        result = self.admit(fixture("unresolved"))
        self.assertEqual((result.resource_state, result.executed_operations, result.requested_operations),
                         ("unresolved", 1, 1))
        record = fixture("unresolved")
        append(record, "cleanup", "unresolved", "removed")
        self.reject(record, "unowned_cleanup")

    def test_source_schema_and_version_have_specific_findings(self):
        for field, value, code in (
            ("source", {"source_ref": "ref:program-database-lifecycle", "revision": "3" * 40}, "stale_source"),
            ("schema_ref", "urn:driftframe:lims-eln:database-lifecycle-profile:2.0.0", "stale_schema"),
            ("schema_version", "2.0.0", "unsupported_version"),
        ):
            with self.subTest(field=field):
                record = fixture("external"); record[field] = value
                self.reject(record, code)

    def test_wrong_resource_owner_cannot_authorize_an_event(self):
        record = fixture("retained")
        record["operations"][0]["authority"]["owner_ref"] = "ref:unrelated-owner"
        self.reject(record, "wrong_owner")

    def test_disposable_profile_requires_its_current_invocation_ownership(self):
        record = fixture("disposable")
        record["resource"]["created_by_invocation_ref"] = "ref:earlier-invocation"
        self.reject(record, "ownership_profile")

    def test_external_cleanup_requires_its_owner_actor(self):
        record = fixture("external")
        append(record, "cleanup", "present", "removed")
        self.assertEqual(self.admit(record).resource_state, "removed")
        record["operations"][-1]["authority"]["actor_ref"] = record["invocation"]["owner_ref"]
        self.reject(record, "external_cleanup_forbidden")

    def test_external_migration_stays_with_its_owner(self):
        record = fixture("external")
        append(record, "migrate", "present", "present")
        self.admit(record)
        record["operations"][-1]["authority"]["actor_ref"] = record["invocation"]["owner_ref"]
        self.reject(record, "external_owner_action_required")

    def test_retained_restore_requires_explicit_owner_decision_and_destructive_authority(self):
        record = fixture("retained")
        record["operations"][0]["authority"]["basis"] = "invocation_owned"
        self.reject(record, "owner_decision_required")
        record = fixture("retained")
        record["operations"][0]["authority"]["destructive_authorized"] = False
        self.reject(record, "destructive_authority_required")

    def test_profile_cleanup_policy_and_permitted_actions_are_material(self):
        record = fixture("external")
        record["requested_profile"]["cleanup_policy"] = "current_invocation_owned"
        self.reject(record, "ownership_profile")
        record = fixture("disposable")
        record["requested_profile"]["permitted_actions"].remove("migrate")
        self.reject(record, "action_not_permitted")

    def test_successful_migration_requires_matching_event_specific_compatibility(self):
        record = fixture("disposable")
        record["operations"][1]["compatibility"]["engine_major"] = 18
        self.reject(record, "compatibility_mismatch")
        record = fixture("disposable")
        record["operations"][1]["compatibility"] = {
            "state": "not_observed", "engine_major": None, "migration_ref": None, "observation_ref": None}
        self.reject(record, "compatibility_required")

    def test_event_identity_order_and_outcome_evidence_remain_consistent(self):
        record = fixture("disposable")
        record["operations"][1]["operation_ref"] = record["operations"][0]["operation_ref"]
        self.reject(record, "duplicate_operation")
        record = fixture("disposable")
        record["operations"][1]["from_state"] = "retained"
        self.reject(record, "invalid_transition")
        record = fixture("cleanup-failed")
        record["operations"][1]["failure_code"] = "create_failed"
        self.reject(record, "operation_evidence")

    def test_confirmed_absence_removes_old_creation_authority(self):
        record = fixture("cleanup-failed")
        append(record, "inspect", "unresolved", "absent")
        append(record, "create", "absent", "unresolved", "unresolved")
        append(record, "inspect", "unresolved", "present")
        append(record, "cleanup", "present", "removed")
        self.reject(record, "unowned_cleanup")

    def test_new_successful_creation_earns_new_cleanup_authority(self):
        record = fixture("cleanup-failed")
        append(record, "inspect", "unresolved", "absent")
        append(record, "create", "absent", "present")
        append(record, "cleanup", "present", "removed")
        result = self.admit(record)
        self.assertEqual(result.resource_state, "removed")
        self.assertEqual(result.executed_operations, 6)
        self.assertEqual(len(json.loads(result.canonical_bytes)["operations"]), 6)

    def test_new_uncertain_instance_cannot_reuse_an_old_cleanup_attempt(self):
        record = fixture("cleanup-failed")
        append(record, "inspect", "unresolved", "absent")
        append(record, "create", "absent", "unresolved", "unresolved")
        append(record, "inspect", "unresolved", "removed")
        self.reject(record, "invalid_transition")

    def test_removed_resource_can_be_created_and_cleaned_as_a_new_instance(self):
        record = fixture("disposable")
        append(record, "create", "removed", "present")
        append(record, "cleanup", "present", "removed")
        result = self.admit(record)
        self.assertEqual((result.resource_state, result.executed_operations), ("removed", 5))
        self.assertEqual(len(json.loads(result.canonical_bytes)["operations"]), 5)

    def test_failed_or_uncertain_recreation_from_removed_preserves_only_its_own_authority(self):
        for outcome in ("failed", "unresolved"):
            with self.subTest(outcome=outcome):
                record = fixture("disposable")
                append(record, "create", "removed", "unresolved", outcome)
                result = self.admit(record)
                self.assertEqual((result.resource_state, result.executed_operations), ("unresolved", 4))
                append(record, "cleanup", "unresolved", "removed")
                self.reject(record, "unowned_cleanup")

    def test_postgresql_composition_preserves_false_package_compatibility_and_readiness_separation(self):
        record = fixture("unresolved")
        payload = encoded(capability(compatible=False)); bind_composition(record, payload)
        record["readiness"] = {"state": "ready", "observation_ref": "ref:enterprise-readiness-snapshot"}
        result = self.admit(record, payload)
        self.assertEqual(result.resource_state, "unresolved")
        self.assertEqual(result.requested_operations, 1)

    def test_process_local_capability_conflicts_with_database_profile(self):
        record = fixture("external")
        payload = encoded(capability("process_local")); bind_composition(record, payload)
        self.reject(record, "composition_mismatch", payload)

    def test_capability_reference_requires_exact_bytes_and_the_v1_contract(self):
        record = fixture("external")
        payload = encoded(capability()); bind_composition(record, payload)
        self.reject(record, "composition_unresolved")
        self.reject(record, "composition_digest", payload + b" ")
        changed = capability(); changed["runtime"]["access_scope"] = "remote"
        payload = encoded(changed); bind_composition(record, payload)
        self.reject(record, "composition_contract", payload)
        self.reject(fixture("external"), "composition_mismatch", encoded(capability()))

    def test_bounded_strict_input_preserves_typed_findings(self):
        for payload, code in (
            (b" " * (131072 + 1), "input_bytes"), (b"\xff", "utf8"),
            (b'{"same":1,"same":2}', "json_duplicate_key"),
            (b'{"number":NaN}', "json_number"), (b'[]', "contract_shape"),
        ):
            with self.subTest(code=code):
                with self.assertRaises(receiver.LifecycleReceiptError) as finding:
                    receiver.receive_profile(payload)
                self.assertEqual(finding.exception.code, code)

    def test_current_capability_producer_retains_its_v1_meaning(self):
        from lims_eln_implementation.workbench.capabilities import describe_workbench
        record = fixture("external")
        payload = encoded(describe_workbench("postgresql", package_compatible=False))
        bind_composition(record, payload)
        self.assertEqual(self.admit(record, payload).resource_state, "present")
