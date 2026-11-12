"""Read-only Codex app-server rate-limit probe; never starts an AI turn.

Uses the officially documented account/rateLimits/read JSON-RPC request.
Never reads auth.json, prints tokens or treats Codex windows as Work credits.
"""
from __future__ import annotations

import json
import queue
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone

class CodexLimitError(RuntimeError):
    pass

def summarize_rate_limits(result):
    """Extract only non-sensitive, bounded quota fields."""
    if not isinstance(result, dict):
        raise CodexLimitError("Invalid app-server response")
    buckets=result.get("rateLimitsByLimitId")
    if not isinstance(buckets,dict) or not buckets:
        buckets={"codex":result.get("rateLimits")}
    output=[]
    for name, entry in sorted(buckets.items()):
        if not isinstance(entry, dict):
            continue
        record={"bucket":str(name), "limit_id":entry.get("limitId"),
                "plan_type":entry.get("planType"), "reached":entry.get("rateLimitReachedType")}
        for period in ("primary","secondary"):
            obj=entry.get(period)
            if isinstance(obj,dict):
                used=obj.get("usedPercent")
                duration=obj.get("windowDurationMins")
                reset=obj.get("resetsAt")
                if type(used) in (int,float) and 0<=used<=100:
                    record[period]={"used_percent":round(float(used),3),
                                     "remaining_percent":round(100-float(used),3),
                                     "window_minutes":duration if type(duration) in (int,float) else None,
                                     "resets_unix":reset if type(reset) in (int,float) else None}
        output.append(record)
    return {"observed_utc":datetime.now(timezone.utc).isoformat(),
            "source":"codex_app_server_read_only","windows":output,
            "work_shared_monthly_credit":"unknown_not_inferred"}

def get_rate_limits(timeout=75,executable=None):
    executable=executable or shutil.which("codex.cmd") or shutil.which("codex")
    if not executable:
        raise CodexLimitError("Codex CLI is not installed or not in PATH")
    proc=None
    try:
        proc=subprocess.Popen([executable,"app-server","--listen","stdio://"],
                              stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL,text=True,bufsize=1,
                              creationflags=getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0))
        incoming=queue.Queue()
        def pump():
            for line in proc.stdout:
                try: incoming.put(json.loads(line))
                except (ValueError,TypeError): pass
        threading.Thread(target=pump,daemon=True).start()
        def send(msg):
            proc.stdin.write(json.dumps(msg,separators=(",",":"))+"\n")
            proc.stdin.flush()
        def receive(target, deadline):
            while time.monotonic()<deadline:
                if proc.poll() is not None:
                    break
                try: msg=incoming.get(timeout=0.3)
                except queue.Empty: continue
                if msg.get("id")==target:
                    return msg
            raise CodexLimitError("Codex local quota request timed out or exited")
        deadline=time.monotonic()+timeout
        send({"method":"initialize","id":1,
              "params":{"clientInfo":{"name":"quotaflow","title":"QuotaFlow read-only quota","version":"0.2.0"}}})
        init=receive(1,deadline)
        if "result" not in init:
            raise CodexLimitError("Codex app-server initialize denied")
        send({"method":"initialized","params":{}})
        send({"method":"account/rateLimits/read","id":2})
        answer=receive(2,deadline)
        if "result" not in answer:
            raise CodexLimitError("Codex rate-limit read unsupported or denied")
        return summarize_rate_limits(answer["result"])
    except (OSError,BrokenPipeError) as ex:
        raise CodexLimitError("Unable to start Codex rate-limit probe") from ex
    finally:
        if proc is not None:
            try: proc.stdin.close()
            except (OSError,AttributeError): pass
            try: proc.terminate()
            except OSError: pass
            try: proc.wait(timeout=2)
            except (OSError,subprocess.TimeoutExpired):
                try: proc.kill()
                except OSError: pass

def plan_ai_tasks(tasks,manual_budget,now=None):
    """Plan but NEVER invoke Work/Codex. Codex window percentages are not monthly credits."""
    if not isinstance(tasks,list) or not isinstance(manual_budget,dict):
        raise ValueError("AI tasks and budget must be JSON list/object")
    now=now or datetime.now(timezone.utc)
    stamp=manual_budget.get("as_of_utc")
    remaining=manual_budget.get("shared_remaining_pct")
    fresh=False
    if isinstance(stamp,str):
        try:
            observed=datetime.fromisoformat(stamp.replace("Z","+00:00"))
            fresh=observed.tzinfo is not None and -300 <= (now-observed).total_seconds() <= 12*3600
        except ValueError:
            pass
    valid_remaining=type(remaining) in (int,float) and 0<=remaining<=100
    available=remaining if fresh and valid_remaining else None
    results=[]
    for item in tasks:
        if not isinstance(item,dict) or set(item)!={"id","project","surface","estimated_pct","description"}:
            raise ValueError("Every AI task must use exact declarative fields")
        if item["surface"] not in ("codex","work") or not isinstance(item["id"],str) or not isinstance(item["project"],str) or not isinstance(item["description"],str):
            raise ValueError("Invalid AI task surface or text")
        estimate=item["estimated_pct"]
        if type(estimate) not in (int,float) or not 0<=estimate<=100:
            raise ValueError("Invalid AI budget estimate")
        if available is None:
            status="blocked_shared_credit_unknown"
        elif available-estimate<30:
            status="blocked_shared_credit_reserve"
        else:
            status="manual_agent_approval_required"
            available-=estimate
        results.append({"id":item["id"],"project":item["project"],"surface":item["surface"],"status":status,"description":item["description"]})
    return {"source":"human_attested_shared_budget","estimated_available_after_planning":available,"tasks":results}
