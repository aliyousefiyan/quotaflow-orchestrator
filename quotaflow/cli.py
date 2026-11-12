"""Public CLI; all network-changing operations require an explicit flag."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from .models import ConfigError, Job, load_accounts, load_budgets
from .db import QueueDB
from .scheduler import plan, dispatch_one, sync
from .github_api import GitHub, GitHubError


def main(argv=None):
    p=argparse.ArgumentParser(prog="quotaflow",description="Quota-aware GitHub workflow queue; default safe/read-only")
    p.add_argument("--config",default="accounts.json")
    p.add_argument("--budgets",default="budgets.json")
    p.add_argument("--state",default=".quotaflow/queue.sqlite3")
    sub=p.add_subparsers(dest="command",required=True)
    enq=sub.add_parser("enqueue",help="Add immutable job definitions from JSON")
    enq.add_argument("--file",required=True)
    sub.add_parser("plan",help="No network or mutation")
    dispatch=sub.add_parser("dispatch",help="Dispatch at most one job if verified and quota-eligible")
    dispatch.add_argument("--approve-dispatch",action="store_true",help="Required for network-changing action")
    sub.add_parser("sync",help="Read-only remote run reconciliation")
    sub.add_parser("doctor",help="Verify remote ownership and worker contracts (read-only)")
    sub.add_parser("billing-probe",help="Try read-only billing endpoint without auto-granting quota")
    sub.add_parser("codex-limits",help="Read Codex rate windows via official local app-server (no model turn)")
    ai=sub.add_parser("ai-plan",help="Plan Work and Codex tasks against shared manually attested credits")
    ai.add_argument("--ai-tasks",required=True)
    ai.add_argument("--ai-budget",required=True)
    args=p.parse_args(argv)
    if args.command in ("codex-limits","ai-plan"):
        try:
            from .codex_usage import CodexLimitError, get_rate_limits, plan_ai_tasks
            if args.command=="codex-limits":
                value=get_rate_limits()
            else:
                tasks=json.loads(Path(args.ai_tasks).read_text(encoding="utf-8"))
                budget=json.loads(Path(args.ai_budget).read_text(encoding="utf-8"))
                value=plan_ai_tasks(tasks,budget)
            print(json.dumps(value,ensure_ascii=False,indent=2))
            return 0
        except (CodexLimitError,ValueError,OSError,json.JSONDecodeError) as exc:
            print(json.dumps({"error":str(exc)},ensure_ascii=False))
            return 2
    db=None
    try:
        accounts=load_accounts(args.config)
        budgets=load_budgets(args.budgets)
        db=QueueDB(args.state)
        if args.command=="enqueue":
            raw=json.loads(Path(args.file).read_text(encoding="utf-8"))
            if not isinstance(raw,list):
                raise ConfigError("Job definitions must be a JSON list")
            value=[{"id":j.id,"status":db.add(j)} for j in (Job.parse(v) for v in raw)]
        elif args.command=="plan":
            value=plan(db,accounts,budgets)
        elif args.command=="dispatch":
            value=dispatch_one(db,accounts,budgets,approved=args.approve_dispatch)
        elif args.command=="sync":
            value=sync(db,accounts)
        elif args.command in ("doctor","billing-probe"):
            value=[]
            for a in accounts.values():
                try:
                    client=GitHub(a)
                    # Verify identity before doing any billing action
                    verified=client.verify()
                    if args.command=="billing-probe":
                        verified.update(client.billing_probe())
                    value.append({"id":a.id,"status":"ok","verified":verified})
                except GitHubError as exc:
                    value.append({"id":a.id,"status":"blocked","reason":str(exc)})
        else:
            raise AssertionError(args.command)
        print(json.dumps(value,ensure_ascii=False,indent=2))
        return 0
    except (ValueError,KeyError,OSError,json.JSONDecodeError,ConfigError) as exc:
        print(json.dumps({"error":str(exc)},ensure_ascii=False))
        return 2
    finally:
        if db is not None:
            db.close()

if __name__=="__main__":
    sys.exit(main())
