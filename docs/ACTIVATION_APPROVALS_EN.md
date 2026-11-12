# QuotaFlow — account owner activation approvals

**Status: approvals prepared, not granted** (2026-11-12). This public document intentionally excludes private repo names, private budgets and secrets.

The public v0.3 controller-to-worker path and CI passed. Three separate private owner Worker YAML contracts have been installed and verified but **not approved for spending or automated private dispatch**. Workflow profiles are fixed (`smoke`, `sample_compute`) and are manually triggered.

For **each owner**, confirm their account identity and GitHub [Billing & Licensing](https://github.com/settings/billing) usage, billing currency/allowance, actual spendable remaining amount, observation timestamp, reset time and budget/alerts. Enable the desired Actions hard limit if offered. Usage alarms alone are not hard stops. Never treat minutes as dollars without verified pricing or convert usage API totals to an allowance by guesswork. Stale or unknown private budgets stay blocked.

A private workflow dispatcher needs an owner-approved, short-lived **fine-grained** token restricted to the **one selected worker repository**, with **Repository permission: Actions (read/write)**. Store it in an operator-controlled secret store or environment; never put it in a public repo, issue, chat or screenshot. Optional billing API reads need a separate fine-grained **User permission: Plan (read-only)** token issued by the owner. A billing 403/404 means permission or endpoint support must be resolved; never invent an allowance.

Verify the worker exists on each repository's default branch and Actions is enabled. Then perform **one explicit, minimal smoke run per owner** and retain a link to a successful run. No automatic private fanout until all three are confirmed.

Codex 5-hour and weekly limit percentages can be read via its local read-only app-server endpoint. They are **not equivalent** to a spendable monthly Work/Codex shared credit amount. If a reliable monthly balance is unavailable, keep agent tasks blocked. QuotaFlow does not automatically launch Work or Codex.

Before connecting trading/backtest projects, separately verify the actual checked-out source version, project-specific handoffs, input dataset hashes, dependencies, risk isolation and release gates. Approval for smoke does **not** authorize real/demo trades, VPS changes, proprietary dataset publication, or strategy deployments.

### Acceptance gates
- [x] Public CI, public controller-to-worker E2E
- [x] 3 private worker files validated read-only
- [ ] 3 independently observed private Actions budgets and hard spending policies
- [ ] 3 minimal owner-scoped dispatcher secrets/authorizations
- [ ] 3 approved private smoke successes
- [ ] Separate project adapter + source/data tests before real research
- [ ] Separate trading deployment approval, if ever requested

Refs: [Billing](https://docs.github.com/en/billing/get-started/introduction-to-billing) · [Budgets](https://docs.github.com/en/billing/how-tos/set-up-budgets) · [Billing API](https://docs.github.com/en/rest/billing/usage) · [Dispatch API](https://docs.github.com/en/rest/actions/workflows) · [PAT security](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens).
