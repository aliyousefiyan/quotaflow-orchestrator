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
