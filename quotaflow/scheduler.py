"""One-shot, fail-closed scheduling across independent account owners."""
from __future__ import annotations
from datetime import datetime, timezone
import json
from .models import Account, Job, timestamp, ConfigError
from .db import QueueDB
from .github_api import GitHub, GitHubError

MAX_AGE_HOURS = 12


def budget_fresh(item, now=None):
    if not item or item.get("remaining_usd") is None or item.get("as_of_utc") is None:
        return False
    try:
        observed=timestamp(item["as_of_utc"])
    except ConfigError:
        return False
    now = now or datetime.now(timezone.utc)
    elapsed=(now-observed).total_seconds()
    return -300 <= elapsed <= MAX_AGE_HOURS * 3600


def choose(job: Job, accounts: dict[str,Account], budget: dict[str,dict], db: QueueDB, routing_priority=None):
    choices=[]
    reasons=[]
    for account_id in job.target_accounts:
        account=accounts.get(account_id)
        if not account:
            reasons.append((account_id,"not_configured"))
            continue
        if routing_priority is not None and not db.alert_source_fresh():
            reasons.append((account_id,"email_alert_feed_missing_or_stale"))
            continue
        hold=db.account_hold(account_id)
        if hold and hold["level"]=="hold":
            reasons.append((account_id,"held_by_actions_email"))
            continue
        if job.profile not in account.profiles:
            reasons.append((account_id,"profile_not_allowed"))
            continue
        if db.open_count(account_id):
            reasons.append((account_id,"busy"))
            continue
        quota=budget.get(account_id)
        if account.public_standard_runner:
            # Public standard GitHub-hosted runners do not use private-repo compute allowance;
            # still require the target verified PUBLIC via GitHub.verify() before dispatch.
            if job.estimated_usd != 0:
                reasons.append((account_id,"public_cost_must_be_zero"))
                continue
            choices.append((float("inf"),account_id))
            continue
        if not budget_fresh(quota):
            reasons.append((account_id,"budget_missing_or_stale"))
            continue
        spent_after_snapshot=db.reserved_since(account_id,quota["as_of_utc"])
        available=quota["remaining_usd"] - spent_after_snapshot - account.minimum_reserve_usd
        if available + 1e-9 < job.estimated_usd:
            reasons.append((account_id,"quota_or_reserve_insufficient"))
            continue
        choices.append((available - job.estimated_usd, account_id))
    if routing_priority is not None:
        rank={value:i for i,value in enumerate(routing_priority)}
        choices.sort(key=lambda x:(rank.get(x[1],999999),-x[0]))
    else:
        choices.sort(key=lambda x:(-x[0],x[1]))
    return (choices[0][1] if choices else None),reasons


def plan(db, accounts, budgets, routing_priority=None):
    rows=[]
    for row in db.list():
        job=Job.parse(json.loads(row["definition"]))
        target,reasons=choose(job,accounts,budgets,db,routing_priority) if row["status"] == "queued" else (row["target"],[])
        rows.append({"id":row["id"],"project":job.project,"profile":job.profile,"status":row["status"],"suggested_owner":target,"blocked_reasons":reasons})
    return rows


def dispatch_one(db: QueueDB, accounts, budgets, *, approved=False, github_factory=GitHub, routing_priority=None):
    """Never invokes external workflow until explicitly --approve-dispatch, even with available quota."""
    if not approved:
        return {"status":"dry_run", "plan":plan(db,accounts,budgets,routing_priority)}
    for row in db.list(status="queued"):
        job=Job.parse(json.loads(row["definition"]))
        target,reasons=choose(job,accounts,budgets,db,routing_priority)
        if not target:
            continue
        account=accounts[target]
        try:
            client=github_factory(account)
            client.verify()  # includes owner equality + code contract + public-status validation
        except GitHubError as exc:
            return {"id":job.id,"status":"blocked_identity_or_worker_contract","reason":str(exc)}
        snapshot=budgets.get(target,{}).get("as_of_utc") or datetime.now(timezone.utc).isoformat()
        # Unique serialized claim written BEFORE network call. If the process crashes,
        # state remains 'dispatching'; never retry automatically / risk duplicated billing.
        if not db.transition(job.id,"queued","dispatching",target=target,budget_as_of=snapshot,details="remote dispatch may be ambiguous"):
            continue
        try:
            client.dispatch(job.id,job.profile)
        except GitHubError as exc:
            db.transition(job.id,"dispatching","ambiguous",details="Dispatch uncertain; reconcile manually: "+str(exc))
            return {"id":job.id,"target":target,"status":"ambiguous"}
        db.transition(job.id,"dispatching","dispatched",details="Accepted by GitHub; awaiting matching workflow run")
        return {"id":job.id,"target":target,"status":"dispatched"}
    return {"status":"no_eligible_queued_jobs","plan":plan(db,accounts,budgets,routing_priority)}


def sync(db: QueueDB, accounts, github_factory=GitHub):
    results=[]
    for row in db.list():
        if row["status"] not in ("dispatching","dispatched","running","ambiguous") or not row["target"]:
            continue
        account=accounts.get(row["target"])
        if not account:
            results.append({"id":row["id"],"status":"blocked_unknown_account"})
            continue
        try:
            client=github_factory(account)
            client.verify()
            remote=client.find_run(row["id"])
            if not remote:
                results.append({"id":row["id"],"status":"awaiting_remote_run_or_manual_reconciliation"})
                continue
            state=remote.get("status")
            conclusion=remote.get("conclusion")
            if state == "completed":
                next_status="success" if conclusion=="success" else "failure"
            else:
                next_status="running"
            if db.transition(row["id"],row["status"],next_status,details="Remote state="+str(state)+" conclusion="+str(conclusion),remote_run_id=remote.get("id")):
                results.append({"id":row["id"],"status":next_status,"run_id":remote.get("id")})
            else:
                results.append({"id":row["id"],"status":"concurrent_transition_skipped"})
        except GitHubError as exc:
            results.append({"id":row["id"],"status":"sync_unavailable", "reason":str(exc)})
    return results
