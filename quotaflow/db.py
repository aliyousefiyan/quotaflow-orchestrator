"""Atomic SQLite queue and immutable dispatch accounting."""
from __future__ import annotations
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from .models import Job, ConfigError


def utcnow():
    return datetime.now(timezone.utc).isoformat()

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY,
 fingerprint TEXT NOT NULL,
 definition TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'queued',
 target TEXT,
 dispatched_at TEXT,
 budget_as_of TEXT,
 remote_run_id INTEGER,
 details TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs(status);
CREATE TABLE IF NOT EXISTS quota_alerts (
  event_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  threshold_pct INTEGER NOT NULL,
  action TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  ingested_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quota_source_health (
  source TEXT PRIMARY KEY,
  last_success_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quota_account_holds (
  owner_id TEXT PRIMARY KEY,
  level TEXT NOT NULL,
  threshold_pct INTEGER NOT NULL,
  event_id TEXT NOT NULL,
  observed_at TEXT NOT NULL
);

"""

class QueueDB:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        self.conn.executescript(SCHEMA)
        self.conn.row_factory = sqlite3.Row

    def close(self):
        self.conn.close()

    def add(self, job: Job):
        definition = {"id": job.id, "project": job.project, "profile": job.profile, "estimated_usd": job.estimated_usd,
                      "priority": job.priority, "target_accounts": list(job.target_accounts), "inputs_digest": job.inputs_digest}
        raw = json.dumps(definition, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(raw.encode()).hexdigest()
        now = utcnow()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            prev = self.conn.execute("SELECT fingerprint FROM jobs WHERE id=?", (job.id,)).fetchone()
            if prev and prev[0] != digest:
                raise ConfigError("Existing job ID differs from queued immutable payload")
            if not prev:
                self.conn.execute("INSERT INTO jobs(id,fingerprint,definition,status,created_at,updated_at) VALUES(?,?,?,?,?,?)", (job.id,digest,raw,'queued',now,now))
            self.conn.execute("COMMIT")
            return "already_queued" if prev else "queued"
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise

    def list(self, status=None):
        if status:
            rows=self.conn.execute("SELECT * FROM jobs WHERE status=? ORDER BY json_extract(definition,'$.priority'), created_at",(status,)).fetchall()
        else:
            rows=self.conn.execute("SELECT * FROM jobs ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]

    def get(self, job_id):
        r=self.conn.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone()
        return dict(r) if r else None

    def open_count(self, target):
        return self.conn.execute("SELECT COUNT(*) FROM jobs WHERE target=? AND status IN ('dispatching','dispatched','running','ambiguous')",(target,)).fetchone()[0]

    def reserved_since(self, target, snapshot_at):
        # Reserve including succeeded/failed jobs submitted since snapshot: their consumption
        # may not yet appear in billing data, so never silently re-credit them.
        row=self.conn.execute("SELECT COALESCE(SUM(json_extract(definition,'$.estimated_usd')),0) FROM jobs WHERE target=? AND dispatched_at IS NOT NULL AND dispatched_at>=?",(target,snapshot_at)).fetchone()
        return float(row[0] or 0)

    def transition(self, job_id, previous, next_status, *, target=None, budget_as_of=None, details='', remote_run_id=None):
        now=utcnow()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row=self.conn.execute("SELECT status FROM jobs WHERE id=?",(job_id,)).fetchone()
            if not row or row[0]!=previous:
                self.conn.execute("ROLLBACK")
                return False
            if next_status=='dispatching':
                self.conn.execute("UPDATE jobs SET status=?,target=?,dispatched_at=?,budget_as_of=?,details=?,updated_at=? WHERE id=?",(next_status,target,now,budget_as_of,details,now,job_id))
            else:
                self.conn.execute("UPDATE jobs SET status=?,details=?,remote_run_id=COALESCE(?,remote_run_id),updated_at=? WHERE id=?",(next_status,details,remote_run_id,now,job_id))
            self.conn.execute("COMMIT")
            return True
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise

    def account_hold(self, owner_id, now=None):
        """Return only CURRENT UTC billing month holds. Keep prior months for audit."""
        from .billing_period import same_billing_period
        from .models import timestamp
        now=now or datetime.now(timezone.utc)
        row=self.conn.execute("SELECT level,threshold_pct,observed_at FROM quota_account_holds WHERE owner_id=?",(owner_id,)).fetchone()
        if not row or not same_billing_period(timestamp(row["observed_at"]),now):
            return None
        return dict(row)

    def archived_hold(self, owner_id):
        """Read-only historical hold, even if no longer effective this month."""
        row=self.conn.execute("SELECT level,threshold_pct,observed_at FROM quota_account_holds WHERE owner_id=?",(owner_id,)).fetchone()
        return dict(row) if row else None

    def record_quota_alert(self, *, event_id, owner_id, threshold_pct, observed_at):
        """Commit immutable alert + monotonic status in one transaction; duplicate safe."""
        from .alerts import validate_alert_parts
        validate_alert_parts(event_id,owner_id,threshold_pct,observed_at)
        now=utcnow()
        action="hold" if threshold_pct>=85 else "warn"
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            prev=self.conn.execute("SELECT owner_id,threshold_pct,observed_at FROM quota_alerts WHERE event_id=?",(event_id,)).fetchone()
            if prev:
                if tuple(prev)!=(owner_id,threshold_pct,observed_at):
                    raise ConfigError("Alert event ID reused with different content")
                self.conn.execute("COMMIT")
                return "already_ingested"
            self.conn.execute("INSERT INTO quota_alerts(event_id,owner_id,threshold_pct,action,observed_at,ingested_at) VALUES (?,?,?,?,?,?)",
                              (event_id,owner_id,threshold_pct,action,observed_at,now))
            from .billing_period import same_billing_period
            from .models import timestamp
            current=self.conn.execute("SELECT level,threshold_pct,observed_at FROM quota_account_holds WHERE owner_id=?",(owner_id,)).fetchone()
            observation=timestamp(observed_at)
            is_current_month=same_billing_period(observation,datetime.now(timezone.utc))
            effective_current=(current is not None
                              and same_billing_period(timestamp(current["observed_at"]), observation))
            # Preserve the alert in immutable history but NEVER resurrect an
            # obsolete previous-month hold or let it replace a newer record.
            if is_current_month and (
                not current or
                (observed_at>=current["observed_at"] and
                 (not effective_current or current["level"]!="hold" or action=="hold"))):
                self.conn.execute("""INSERT INTO quota_account_holds(owner_id,level,threshold_pct,event_id,observed_at)
                    VALUES (?,?,?,?,?)
                    ON CONFLICT(owner_id) DO UPDATE SET level=excluded.level,
                        threshold_pct=excluded.threshold_pct,event_id=excluded.event_id,
                        observed_at=excluded.observed_at""",(owner_id,action,threshold_pct,event_id,observed_at))
            self.conn.execute("COMMIT")
            return action if is_current_month else "archived_previous_month"
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise

    def acknowledge_new_period(self,owner_id,*,observed_at,verified_budget_available,approved):
        """A missing/bad budget MUST NOT lift an email hold. Never called by email intake."""
        from .models import timestamp
        if not approved or not verified_budget_available:
            raise ConfigError("Explicit operator approval and separately verified new budget are required")
        moment=timestamp(observed_at)
        now=datetime.now(timezone.utc)
        if not -300 <= (now-moment).total_seconds() <= 12*3600:
            raise ConfigError("New budget verification must be fresh")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            prior=self.conn.execute("SELECT observed_at FROM quota_account_holds WHERE owner_id=?",(owner_id,)).fetchone()
            if prior and observed_at<=prior["observed_at"]:
                raise ConfigError("Budget verification must be later than last alert")
            self.conn.execute("DELETE FROM quota_account_holds WHERE owner_id=?",(owner_id,))
            self.conn.execute("COMMIT")
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise

    def mark_alert_source_checked(self):
        """Only call after a complete authenticated private-issue read succeeded."""
        self.conn.execute("""INSERT INTO quota_source_health(source,last_success_utc)
              VALUES ('github_private_issue',?)
              ON CONFLICT(source) DO UPDATE SET last_success_utc=excluded.last_success_utc""",
              (utcnow(),))

    def alert_source_fresh(self, max_age_minutes=60):
        row=self.conn.execute(
            "SELECT last_success_utc FROM quota_source_health WHERE source='github_private_issue'"
        ).fetchone()
        if not row: return False
        from .models import timestamp
        age=(datetime.now(timezone.utc)-timestamp(row[0])).total_seconds()
        return -300<=age<=max_age_minutes*60
