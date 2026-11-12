"""Verify Gmail-signed private GitHub issue receipts before mutating queue holds.

Issue bodies and forwarded messages are untrusted. Valid HMAC permits only
monotonic alert HOLD/WARN; cannot dispatch, grant credits, clear holds or modify
a GitHub workflow.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import re
from .alerts import validate_alert_parts
from .models import ConfigError

MARKER="QUOTAFLOW_ACTIONS_ALERT_V1\n"
ALERT_FIELDS={"schema","source","event_id","owner_id","product",
              "threshold_pct","observed_at_utc","owner_identity_verified"}


def canonical(item):
    return "|".join((item["event_id"],item["owner_id"],item["product"],
                     str(item["threshold_pct"]),item["observed_at_utc"]))


def sign_for_tests_only(item,secret):
    """Pure helper; production signing is performed in the private Gmail script."""
    if not isinstance(secret,str) or len(secret)<32:
        raise ConfigError("Alert signing secret must be at least 32 characters")
    return hmac.new(secret.encode("utf-8"),canonical(item).encode("utf-8"),hashlib.sha256).hexdigest()


def verify_comment_body(body,secret,known_owners):
    if not isinstance(body,str) or not body.startswith(MARKER):
        return None
    try:
        event=json.loads(body[len(MARKER):])
    except (TypeError,json.JSONDecodeError):
        return None
    if not isinstance(event,dict) or set(event)!=ALERT_FIELDS|{"signature"}:
        return None
    if event.get("schema")!=1 or event.get("source")!="gmail_app_script":
        return None
    if event.get("product")!="github_actions" or event.get("owner_identity_verified") is not True:
        return None
    if event.get("owner_id") not in known_owners:
        return None
    try:
        validate_alert_parts(event["event_id"],event["owner_id"],
                             event["threshold_pct"],event["observed_at_utc"])
    except (ConfigError,ValueError,TypeError):
        return None
    sig=event["signature"]
    if not isinstance(sig,str) or re.fullmatch(r"[a-f0-9]{64}",sig) is None:
        return None
    if not hmac.compare_digest(sign_for_tests_only(event,secret),sig):
        return None
    return {k:event[k] for k in ALERT_FIELDS}


def import_issue_comments(db,comments,secret,configured_owners):
    if not isinstance(comments,list):
        raise ConfigError("Issue comment feed must be a JSON array")
    if not isinstance(secret,str) or len(secret)<32:
        raise ConfigError("Missing properly sized signing secret")
    counts={"accepted":0,"duplicates":0,"ignored_or_unverified":0}
    for entry in comments:
        if not isinstance(entry,dict):
            counts["ignored_or_unverified"]+=1
            continue
        event=verify_comment_body(entry.get("body"),secret,configured_owners)
        if not event:
            counts["ignored_or_unverified"]+=1
            continue
        state=db.record_quota_alert(event_id=event["event_id"],
                                   owner_id=event["owner_id"],
                                   threshold_pct=event["threshold_pct"],
                                   observed_at=event["observed_at_utc"])
        counts["duplicates" if state=="already_ingested" else "accepted"]+=1
    return counts

def fetch_private_issue_comments(*, repository, issue_number, token, max_pages=5, opener=None):
    """Read-only private issue feed, no token logging, no arbitrary URL target."""
    from urllib import request, error
    from .models import REPO
    if not isinstance(repository,str) or not REPO.fullmatch(repository):
        raise ConfigError("Invalid repository")
    if type(issue_number) is not int or not 1<=issue_number<=100000000:
        raise ConfigError("Invalid issue number")
    if not isinstance(token,str) or not token:
        raise ConfigError("Private issue read token required")
    opener=opener or request.urlopen
    combined=[]
    for page in range(1,max_pages+1):
        req=request.Request(
            "https://api.github.com/repos/"+repository+"/issues/"+str(issue_number)+
            "/comments?per_page=100&page="+str(page),
            headers={"Authorization":"Bearer "+token,
                     "Accept":"application/vnd.github+json",
                     "User-Agent":"QuotaFlow-private-alerts-read",
                     "X-GitHub-Api-Version":"2022-11-28"})
        try:
            with opener(req,timeout=20) as response:
                payload=json.loads(response.read())
        except (error.HTTPError,error.URLError,TimeoutError) as exc:
            raise ConfigError("Cannot read authorized private issue feed") from None
        if not isinstance(payload,list):
            raise ConfigError("Expected GitHub issue comments array")
        combined.extend(payload)
        if len(payload)<100:
            return combined
    raise ConfigError("Private issue comments exceed safe paging limit; manual audit required")
