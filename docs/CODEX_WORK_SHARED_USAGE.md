# Codex and Work: safe usage control

This project can read **Codex rate-limit windows** locally from the official `codex app-server` JSON-RPC method `account/rateLimits/read`. It does not access auth files or token secrets and does not start model turns. Try `python -m quotaflow codex-limits` on a machine with Codex CLI signed into ChatGPT.

**Important:** Codex's 5-hour and weekly `usedPercent` values are not necessarily the same thing as the available **monthly shared Work/Codex credit allowance**. Never infer Work's spendable remaining credits from those windows. Shared credits must be independently observed from supported account/workspace usage UI (when available). Not every plan offers the same dashboard. Codex and Work have shared limits in supported billing arrangements, so run only bounded AI tasks when both the relevant limits are healthy.

## Human-controlled AI task planner

```bash
python -m quotaflow ai-plan --ai-tasks examples/ai_tasks.example.json --ai-budget examples/ai_budget.unknown.json
```

The example correctly blocks both tasks: actual shared allowance is unknown.

If a supported account usage dashboard explicitly shows spendable remaining percentage, create a **local-only** AI budget file with a current UTC timestamp and a real observed value:

```json
{"as_of_utc":"2026-11-12T12:00:00+00:00","shared_remaining_pct":65}
```

The planner reserves the last 30 percentage points and allocates estimates across Work/Codex together; it **never launches either agent**. Results remain `manual_agent_approval_required` even when quota is ample.

## Safe division of labor

- Normal ChatGPT: discussion, planning, code review guidance.
- Codex/Work: complex bounded code or artifact work only when allowance supports it.
- Local deterministic Python / GitHub Actions: approved code, backtests, test suites and data-processing steps. No AI model credits are spent unless separately configured.
- Desktop Commander: emergency access to local-only files; do not poll unnecessarily.
- If any quota feed is unavailable, fail closed for that expensive runner and continue only the independent deterministic work.

Official reference: https://learn.chatgpt.com/docs/app-server
