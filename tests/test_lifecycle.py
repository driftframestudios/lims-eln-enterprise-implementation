from __future__ import annotations

import unittest

from lims_eln_implementation.idempotency import (
    ContentCollision,
    IdempotencyInProgress,
    IdempotencyLedger,
)
from lims_eln_implementation.lifecycle import LifecycleService
from lims_eln_implementation.model import (
    DomainError,
    RevisionConflict,
    SpecimenState,
    TransitionRejected,
)
from lims_eln_implementation.store import InMemorySpecimenRepository

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
