# One stable home per project; execution capacity is separate

QuotaFlow can resolve each project/chat to one canonical GitHub **home account** and repository, without treating that identity as a quota-balancing decision. A fixed home avoids duplicated source/data/result versions across accounts.

- Supply a private JSON `--project-registry` file conforming to [the synthetic example](../examples/project_registry.example.json).
- `project-home --project PROJECT_OR_ALIAS` reports the fixed owner, evidence status and authoritative repository.
- `proposed_home` means no verified repository: QuotaFlow rejects any dispatch for that project. The operator must verify active source and provenance first.
- Verified projects are **owner-only by default**, even if another account has available Actions quota.
- Delegation is restricted to explicitly listed, static synthetic `smoke` or `sample_compute` profiles; real private code/data/strategies cannot be shipped cross-owner by changing a field. The existing workflow allowlist, explicit approval, budget and owner verification remain mandatory.
- Yahoo is a last-resort compute runner, NOT an automatic source code mirror.
- A repo containing multiple old projects is not evidence that all its folders are currently deployed. Separating project archives into dedicated repos requires source/runtime verification, backups, migration approval and hash checks.
- At 00:00 UTC on the first day of every calendar month, prior-month email holds become inactive for the new period but remain in immutable SQLite alert history. **Never** infer new spendable credits: a prior-month budget snapshot is invalid at rollover even if less than 12 hours old.

The public example deliberately contains no account credentials or private repository catalog. Keep the real registry and its chat handoffs **private**. See [Persian policy](PROJECT_OWNERSHIP_POLICY_FA.md).
