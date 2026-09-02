#!/usr/bin/env python3
"""Check pull-request coordinates against this repository's GitFlow contract."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import re
import sys
from typing import Pattern


BRANCH_PATTERN = re.compile(
    r"^(?:main|develop|"
    r"(?:feature|fix|chore|experiment|hotfix|evidence)/"
    r"[a-z0-9]+(?:-[a-z0-9]+)*|"
    r"forecast/(?:20[0-9]{2})-q[1-4]-r[1-9][0-9]*|"
    r"release/(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*))$"
)
_SAFE_AUTOMATION_SEGMENT = (
    r"[A-Za-z0-9](?:[A-Za-z0-9._+@-]*[A-Za-z0-9])?"
)
_SAFE_AUTOMATION_PATH = (
    rf"(?!.*\.\.)(?!.*@\{{){_SAFE_AUTOMATION_SEGMENT}"
    rf"(?:/{_SAFE_AUTOMATION_SEGMENT})*"
)
DEPENDABOT_BRANCH_ECOSYSTEMS = frozenset(
    {"docker", "github_actions", "pip", "terraform"}
)


@dataclass(frozen=True)
class AutomationRule:
    """Bind one maintenance grammar to its pull-request identity and targets."""

    label: str
    branch_pattern: Pattern[str]
    authors: frozenset[str]
    targets: frozenset[str]


AUTOMATION_RULES = (
    AutomationRule(
        label="Dependabot",
        branch_pattern=re.compile(
            rf"^dependabot/(?:"
            rf"{'|'.join(re.escape(item) for item in sorted(DEPENDABOT_BRANCH_ECOSYSTEMS))}"
            rf")/{_SAFE_AUTOMATION_PATH}$"
        ),
        authors=frozenset({"dependabot[bot]"}),
        targets=frozenset({"main", "develop"}),
    ),
    AutomationRule(
        label="Renovate",
        branch_pattern=re.compile(rf"^renovate/{_SAFE_AUTOMATION_PATH}$"),
        authors=frozenset({"renovate[bot]"}),
        targets=frozenset({"main", "develop"}),
    ),
)


def automation_rule(head: str) -> AutomationRule | None:
    """Resolve a complete automated-maintenance source coordinate."""
    for rule in AUTOMATION_RULES:
        if rule.branch_pattern.fullmatch(head):
            return rule
    return None


def allowed_sources(base: str) -> tuple[str, ...]:
    """Return the source families that can advance the selected target."""
    if base == "main":
        return ("release/", "hotfix/")
    if base == "develop":
        return (
            "feature/",
            "fix/",
            "chore/",
            "experiment/",
            "forecast/",
            "evidence/",
            "release/",
            "hotfix/",
        )
    if base.startswith("release/"):
        return ("fix/", "chore/")
    return ()


def check_flow(base: str, head: str, author: str = "") -> list[str]:
    """Return actionable differences for one proposed merge coordinate."""
    findings: list[str] = []
    if BRANCH_PATTERN.fullmatch(base) is None:
        findings.append(f"target branch {base!r} is outside the branch naming contract")

    rule = automation_rule(head)
    if rule is not None:
        if base not in rule.targets:
            findings.append(
                f"{rule.label} source branch {head!r} should target one of "
                f"{', '.join(sorted(rule.targets))}"
            )
        if author not in rule.authors:
            findings.append(
                f"{rule.label} source branch {head!r} requires pull-request author "
                f"{', '.join(sorted(rule.authors))}; received {author or '<empty>'!r}"
            )
        return findings

    if BRANCH_PATTERN.fullmatch(head) is None:
        findings.append(f"source branch {head!r} is outside the branch naming contract")
    families = allowed_sources(base)
    if families and not head.startswith(families):
        findings.append(
            f"source branch {head!r} should use one of {', '.join(families)} "
            f"for target {base!r}"
        )
    if not families and BRANCH_PATTERN.fullmatch(base):
        findings.append(f"target branch {base!r} is a source branch rather than a merge target")
    return findings


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="")
    parser.add_argument("--head", default="")
    parser.add_argument(
        "--author",
        default="",
        help="Pull-request author login used to bind automated maintenance branches",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if not args.base and not args.head and not args.author:
        print("Branch-flow check skipped for a non-pull-request event.")
        return 0
    if not args.base or not args.head or not args.author:
        print(
            "Branch-flow check requires base, head, and pull-request author "
            "coordinates together."
        )
        return 2
    findings = check_flow(args.base, args.head, args.author)
    if findings:
        print("Branch-flow check found coordinate differences:")
        for finding in findings:
            print(f"  - {finding}")
        return 1
    rule = automation_rule(args.head)
    if rule is not None:
        print(
            f"{rule.label} branch passed its automation flow: "
            f"{args.head} -> {args.base}"
        )
        return 0
    print(f"Branch-flow check passed: {args.head} -> {args.base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
