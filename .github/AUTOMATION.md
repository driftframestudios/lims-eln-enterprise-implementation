# Human-cued automation

## Resting state

The repository rests with GitHub Actions disabled in repository settings, and the Actions spend boundary remains **$0**. Local repository validation is the standing proof path. Pull requests and pushes stay on that path; the manual workflow preserves the two-version implementation proof for an allocated dispatch.

Repository settings are the primary control. If Actions is later enabled, the workflow still requires the repository variable `ENABLE_GITHUB_ACTIONS` to equal `true` and a human to select `confirm_run` during manual dispatch. Scheduled dependency updates remain at rest while the activation template is named `dependabot.manual.yml`.

## Activation state

A named human can allocate one remote proof by enabling Actions in repository settings, setting `ENABLE_GITHUB_ACTIONS=true`, selecting the confirmation, and dispatching **implementation-proof**. Dependency update scheduling becomes active only after a human reviews the template and renames it to `.github/dependabot.yml`.

After the proof is read, set `ENABLE_GITHUB_ACTIONS=false` and return Actions in repository settings to disabled. Keep the dependency template at `.github/dependabot.manual.yml` to restore its resting state.
