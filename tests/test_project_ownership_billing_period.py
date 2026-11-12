import json
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path

from quotaflow.billing_period import utc_month_start,billing_month,same_billing_period
from quotaflow.db import QueueDB
from quotaflow.models import ConfigError,Account,Job
from quotaflow.scheduler import budget_fresh,choose
from quotaflow.project_registry import load_project_registry,resolve_project,authorize_project_runner,project_home_report

def observed(day):
    return datetime.fromisoformat(day.replace("Z","+00:00"))

def account(alias):
    return Account.parse({"id":alias,"owner":alias,"repository":alias+"/safe-worker",
            "workflow":"quotaflow-worker.yml","ref":"main","token_env":"QF_"+alias.upper(),
            "profiles":["smoke","sample_compute","unit"],"minimum_reserve_usd":.2})

class CalendarBillingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=QueueDB(Path(self.temp.name)/"queue.sqlite3");self.addCleanup(self.db.close)
        self.now=datetime.now(timezone.utc)
    def test_november_starts_at_utc_midnight(self):
        self.assertEqual(utc_month_start(observed("2026-11-30T23:59:59Z")).isoformat(),"2026-11-01T00:00:00+00:00")
    def test_december_is_new_billing_month(self):
        self.assertFalse(same_billing_period(observed("2026-11-30T23:59:59Z"),observed("2026-12-01T00:00:00Z")))
    def test_year_reset(self):
        self.assertEqual(billing_month(observed("2027-01-01T00:00:00Z")),"2027-01")
    def test_leap_day(self):
        self.assertEqual(billing_month(observed("2028-02-29T23:59:59Z")),"2028-02")
        self.assertFalse(same_billing_period(observed("2028-02-29T23:59:59Z"),observed("2028-03-01T00:00:00Z")))
    def test_timezone_conversion_not_local_calendar(self):
        self.assertEqual(billing_month(observed("2026-12-01T01:30:00+03:30")),"2026-11")
    def test_previous_month_hold_is_archived_not_effective(self):
        t=self.now.isoformat().replace("+00:00","Z")
        self.db.record_quota_alert(event_id="1"*64,owner_id="owner_a",threshold_pct=100,observed_at=t)
        self.assertEqual(self.db.account_hold("owner_a")["level"],"hold")
        first_next=utc_month_start(self.now)
        next_month=(first_next.replace(day=28)+timedelta(days=4)).replace(day=1)
        self.assertIsNone(self.db.account_hold("owner_a",now=next_month))
        self.assertEqual(self.db.archived_hold("owner_a")["level"],"hold")
    def test_last_month_email_insert_cannot_hold_current_month(self):
        last=(utc_month_start(self.now)-timedelta(seconds=1)).isoformat().replace("+00:00","Z")
        self.db.record_quota_alert(event_id="2"*64,owner_id="owner_b",threshold_pct=100,observed_at=last)
        self.assertIsNone(self.db.account_hold("owner_b"))
        self.assertIsNone(self.db.archived_hold("owner_b"))
        self.assertEqual(self.db.conn.execute("SELECT count(*) FROM quota_alerts").fetchone()[0],1)
    def test_old_email_does_not_replace_current_month_hold(self):
        now=self.now.isoformat().replace("+00:00","Z")
        past=(utc_month_start(self.now)-timedelta(seconds=1)).isoformat().replace("+00:00","Z")
        self.db.record_quota_alert(event_id="3"*64,owner_id="owner_a",threshold_pct=90,observed_at=now)
        self.db.record_quota_alert(event_id="4"*64,owner_id="owner_a",threshold_pct=100,observed_at=past)
        self.assertEqual(self.db.account_hold("owner_a")["threshold_pct"],90)
    def test_previous_month_budget_is_not_fresh_just_after_midnight(self):
        now=observed("2026-12-01T00:01:00Z")
        old={"as_of_utc":"2026-11-30T23:59:50Z","remaining_usd":100}
        self.assertFalse(budget_fresh(old,now))
        current={**old,"as_of_utc":"2026-12-01T00:00:30Z"}
        self.assertTrue(budget_fresh(current,now))
    def test_no_guessing_budget_after_month_reset(self):
        now=observed("2027-01-01T00:02:00Z")
        self.assertFalse(budget_fresh({"as_of_utc":"2026-12-31T23:59:59Z","remaining_usd":100},now))
        self.assertFalse(budget_fresh({"as_of_utc":"2027-01-01T00:00:00Z","remaining_usd":None},now))
    def test_naive_timezone_refused(self):
        with self.assertRaises(ValueError):utc_month_start(datetime(2026,11,1))


class ProjectHomeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.accounts={x:account(x) for x in ("owner_a","owner_b","owner_c")}
        self.project={"project":"EMA_SDF","aliases":["EMA","SDF"],"home_account":"owner_a",
            "home_repository":"owner_a/ema-private","status":"verified_repository",
            "portable_profiles":[],"notes":"Home for nonportable research"}
        self.proposed={"project":"Whale_Collector","aliases":["Whale"],"home_account":"owner_b",
            "home_repository":None,"status":"proposed_home","portable_profiles":[]}
    def parse(self,projects=None):
        file=self.root/"registry.json"
        file.write_text(json.dumps({"schema":1,"projects":projects or [self.project,self.proposed]}))
        return load_project_registry(file,self.accounts)
    def job(self,project="EMA",profile="unit"):
        return Job.parse({"id":"one","project":project,"profile":profile,"estimated_usd":.5,
            "priority":1,"target_accounts":["owner_a","owner_b","owner_c"],
            "inputs_digest":"1"*64})
    def test_resolve_alias_and_home(self):
        tab=self.parse()
        self.assertEqual(resolve_project(tab,"EMA")["home_account"],"owner_a")
        self.assertEqual(project_home_report(tab,"SDF")["home_repository"],"owner_a/ema-private")
    def test_unknown_project_blocked(self):
        self.assertEqual(authorize_project_runner(self.job("Router"),"owner_a",self.parse()),"unknown_project_blocked")
    def test_only_home_allowed_for_private_job(self):
        t=self.parse()
        self.assertIsNone(authorize_project_runner(self.job(),"owner_a",t))
        self.assertEqual(authorize_project_runner(self.job(),"owner_b",t),"cross_account_private_project_blocked")
    def test_proposed_home_cannot_dispatch(self):
        self.assertEqual(authorize_project_runner(self.job("Whale"),"owner_b",self.parse()),"project_home_not_verified")
    def test_portable_smoke_explicitly_allowed(self):
        data={**self.project,"portable_profiles":["smoke"]}
        t=self.parse([data,self.proposed])
        self.assertIsNone(authorize_project_runner(self.job(profile="smoke"),"owner_c",t))
        self.assertEqual(authorize_project_runner(self.job(profile="unit"),"owner_c",t),"cross_account_private_project_blocked")
    def test_private_repo_owner_mismatch_fails(self):
        with self.assertRaises(ConfigError):self.parse([{**self.project,"home_repository":"owner_c/ema-private"}])
    def test_duplicate_alias_fails(self):
        with self.assertRaises(ConfigError):self.parse([self.project,{**self.proposed,"aliases":["EMA"]}])
    def test_secret_unsafe_field_rejected(self):
        with self.assertRaises(ConfigError):self.parse([{**self.project,"token":"secret"}])
    def test_unknown_home_account_rejected(self):
        with self.assertRaises(ConfigError):self.parse([{**self.project,"home_account":"not_connected"}])
    def test_arbitrary_portability_fails(self):
        with self.assertRaises(ConfigError):self.parse([{**self.project,"portable_profiles":["run_private_strategy"]}])
    def test_proposed_never_portable(self):
        with self.assertRaises(ConfigError):self.parse([{**self.proposed,"portable_profiles":["smoke"]}])
    def test_routing_owner_priority_cannot_override_project_home(self):
        from quotaflow.scheduler import choose
        tab=self.parse()
        with tempfile.TemporaryDirectory() as d:
            db=QueueDB(Path(d)/"queue.sqlite3")
            self.addCleanup(db.close)
            now=datetime.now(timezone.utc).isoformat()
            budgets={x:{"remaining_usd":100,"as_of_utc":now,"source":"manual"} for x in self.accounts}
            job=self.job()
            owner,blocked=choose(job,self.accounts,budgets,db,project_registry=tab,
                                 routing_priority=("owner_c","owner_b","owner_a"))
            # Even with Yahoo first by quota routing, source ownership is fixed.
            self.assertEqual(owner,"owner_a")
            self.assertIn(("owner_c","cross_account_private_project_blocked"),blocked)
            self.assertIn(("owner_b","cross_account_private_project_blocked"),blocked)
