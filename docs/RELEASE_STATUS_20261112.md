# QuotaFlow v0.3.0 — release verification

**Status:** public, tested reference implementation for deterministic jobs. Not a deployed trading service and not an unattended cross-owner private workflow dispatcher.

## Live GitHub evidence (2026-11-12)

| Check | Result |
|---|---|
| GitHub CI, default branch | [PASS](https://github.com/aliyousefiyan/quotaflow-orchestrator/actions/runs/43209855374) |
| GitHub CI, feature PR | [PASS](https://github.com/aliyousefiyan/quotaflow-orchestrator/actions/runs/43209798654) |
| Controller: SQLite queue -> verified public owner/workflow -> dispatch | [PASS](https://github.com/aliyousefiyan/quotaflow-orchestrator/actions/runs/43209855212) |
| Worker: accepted and executed controller job | [PASS](https://github.com/aliyousefiyan/quotaflow-orchestrator/actions/runs/43209874513) |
| Prior public direct action-to-worker smoke | [PASS](https://github.com/aliyousefiyan/quotaflow-orchestrator/actions/runs/43206575537) |
| Automated security and functional unit tests | 51 expected tests; CI job PASS |

## Operating boundaries

- Public same-repository jobs can use ephemeral GitHub Actions GITHUB_TOKEN only when the current owner/repo, target default branch, repository visibility and reviewed worker contract all match. Actual smoke dispatch succeeded.
- Separate private owner repositories may install the identical reviewed manual-only worker contract, but require distinct **authorized owner tokens** and current, verified spendable billing capacity before the controller can dispatch them.
- Unknown or stale private GitHub Actions budgets cause an intentional hard block; estimates and fallback accounts do not override this.
- The local Codex app-server rate-limit probe is read-only and does not run any model. It reports time-window usage only; it **does not establish Work/Codex shared monthly credit balances**. The combined budget planner requires separately attested credit observations and never auto-launches agents.
- This version contains no arbitrary remote shell execution, secrets, trading API calls, automated account creation, background host service, or private market dataset upload.
- Existing trading projects require independent source SHA, causal data checks, explicit preflight and user authorization before integration. This pilot does not replace those gates.

## Recommended safe usage

Run existing source-verified deterministic jobs on owner-approved standard GitHub runners; use public compute only for non-sensitive, open-source workloads. Keep proprietary trading datasets in private repositories under each owner's legitimate quota. Review the owner-specific budget dashboard and project configuration before allowing any private dispatch.

Version: `0.3.0` / main commit after security reviewed PR #2: `831a7fa074de42bec794654faec09dbf7aed354b`.
