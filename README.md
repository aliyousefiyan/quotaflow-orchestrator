# QuotaFlow Orchestrator

**A safe, quota-aware controller for deterministic jobs across multiple GitHub Actions repository owners.** No paid service required for the controller, no external Python packages, and no dependence on Codex/Work for jobs already implemented as ordinary scripts.

> v0.3.0 — verified pilot, not production trading software. Explicit GitHub workflow dispatch is supported; automatic unattended scheduling and live multi-owner deployment are **not** enabled. When billing data is unavailable or stale, private repo jobs are blocked. This is intentional.

[راهنمای فارسی](README.fa.md) · [Security](SECURITY.md) · [Architecture](docs/ARCHITECTURE.md) · [Activation approvals (FA)](docs/ACTIVATION_APPROVALS_FA.md) · [Activation approvals (EN)](docs/ACTIVATION_APPROVALS_EN.md)

## Why this exists

- **Three GitHub accounts are not one shared quota**: GitHub Actions costs are billed to the **repository owner**, not the triggerer. To draw from separate included allowances, use distinct approved worker repositories owned by each respective account. Never evade platform conditions or abuse accounts.
- Public repositories with **standard GitHub-hosted runners** generally have free job compute, subject to GitHub policies, abuse limits, storage, concurrency and other constraints. Private repositories use the respective owner's current included allowance and billing rules (which GitHub may express as money or minutes).
- ChatGPT **Work and Codex share a separate OpenAI allowance** in eligible plans. GitHub Actions execution does not itself debit Work/Codex credits, but **calling AI inside workflows does** if you configure a paid API. This project makes no paid AI API calls.
- Desktop Commander has its own limits. It is not required for the main runtime.

## Features shipped

1. Strict JSON configuration (no tokens in files; only secret environment-variable names).
2. Durable, idempotent SQLite queue and immutable jobs.
3. Cross-owner routing by validated account identity, owner-controlled repository, allowlisted worker and profiled job type.
4. Conservative budget plans per account (staleness cap 12 h, extra reserve, tracked dispatch commitments). No fake quotas or silently inferred allowances.
5. Maximum **one active run per owner**, **one dispatch per CLI invocation**, and no network writes without `--approve-dispatch`.
6. Fail-closed ambiguous network responses: no automatic duplicate dispatches after timeouts. Separate read-only `sync` recovers remote run state when possible.
7. Read-only `doctor` and `billing-probe`; no credential echo, shell injection or trading endpoints.
8. Copyable owner-side GitHub Actions worker example with only two *static* no-trading recipes; 51 automated unit tests.
9. Official **read-only local Codex rate-window probe** via app-server; shared Work/Codex allowance planner with 30% reserve and manual approval gate.

## Install and offline demonstration

Requirements: Python 3.10+ and GitHub account(s) with permission to run Actions. **No API keys required to test locally.**

```bash
python -m unittest discover -s tests -t . -v
python -m quotaflow --config examples/accounts.example.json --budgets examples/budgets.unknown.json --state /tmp/qf-demo.sqlite3 enqueue --file examples/jobs.example.json
python -m quotaflow --config examples/accounts.example.json --budgets examples/budgets.unknown.json --state /tmp/qf-demo.sqlite3 plan
```

The demo uses **unknown** budgets: no paid private workflow is dispatched. Repeat enqueue to see idempotence.

## How to connect three independent owners

1. Create a dedicated **worker repository owned by each account**. Do not point three tokens at one repository and expect separate billing. Keep private research or trading data in its authorized owner's repository only.
2. Copy `templates/worker.yml` to `.github/workflows/quotaflow-worker.yml` in each worker repository's **default branch**. Review and approve a worker-specific recipe before adding any real backtesting code. Avoid arbitrary shell command inputs.
3. Copy `examples/accounts.example.json` to `accounts.json` and edit owner/repository/allowlisted profiles. Keep this file private if it describes private infrastructure; the example is public only.
4. Provide credentials via environment variables `QF_TOKEN_OWNER_A`, `QF_TOKEN_OWNER_B`, `QF_TOKEN_OWNER_C`. Each account's token must resolve via `/user` to that configured **owner** and be authorized to read the repo and dispatch workflows. Never paste secrets into chat or GitHub code/issue content. Tokens are **not** stored by the queue.
5. Copy `examples/budgets.unknown.json` to `budgets.json`. Enter **real verified, recent, spendable** remaining USD values per owner (or set up a verified billing adapter). Do not convert old included minutes into money without checking the current plan/rate. Unknown values stay null. Budget samples are not actual allowances.
6. Test read-only: `python -m quotaflow --config accounts.json --budgets budgets.json doctor`.
7. Enqueue a task with a genuinely derived input SHA256; run `plan`, then explicitly `dispatch --approve-dispatch` to start **at most one** eligible workflow. After GitHub accepts, run `sync` to verify completion. Save artifacts in each worker repository's Actions run.

> `dispatch --approve-dispatch` is intentionally opt-in and **may incur GitHub costs** if the repo is private. The repository's owner must review allowance and spending settings first. GitHub's billing API can deny access even with valid repo credentials; the system does not guess.

## Verified GitHub Actions built-in token: public same-repository controller

A public repository can use its own short-lived, repository-scoped `GITHUB_TOKEN` to submit an allowlisted `workflow_dispatch` to **itself**, without creating a personal access token. This is an explicit opt-in via `github_actions_self_token: true` and it is accepted only when the runtime's GitHub Actions owner/repo matches the configured repository **and** GitHub verifies that repository is public and the target is the default branch. No cross-owner or private routing is allowed in this special mode.

See [controller end-to-end smoke](.github/workflows/controller-queue-e2e.yml). This safety-scoped, one-shot workflow submits a synthetic job, not trading or market data, and uploads its local queue evidence. Three *private* owner workers still require independently authorized owner tokens and real remaining budget before billing-consuming dispatch; no automatic private fanout is enabled.

## Shared Work/Codex usage control

```bash
python -m quotaflow codex-limits
python -m quotaflow ai-plan --ai-tasks examples/ai_tasks.example.json --ai-budget examples/ai_budget.unknown.json
```

Codex is queried read-only and no model turn is created. An unknown monthly shared Work/Codex credit value **blocks** agent tasks; Work and Codex are never invoked automatically. See [details](docs/CODEX_WORK_SHARED_USAGE.md).

## Explicit limitations

- **Codex rate-window percentages** can be read with `python -m quotaflow codex-limits` from a signed-in local Codex CLI, using its official read-only app-server API. **Work/Codex shared monthly credits** are distinct and not inferred from these windows; check supported ChatGPT account UI. Run `ai-plan` with a manually observed credit budget; it never starts an AI agent.
- The GitHub connector may not expose billing permissions; the optional `billing-probe` will report access failure and leave usable quota unknown.
- No automated quota discovery when auth/plan is unsupported; no deployment to any user's machine/server, no auto-run scheduler, no self-hosted runner or arbitrarily timed background work in this release.
- No unified risk pool for trading; no Binance keys, no order/router actions, no strategy generation, and no private model data.
- GitHub Dispatch API may acknowledge a run before it appears in the Actions listing. The worker run-name includes the job ID so `sync` can correlate a later record. Unmatched/ambiguous cases must be investigated, never retried blindly.

## GitHub and OpenAI documentation

- [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
- [GitHub REST billing usage](https://docs.github.com/en/rest/billing/usage)
- [GitHub workflow dispatch](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)
- [Codex usage](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan)

License: MIT. Contributions and security reviews welcome.
