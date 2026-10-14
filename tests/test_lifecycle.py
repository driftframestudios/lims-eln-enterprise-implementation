from __future__ import annotations

import unittest
from dataclasses import replace
import json

from lims_eln_implementation.idempotency import (
    ContentCollision,
    IdempotencyInProgress,
    IdempotencyLedger,
)
from lims_eln_implementation.lifecycle import LifecycleService
from lims_eln_implementation.model import (
    DomainError,
    DomainEvent,
    RevisionConflict,
    SpecimenState,
    SpecimenAggregate,
    TransitionRejected,
    canonical_json,
)
from lims_eln_implementation.store import InMemoryAtomicExecutor, InMemorySpecimenRepository
from lims_eln_implementation.workbench.service import SpecimenView
from lims_eln_implementation.workbench.postgres import _aggregate_document, _json

from helpers import command


class LifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemorySpecimenRepository()
        self.service = LifecycleService(self.repository)

    def test_registration_is_attributable_and_versioned(self) -> None:
        aggregate = self.service.register(
            command("cmd-001", "register", 0, payload={"type": "synthetic_plasma"})
        )
        self.assertEqual(aggregate.state, SpecimenState.REGISTERED)
        self.assertEqual(aggregate.version, 1)
        self.assertEqual(aggregate.events[0].actor_id, "SYN-ACTOR-01")
        self.assertEqual(aggregate.events[0].aggregate_version, 1)

    def test_exact_registration_replay_returns_recorded_outcome(self) -> None:
        original = command("cmd-001", "register", 0)
        first = self.service.register(original)
        second = self.service.register(original)
        self.assertIs(first, second)
        self.assertEqual(len(second.events), 1)

    def test_changed_content_on_stable_command_identity_is_a_collision(self) -> None:
        self.service.register(command("cmd-001", "register", 0, payload={"type": "A"}))
        with self.assertRaises(ContentCollision):
            self.service.register(
                command("cmd-001", "register", 0, payload={"type": "B"})
            )

    def test_command_snapshots_nested_payload_before_authorization(self) -> None:
        source = {"measurements": [{"value": "12.5"}]}
        planned = command("cmd-snapshot", "register", 0, payload=source)
        digest = planned.content_digest
        source["measurements"][0]["value"] = "caller-mutated"
        self.assertEqual(planned.content_digest, digest)
        self.assertEqual(planned.payload["measurements"][0]["value"], "12.5")
        with self.assertRaises(TypeError):
            planned.payload["measurements"][0]["value"] = "later-mutation"

    def test_command_requires_string_keyed_finite_json(self) -> None:
        with self.assertRaisesRegex(DomainError, "string-keyed"):
            command("cmd-key-shape", "register", 0, payload={1: "value"})

    def test_direct_domain_values_own_nested_json_and_event_membership(self) -> None:
        source = {"values": [{"value": "12.5", "missing": None}], "pending": False}
        planned = command("cmd-direct", "register", 0)
        event = DomainEvent(
            "event-direct", planned.tenant_id, planned.specimen_id, 1,
            "specimen.registered", planned.actor_id, planned.command_id,
            planned.content_digest, planned.occurred_at, source,
        )
        events = [event]
        aggregate = SpecimenAggregate(
            planned.tenant_id, planned.specimen_id, SpecimenState.REGISTERED,
            1, source, events,
        )
        source["values"][0]["value"] = "caller-edited"
        events.clear()
        expected = {"values": [{"value": "12.5", "missing": None}], "pending": False}
        self.assertEqual(json.loads(canonical_json(event.payload)), expected)
        self.assertEqual(json.loads(canonical_json(aggregate.attributes)), expected)
        self.assertEqual(aggregate.events, (event,))
        for owned in (event.payload, aggregate.attributes):
            with self.assertRaises(TypeError):
                owned["pending"] = True
            with self.assertRaises(TypeError):
                owned["values"][0]["value"] = "later-edit"
            with self.assertRaises(TypeError):
                owned["values"][0] = {}

    def test_returned_values_preserve_replay_and_populated_rollback(self) -> None:
        original = command("cmd-owned", "register", 0, payload={"nested": [{"value": 0}]})
        digest = original.content_digest
        accepted = self.service.register(original)
        before = canonical_json(accepted.attributes)
        for owned in (accepted.attributes, accepted.events[0].payload):
            with self.assertRaises(TypeError):
                owned["nested"][0]["value"] = 2
        replay = self.service.register(original)
        self.assertIs(replay, accepted)
        self.assertEqual(original.content_digest, digest)
        self.assertEqual(replay.events[0].command_digest, digest)

        def failed_operation():
            candidate = replace(accepted, version=2, attributes={"nested": [{"value": 1}]})
            self.repository.save(candidate, previous_version=1)
            raise RuntimeError("synthetic failure after candidate save")

        with self.assertRaisesRegex(RuntimeError, "after candidate save"):
            InMemoryAtomicExecutor((self.repository,)).execute(failed_operation)
        restored = self.repository.get(original.tenant_id, original.specimen_id)
        self.assertIs(restored, accepted)
        self.assertEqual(canonical_json(restored.attributes), before)
        self.assertEqual(restored.version, 1)
        self.assertEqual(len(restored.events), 1)

    def test_nested_domain_values_project_to_detached_json_documents(self) -> None:
        aggregate = self.service.register(
            command("cmd-document", "register", 0, payload={"nested": [{"value": 0}]})
        )
        view = SpecimenView(aggregate, None, (), None)
        document = view.to_document()
        self.assertEqual(json.loads(json.dumps(document)), document)
        document["attributes"]["nested"][0]["value"] = 1
        document["events"][0]["payload"]["nested"][0]["value"] = 2
        self.assertEqual(view.to_document()["attributes"]["nested"][0]["value"], 0)
        self.assertEqual(view.to_document()["events"][0]["payload"]["nested"][0]["value"], 0)
        stored = json.loads(_json(_aggregate_document(aggregate)))
        self.assertEqual(stored["attributes"], {"nested": [{"value": 0}]})
        self.assertEqual(json.loads(_json(aggregate.events[0].payload)), stored["attributes"])

    def test_matching_in_progress_command_fails_closed(self) -> None:
        ledger: IdempotencyLedger = IdempotencyLedger()
        pending = command("cmd-pending", "register", 0)
        ledger.reserve(pending.tenant_id, pending.command_id, pending.content_digest)
        service = LifecycleService(InMemorySpecimenRepository(), ledger)

        with self.assertRaisesRegex(IdempotencyInProgress, "reconcile"):
            service.register(pending)

    def test_failed_idempotency_commit_rolls_back_specimen(self) -> None:
        class FailingCommitLedger(IdempotencyLedger):
            def commit(self, tenant_id, key, outcome):
                raise RuntimeError("synthetic ledger failure")

        repository = InMemorySpecimenRepository()
        service = LifecycleService(repository, FailingCommitLedger())

        with self.assertRaisesRegex(RuntimeError, "synthetic ledger failure"):
            service.register(command("cmd-atomic", "register", 0))

        self.assertIsNone(repository.get("SYN-TENANT-A", "SYN-SPECIMEN-0001"))

    def test_full_review_and_correction_cycle(self) -> None:
        aggregate = self.service.register(command("cmd-001", "register", 0))
        for command_id, action, reason in (
            ("cmd-002", "accession", None),
            ("cmd-003", "start_processing", None),
            ("cmd-004", "submit_review", None),
            ("cmd-005", "release", "scientific_review_complete"),
            ("cmd-006", "correct", "amended_interpretation"),
            ("cmd-007", "submit_review", None),
            ("cmd-008", "release", "scientific_review_complete"),
        ):
            aggregate = self.service.transition(
                command(command_id, action, aggregate.version, reason=reason)
            )
        self.assertEqual(aggregate.state, SpecimenState.RELEASED)
        self.assertEqual(aggregate.version, 8)
        self.assertEqual(len(aggregate.events), 8)

    def test_stale_revision_prompts_reload(self) -> None:
        aggregate = self.service.register(command("cmd-001", "register", 0))
        aggregate = self.service.transition(
            command("cmd-002", "accession", aggregate.version)
        )
        with self.assertRaisesRegex(RevisionConflict, "reload"):
            self.service.transition(command("cmd-stale", "start_processing", 1))

    def test_unsupported_transition_explains_next_action(self) -> None:
        aggregate = self.service.register(command("cmd-001", "register", 0))
        with self.assertRaisesRegex(TransitionRejected, "select its next supported action"):
            self.service.transition(command("cmd-002", "release", aggregate.version))

    def test_void_requires_accountable_reason(self) -> None:
        aggregate = self.service.register(command("cmd-001", "register", 0))
        with self.assertRaisesRegex(TransitionRejected, "reason code"):
            self.service.transition(command("cmd-002", "void", aggregate.version))
        voided = self.service.transition(
            command("cmd-003", "void", aggregate.version, reason="sample_compromised")
        )
        self.assertEqual(voided.state, SpecimenState.VOIDED)


if __name__ == "__main__":
    unittest.main()
