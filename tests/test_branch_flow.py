"""Regression tests for human and automated branch coordinates."""

from __future__ import annotations

from copy import deepcopy
from contextlib import redirect_stdout
import importlib.util
from io import StringIO
import json
from pathlib import Path
import re
import sys
import unittest

from scripts.check_automation_contract import (
    AutomationContractError,
    EXPECTED_DEPENDABOT_DIRECTORIES,
    validate_automation_documents,
)


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "scripts" / "check_branch_flow.py"
SPEC = importlib.util.spec_from_file_location("check_branch_flow", TOOL_PATH)
assert SPEC and SPEC.loader
check_branch_flow = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = check_branch_flow
SPEC.loader.exec_module(check_branch_flow)


def workflow_trigger_keys(workflow: str) -> set[str]:
    """Read exact top-level event keys from the workflow."""
    lines = workflow.splitlines()
    start = lines.index("on:") + 1
    triggers: set[str] = set()
    for line in lines[start:]:
        if line and not line.startswith(" "):
            break
        match = re.fullmatch(r"""  ["']?([A-Za-z0-9_-]+)["']?:.*""", line)
        if match:
            triggers.add(match.group(1))
    return triggers


def runner_job_blocks(workflow: str) -> dict[str, str]:
    """Return each job block that allocates a runner."""
    lines = workflow.splitlines()
    start = lines.index("jobs:") + 1
    job_starts = [
        (index, match.group(1))
        for index in range(start, len(lines))
        if (match := re.fullmatch(r"  ([A-Za-z0-9_-]+):", lines[index]))
    ]
    blocks: dict[str, str] = {}
    for position, (index, name) in enumerate(job_starts):
        end = (
            job_starts[position + 1][0]
            if position + 1 < len(job_starts)
            else len(lines)
        )
        block = "\n".join(lines[index:end])
        if re.search(r"(?m)^    runs-on:", block):
            blocks[name] = block
    return blocks


class BranchFlowTests(unittest.TestCase):
    def automation_documents(self) -> tuple[str, str, dict[str, object]]:
        workflow = (
            ROOT / ".github" / "workflows" / "pull-request.yml"
        ).read_text(encoding="utf-8")
        dependabot = (ROOT / ".github" / "dependabot.yml").read_text(
            encoding="utf-8"
        )
        release = json.loads(
            (ROOT / "release" / "repository-role.json").read_text(encoding="utf-8")
        )
        return workflow, dependabot, release["automation_controls"]

    def invoke(self, *, base: str, head: str, author: str) -> tuple[int, str]:
        output = StringIO()
        with redirect_stdout(output):
            result = check_branch_flow.main(
                ["--base", base, "--head", head, "--author", author]
            )
        return result, output.getvalue()

    def test_non_pull_request_event_skips_with_empty_coordinates(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            result = check_branch_flow.main([])
        self.assertEqual(0, result)
        self.assertIn("non-pull-request event", output.getvalue())

    def test_partial_pull_request_coordinates_fail_closed(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            result = check_branch_flow.main(
                ["--base", "main", "--head", "release/0.3.0"]
            )
        self.assertEqual(2, result)
        self.assertIn("requires base, head, and pull-request author", output.getvalue())

    def test_dependabot_branch_requires_complete_bot_identity(self) -> None:
        result, output = self.invoke(
            base="develop",
            head="dependabot/github_actions/actions/setup-python-7.0.0",
            author="dependabot[bot]",
        )
        self.assertEqual(0, result)
        self.assertIn("Dependabot branch", output)

        result, output = self.invoke(
            base="develop",
            head="dependabot/github_actions/actions/setup-python-7.0.0",
            author="repository-contributor",
        )
        self.assertEqual(1, result)
        self.assertIn("requires pull-request author", output)

    def test_renovate_branch_requires_complete_bot_identity(self) -> None:
        result, output = self.invoke(
            base="develop",
            head="renovate/github-actions-minor",
            author="renovate[bot]",
        )
        self.assertEqual(0, result)
        self.assertIn("Renovate branch", output)
        self.assertEqual(
            1,
            self.invoke(
                base="develop",
                head="renovate/github-actions-minor",
                author="self-hosted-renovate[bot]",
            )[0],
        )

    def test_automation_branch_uses_governed_target(self) -> None:
        result, output = self.invoke(
            base="release/0.3.0",
            head="dependabot/github_actions/actions/checkout-5.0.0",
            author="dependabot[bot]",
        )
        self.assertEqual(1, result)
        self.assertIn("should target one of develop, main", output)

    def test_automation_grammar_rejects_malformed_path(self) -> None:
        result, output = self.invoke(
            base="main",
            head="dependabot/github_actions/actions/../release",
            author="dependabot[bot]",
        )
        self.assertEqual(1, result)
        self.assertIn("outside the branch naming contract", output)

    def test_dependabot_schedule_and_grammar_share_ecosystems(self) -> None:
        self.assertFalse((ROOT / ".github" / "dependabot.manual.yml").exists())
        workflow, config, declared = self.automation_documents()
        controls = validate_automation_documents(
            workflow,
            config,
            declared_controls=declared,
        )
        configured = {
            ecosystem.replace("-", "_")
            for ecosystem in EXPECTED_DEPENDABOT_DIRECTORIES
        }
        self.assertEqual(check_branch_flow.DEPENDABOT_BRANCH_ECOSYSTEMS, configured)
        self.assertEqual("develop", controls["dependabot_target"])
        self.assertEqual("monthly", controls["dependabot_interval"])
        self.assertEqual(2, controls["dependabot_open_pull_requests_per_ecosystem"])
        self.assertEqual(
            ["minor", "patch"],
            controls["dependabot_grouped_update_types"],
        )
        for ecosystem in configured:
            head = f"dependabot/{ecosystem}/example-1.2.3"
            with self.subTest(ecosystem=ecosystem):
                self.assertEqual(
                    0,
                    self.invoke(
                        base="develop",
                        head=head,
                        author="dependabot[bot]",
                    )[0],
                )
                self.assertEqual(
                    0,
                    self.invoke(
                        base="main",
                        head=head,
                        author="dependabot[bot]",
                    )[0],
                )

    def test_experiment_branch_can_return_to_develop(self) -> None:
        result, output = self.invoke(
            base="develop",
            head="experiment/vendor-idempotency",
            author="repository-contributor",
        )
        self.assertEqual(0, result)
        self.assertIn("passed", output)

    def test_feature_branch_routes_through_develop(self) -> None:
        result, output = self.invoke(
            base="main",
            head="feature/bounded-caller",
            author="repository-contributor",
        )
        self.assertEqual(1, result)
        self.assertIn("release/, hotfix/", output)

    def test_full_proof_workflow_is_manual_confirmed_and_read_only(self) -> None:
        workflow_directory = ROOT / ".github" / "workflows"
        workflow_paths = sorted(
            [*workflow_directory.glob("*.yml"), *workflow_directory.glob("*.yaml")]
        )
        self.assertEqual(
            ["ci.yml", "pull-request.yml"],
            [path.name for path in workflow_paths],
        )
        self.assertFalse(
            (ROOT / ".github" / "workflows" / "branch-policy.yml").exists()
        )
        workflow = (workflow_directory / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertEqual({"workflow_dispatch"}, workflow_trigger_keys(workflow))
        self.assertIn("type: boolean", workflow)
        self.assertIn("persist-credentials: false", workflow)
        jobs = runner_job_blocks(workflow)
        self.assertEqual(
            {
                "validate",
                "postgres-invariants",
                "postgres-upgrade",
                "implementation-validation",
            },
            set(jobs),
        )
        for name, block in jobs.items():
            with self.subTest(job=name):
                gate = re.search(r"(?m)^    if:\s*(.+)$", block)
                self.assertIsNotNone(gate)
                assert gate is not None
                self.assertIn("vars.ENABLE_GITHUB_ACTIONS == 'true'", gate.group(1))
                self.assertIn("inputs.confirm_run", gate.group(1))

    def test_pull_request_workflow_is_bounded_and_read_only(self) -> None:
        workflow, dependabot, declared = self.automation_documents()
        controls = validate_automation_documents(
            workflow,
            dependabot,
            declared_controls=declared,
        )
        self.assertEqual(["develop", "main"], controls["pull_request_targets"])
        self.assertEqual({"contents": "read"}, controls["pull_request_permissions"])
        self.assertTrue(controls["pull_request_concurrency_cancellation"])
        self.assertEqual(10, controls["pull_request_timeout_minutes"])

    def test_pull_request_contract_rejects_material_mutations(self) -> None:
        workflow, dependabot, declared = self.automation_documents()
        checkout_sha = "3d3c42e5aac5ba805825da76410c181273ba90b1"
        setup_sha = "5fda3b95a4ea91299a34e894583c3862153e4b97"
        mutations = {
            "unknown top-level key": workflow + "\nunexpected: true\n",
            "quoted permission key": workflow.replace(
                "permissions:\n",
                '"permissions":\n',
                1,
            ),
            "flow permission mapping": workflow.replace(
                "permissions:\n  contents: read",
                "permissions: {contents: read}",
            ),
            "top-level permission broadening": workflow.replace(
                "permissions:\n  contents: read",
                "permissions:\n  contents: read\n  issues: write",
            ),
            "job-level permission broadening": workflow.replace(
                "    steps:\n",
                "    permissions:\n      contents: write\n    steps:\n",
                1,
            ),
            "validation can fail open": workflow.replace(
                "      - name: Validate repository contracts and behavior\n        run:",
                "      - name: Validate repository contracts and behavior\n"
                "        continue-on-error: true\n        run:",
            ),
            "cancellation comment decoy": workflow.replace(
                "  cancel-in-progress: true",
                "  cancel-in-progress: false\n  # cancel-in-progress: true",
            ),
            "timeout comment decoy": workflow.replace(
                "    timeout-minutes: 10",
                "    timeout-minutes: 11\n    # timeout-minutes: 10",
            ),
            "extra runner job": workflow
            + "\n  extra-validation:\n"
            "    runs-on: ubuntu-24.04\n"
            "    timeout-minutes: 10\n"
            "    steps:\n"
            "      - name: Extra proof\n"
            "        run: python scripts/validate_repository.py\n",
            "extra reusable job": workflow
            + "\n  delegated-proof:\n"
            "    uses: outside/example/.github/workflows/proof.yml@main\n",
            "anonymous action step": workflow.replace(
                "      - name: Select Python",
                "      - uses: outside/example@main\n\n      - name: Select Python",
            ),
            "unpinned action": workflow.replace(
                f"actions/checkout@{checkout_sha}",
                "actions/checkout@main",
            ),
            "unapproved action": workflow.replace(
                f"actions/setup-python@{setup_sha}",
                f"outside/setup-python@{setup_sha}",
            ),
            "wrong full action SHA with comment decoy": workflow.replace(
                f"        uses: actions/checkout@{checkout_sha}",
                "        uses: actions/checkout@0000000000000000000000000000000000000000\n"
                f"        # uses: actions/checkout@{checkout_sha}",
            ),
            "trigger drift": workflow.replace(
                "  pull_request:",
                "  pull_request_target:",
            ),
            "branch drift": workflow.replace(
                "      - develop",
                "      - release",
                1,
            ),
            "secret injection": workflow.replace(
                "    steps:\n",
                "    env:\n      CREDENTIAL: ${{ secrets.CREDENTIAL }}\n    steps:\n",
                1,
            ),
            "bracket-form secret command": workflow.replace(
                "        run: python scripts/validate_repository.py",
                "        run: echo \"${{ secrets['AUTOMATION_TOKEN'] }}\"",
            ),
            "checkout credential persistence": workflow.replace(
                "          persist-credentials: false",
                "          persist-credentials: true",
            ),
        }
        for name, mutated in mutations.items():
            with self.subTest(mutation=name):
                with self.assertRaises(AutomationContractError):
                    validate_automation_documents(
                        mutated,
                        dependabot,
                        declared_controls=declared,
                    )

    def test_dependabot_contract_rejects_material_mutations(self) -> None:
        workflow, dependabot, declared = self.automation_documents()
        mutations = {
            "quoted ecosystem key": dependabot.replace(
                "  - package-ecosystem: github-actions",
                '  - "package-ecosystem": github-actions',
            ),
            "quoted directory key": dependabot.replace(
                "    directory: /",
                '    "directory": /wrong',
                1,
            ),
            "flow schedule": dependabot.replace(
                "    schedule:\n      interval: monthly",
                "    schedule: {interval: daily}",
            ),
            "github-actions directory": dependabot.replace(
                "  - package-ecosystem: github-actions\n    directory: /",
                "  - package-ecosystem: github-actions\n    directory: /wrong",
            ),
            "pip directory": dependabot.replace(
                "  - package-ecosystem: pip\n    directory: /",
                "  - package-ecosystem: pip\n    directory: /wrong",
            ),
            "docker directory": dependabot.replace(
                "  - package-ecosystem: docker\n    directory: /infra",
                "  - package-ecosystem: docker\n    directory: /wrong",
            ),
            "terraform directory": dependabot.replace(
                "  - package-ecosystem: terraform\n    directory: /infra/terraform",
                "  - package-ecosystem: terraform\n    directory: /wrong",
            ),
            "target comment decoy": dependabot.replace(
                "    target-branch: develop",
                "    target-branch: main\n#    target-branch: develop",
            ),
            "cadence comment decoy": dependabot.replace(
                "      interval: monthly",
                "      interval: weekly\n#      interval: monthly",
            ),
            "limit comment decoy": dependabot.replace(
                "    open-pull-requests-limit: 2",
                "    open-pull-requests-limit: 20\n#    open-pull-requests-limit: 2",
            ),
            "pattern comment decoy": dependabot.replace(
                '          - "*"',
                '          - "requests"\n#          - "*"',
            ),
            "update-type comment decoy": dependabot.replace(
                "          - patch",
                "          - major\n#          - patch",
            ),
            "group-name drift": dependabot.replace(
                "      github-actions-minor-patch:",
                "      dependency-updates:",
            ),
            "quoted group-name drift": dependabot.replace(
                "      github-actions-minor-patch:",
                '      "dependency-updates":',
            ),
            "flow extra ecosystem": dependabot
            + "\n  - {package-ecosystem: npm, directory: /wrong, "
            "target-branch: main}\n",
        }
        for name, mutated in mutations.items():
            with self.subTest(mutation=name):
                with self.assertRaises(AutomationContractError):
                    validate_automation_documents(
                        workflow,
                        mutated,
                        declared_controls=declared,
                    )

    def test_declared_automation_controls_are_derived_from_source(self) -> None:
        workflow, dependabot, declared = self.automation_documents()
        drifted = deepcopy(declared)
        drifted["pull_request_timeout_minutes"] = 9
        with self.assertRaisesRegex(
            AutomationContractError,
            "declared automation control 'pull_request_timeout_minutes' differs",
        ):
            validate_automation_documents(
                workflow,
                dependabot,
                declared_controls=drifted,
            )

    def test_release_controls_record_settings_pending_hosted_source(self) -> None:
        release = json.loads(
            (ROOT / "release" / "repository-role.json").read_text(encoding="utf-8")
        )
        controls = release["promotion_controls"]
        self.assertEqual(
            "human_review_and_history_protection_with_hosted_source_ready",
            controls["current_state"],
        )
        self.assertEqual([], controls["hosted_required_check_contexts"])
        self.assertEqual(["main"], controls["protected_branches"])
        self.assertEqual(
            ["merge", "squash", "rebase"], controls["allowed_merge_methods"]
        )
        self.assertEqual(1, controls["human_review"]["required_approvals"])
        self.assertTrue(controls["human_review"]["code_owner_review"])
        self.assertTrue(
            controls["human_review"]["dismiss_stale_reviews_on_push"]
        )
        self.assertTrue(
            controls["human_review"]["extra_approval_for_unattributed_changes"]
        )
        self.assertTrue(controls["human_review"]["last_push_approval"])
        self.assertTrue(controls["human_review"]["review_thread_resolution"])
        self.assertTrue(controls["history_protection"]["branch_deletion_guard"])
        self.assertTrue(controls["history_protection"]["non_fast_forward_guard"])
        self.assertEqual(
            "source_ready_settings_pending",
            controls["hosted_check_activation"]["state"],
        )
        automation = release["automation_controls"]
        self.assertEqual(["develop", "main"], automation["pull_request_targets"])
        self.assertEqual("ubuntu-24.04", automation["pull_request_runner"])
        self.assertEqual("3.12", automation["pull_request_python"])
        self.assertEqual(10, automation["pull_request_timeout_minutes"])
        self.assertEqual({"contents": "read"}, automation["pull_request_permissions"])
        self.assertTrue(automation["pull_request_concurrency_cancellation"])
        self.assertEqual("develop", automation["dependabot_target"])
        self.assertEqual(
            {"minimum": 100, "maximum": 300},
            automation["monthly_budget_minutes"],
        )

    def test_codeowners_cover_branch_and_authority_control_surfaces(self) -> None:
        owners = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
        for path in (
            "/.github/dependabot.yml",
            "/.github/workflows/",
            "/.gitignore",
            "/.dockerignore",
            "/scripts/check_automation_contract.py",
            "/scripts/check_branch_flow.py",
            "/scripts/build_public_inspection_manifest.py",
            "/scripts/validate_repository.py",
            "/flyway.conf",
            "/tests/test_branch_flow.py",
            "/tests/test_database_migrations.py",
            "/tests/test_public_inspection_manifest.py",
            "/tests/test_postgres_integration.py",
            "/tests/test_sql_tenant_boundary.py",
            "/src/lims_eln_implementation/bounded_caller.py",
            "/src/lims_eln_implementation/bounded_examples.py",
            "/src/lims_eln_implementation/production_adapters.py",
            "/release/",
            "/database/",
            "/machine-node.json",
            "/first-receipt.json",
            "/COORDINATION-HORIZON.json",
        ):
            with self.subTest(path=path):
                self.assertIn(f"{path} @driftframestudios", owners)


    def test_stable_implementation_context_fails_closed_on_matrix_result(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("\n  implementation-validation:\n", workflow)
        self.assertIn(
            "if: ${{ always() && vars.ENABLE_GITHUB_ACTIONS == 'true' && inputs.confirm_run }}",
            workflow,
        )
        self.assertIn('test "$VALIDATE_RESULT" = "success"', workflow)
        self.assertIn('test "$POSTGRES_RESULT" = "success"', workflow)
        self.assertRegex(
            workflow,
            r"image: postgres:17\.10-alpine@sha256:[a-f0-9]{64}",
        )
        self.assertRegex(
            workflow,
            r"FLYWAY_IMAGE: flyway/flyway:13\.0\.0-alpine@sha256:[a-f0-9]{64}",
        )
        self.assertIn("-target=003 migrate", workflow)
        self.assertIn("migration 003 through 005", workflow.lower())
        self.assertIn("run_flyway validate", workflow)
        self.assertIn("run_flyway info", workflow)
        self.assertIn("FLYWAY_USER: laboratory_migrator", workflow)
        self.assertIn("true:false:false:false:false:false", workflow)
        self.assertIn("false:false:true", workflow)
        self.assertIn("granted_role.rolname = 'laboratory_outbox_authority'", workflow)
        self.assertIn("member_role.rolname = 'laboratory_owner'", workflow)
        self.assertIn("role=laboratory_owner", workflow)
        self.assertIn(
            "laboratory_migrator:laboratory_owner:laboratory_owner",
            workflow,
        )
        self.assertIn("set role none; begin; create table", workflow.lower())
        self.assertNotIn("options=-c%20role%3D", workflow)
        self.assertIn("flyway_schema_history", workflow)
        self.assertIn('= "laboratory_owner"', workflow)
        self.assertIn('= "laboratory_outbox_authority"', workflow)
        self.assertEqual(
            workflow.count(
                "pg_catalog.to_regprocedure("
                "'public.claim_outbox_delivery(text,integer)')"
            ),
            3,
        )
        self.assertNotIn("pg_catalog.pg_get_function_identity_arguments", workflow)
        self.assertIn("has_schema_privilege", workflow)
        self.assertEqual(
            workflow.count(
                "has_column_privilege('laboratory_owner', "
                "'public.transactional_outbox', 'payload', 'insert')"
            ),
            2,
        )
        self.assertEqual(
            workflow.count(
                "has_table_privilege('laboratory_outbox_authority', "
                "'public.outbox_delivery_attempt', 'update')"
            ),
            2,
        )
        self.assertEqual(
            workflow.count(
                "has_table_privilege('laboratory_outbox_authority', "
                "'public.outbox_delivery_attempt_outcome', 'update')"
            ),
            2,
        )
        self.assertEqual(
            workflow.count(
                "has_table_privilege('laboratory_outbox_authority', "
                "'public.transactional_outbox', 'insert')"
            ),
            2,
        )
        self.assertIn("clean and upgraded schema convergence", workflow.lower())
        self.assertNotIn("apply_database_migrations.py", workflow)


if __name__ == "__main__":
    unittest.main()
