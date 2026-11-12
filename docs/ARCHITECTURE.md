# Architecture and release gates

## Control plane vs workers

The public controller stores non-secret job definitions and receipt metadata in a local SQLite database. GitHub Actions *workers* live in separate GitHub repositories; for private repos, each owner pays for its own runner usage. Public standard GitHub-hosted runner jobs are generally free subject to terms, and still require real verification that the repo is public and the worker is on a standard runner. No private exchange data is transferred by the controller.

```text
Operator -> enqueue immutable job -> SQLite WAL queue -> safe PLAN
                         |                         |
                 unknown budget BLOCK         owner A/B/C verified
                                                   |
                                         explicit --approve-dispatch
                                                   |
                        GitHub API / owner repo / allowlisted workflow
                                                   |
                                     read-only sync by unique run-name
                                                   |
                            success | failure | ambiguous (no retry)
```

## Why a budget is conservative

GitHub switched toward compute-dollar allowances and some plans/reporting surfaces vary. The `budgets.json` entries are **explicit spendable remaining dollars**, verified for the owner and billing period by a human, not arbitrary monthly prices. Entries older than 12 hours fail closed. Dispatches since the snapshot are reserved, including completed ones, until a fresh quota reading replaces the snapshot. A minimum reserve remains untouched; only one in-flight per owner. The `public_standard_runner` option is allowed only for a verified public repository and the bundled standard runner workflow.

## Dispatch ambiguity

GitHub `workflow_dispatch` often returns no run ID (204 response). The queue persists a `dispatching` marker before sending the HTTP request. A failed request may have been accepted remotely; the local state becomes `ambiguous` and **cannot be re-dispatched without explicit reconciliation**. `sync` scans the destination workflow recent runs and correlates the controlled `run-name` string. For production use with more than 100 concurrent recent runs, add paginated search before claiming guaranteed reconciliation; the current version will return "awaiting" if absent.

## Source controls

We do **not** execute arbitrary uploaded code, remote URLs, bash snippets, AI prompts, arbitrary expressions, or server scripts. Job profiles are allowlisted twice: at the controller and in the worker YAML. Inputs are restricted to job ID and selected profile. The examples do no network calls or financial computation. To extend to actual backtests, write a deterministic, version-controlled, reviewed profile in the specific owner's private worker repo and validate market data provenance, SHA, causal integrity and release tags separately.

## Risk and anti-abuse

- No trading or deployment writes; no Binance API.
- No use of multiple accounts to evade bans/payment obligations; only legitimate, individually owned usage.
- Secrets only environment variables in the controller machine; GitHub repository variables/secret scopes must be reviewed.
- Human-approved cost reservation; no hidden cron that drains allowance.
- Never publish private datasets or ledger to public worker to exploit free minutes.
- Restrict PR Actions from forks, protect branches, pin third-party actions when hardening for production.

## Future work (not shipped)

- Permission-scoped automated billing reader for accounts that expose it.
- Optional user-controlled local scheduled trigger or service, following a separate security review.
- Worker artifact digest verification, pagination and attestation.
- Private per-project adapter with reviewed profile contracts.
- A supported personal Work/Codex usage feed, if available; until then, manual quota entry only.
