"""Regression tests for human and automated branch coordinates."""

from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
from io import StringIO
from pathlib import Path
import re
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "scripts" / "check_branch_flow.py"
SPEC = importlib.util.spec_from_file_location("check_branch_flow", TOOL_PATH)
assert SPEC and SPEC.loader
check_branch_flow = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = check_branch_flow
SPEC.loader.exec_module(check_branch_flow)


class BranchFlowTests(unittest.TestCase):
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
            base="main",
            head="dependabot/github_actions/actions/setup-python-7.0.0",
            author="dependabot[bot]",
        )
        self.assertEqual(0, result)
        self.assertIn("Dependabot branch", output)

        result, output = self.invoke(
            base="main",
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

    def test_dependabot_config_and_grammar_share_ecosystems(self) -> None:
        config = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
        configured = {
            ecosystem.replace("-", "_")
            for ecosystem in re.findall(
                r"^\s*-\s+package-ecosystem:\s*[\"']?([a-z0-9-]+)",
                config,
                flags=re.MULTILINE,
            )
        }
        self.assertEqual(check_branch_flow.DEPENDABOT_BRANCH_ECOSYSTEMS, configured)
        self.assertNotIn("pull-request-branch-name:", config)
        self.assertEqual(
            0,
            self.invoke(
                base="main",
                head="dependabot/pip/urllib3-3.0.0",
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

    def test_workflow_uses_base_controlled_policy_with_read_only_access(self) -> None:
        workflow = (
            ROOT / ".github" / "workflows" / "branch-policy.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("pull_request_target:", workflow)
        self.assertIn("\n  branch-policy:\n", workflow)
        self.assertIn("ref: ${{ github.event.pull_request.base.sha }}", workflow)
        self.assertIn("path: base-policy", workflow)
        self.assertIn("working-directory: base-policy", workflow)
        self.assertIn(
            "PR_AUTHOR: ${{ github.event.pull_request.user.login }}",
            workflow,
        )
        self.assertIn('--author "$PR_AUTHOR"', workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertNotIn("\n  pull_request:\n", workflow)

    def test_codeowners_cover_branch_and_authority_control_surfaces(self) -> None:
        owners = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
        for path in (
            "/.github/dependabot.yml",
            "/.github/workflows/",
            "/scripts/check_branch_flow.py",
            "/flyway.conf",
            "/tests/test_branch_flow.py",
            "/tests/test_database_migrations.py",
            "/tests/test_postgres_integration.py",
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
        self.assertIn("if: ${{ always() }}", workflow)
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
        self.assertIn("run_flyway validate", workflow)
        self.assertIn("run_flyway info", workflow)
        self.assertIn("clean and upgraded schema convergence", workflow.lower())
        self.assertNotIn("apply_database_migrations.py", workflow)


if __name__ == "__main__":
    unittest.main()
