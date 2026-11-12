"""Offline safe ingestion of authenticated account-specific GitHub Actions email alerts.

Email-derived alerts can ONLY warn or hold future jobs. They cannot increase
budgets, resume an owner, dispatch anything, or change credentials.
"""
from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from .models import ConfigError, timestamp, NAME

EVENT_ID = re.compile(r"^[a-f0-9]{64}$")
THRESHOLDS = {75, 85, 90, 100}


def validate_alert_parts(event_id, owner_id, threshold_pct, observed_at):
    if not isinstance(event_id, str) or not EVENT_ID.fullmatch(event_id):
        raise ConfigError("Alert event ID must be SHA-256 hex")
    if not isinstance(owner_id, str) or not NAME.fullmatch(owner_id):
        raise ConfigError("Invalid alert owner ID")
    if type(threshold_pct) is not int or threshold_pct not in THRESHOLDS:
        raise ConfigError("Unsupported alert threshold; only 75,85,90,100")
    if not isinstance(observed_at, str) or not observed_at.endswith("Z"):
        raise ConfigError("Alerts must use normalized UTC/Z timestamp")
    observed = timestamp(observed_at)
    if observed.tzinfo is None:
        raise ConfigError("Timezone missing")
    now=datetime.now(timezone.utc)
    seconds=(now-observed).total_seconds()
    if not -300 <= seconds <= 45*24*3600:
        raise ConfigError("Future or very old alert rejected")


def load_alert(path):
    raw=json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw,dict) or set(raw)!={"schema","source","event_id","owner_id","product","threshold_pct","observed_at_utc","owner_identity_verified"}:
        raise ConfigError("Unexpected alert fields")
    if raw["schema"]!=1 or raw["source"]!="gmail_app_script" or raw["product"]!="github_actions" or raw["owner_identity_verified"] is not True:
        raise ConfigError("Unverified source, account or unrelated product")
    validate_alert_parts(raw["event_id"],raw["owner_id"],raw["threshold_pct"],raw["observed_at_utc"])
    return raw


def ingest_verified_alert(db,raw,configured_owner_ids):
    """Caller must verify provenance; this flag alone is NOT authentication."""
    if raw["owner_id"] not in configured_owner_ids:
        raise ConfigError("Unrecognized alert account: no mutation")
    return db.record_quota_alert(event_id=raw["event_id"],owner_id=raw["owner_id"],
                                 threshold_pct=raw["threshold_pct"],
                                 observed_at=raw["observed_at_utc"])


def load_routing(path,configured_ids):
    raw=json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw,dict) or set(raw)!={"schema","priority","yahoo_backup","yahoo_last"}:
        raise ConfigError("Unknown routing fields")
    p=raw["priority"]
    if raw["schema"]!=1 or not isinstance(p,list) or not p or len(set(p))!=len(p) or set(p)!=set(configured_ids):
        raise ConfigError("Routing priority must contain each configured owner exactly once")
    if raw["yahoo_last"] is not True or raw["yahoo_backup"] not in p or p[-1]!=raw["yahoo_backup"]:
        raise ConfigError("Yahoo must be explicitly last, not first or balanced by capacity")
    return tuple(p)


def preview_routing(db,accounts,budgets,routing_priority):
    from .scheduler import budget_fresh
    rows=[]
    for owner in routing_priority:
        a=accounts[owner]
        hold=db.account_hold(owner)
        quota=budgets.get(owner)
        reason=("held_by_email" if hold and hold["level"]=="hold" else
                "unknown_or_stale_budget" if not a.public_standard_runner and not budget_fresh(quota) else
                "potentially_eligible_requires_preflight")
        rows.append({"owner_id":owner,"position":len(rows)+1,"mail_alert":hold["level"] if hold else "none",
                     "status":reason})
    return rows
