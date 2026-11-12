import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from quotaflow.alerts import load_alert, ingest_verified_alert, load_routing, preview_routing
from quotaflow.db import QueueDB
from quotaflow.models import Account, Job, ConfigError
from quotaflow.scheduler import choose, dispatch_one


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")


class EmailAlertRoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db=QueueDB(Path(self.tmp.name)/"q.sqlite3")
        self.addCleanup(self.db.close)
        self.accounts={}
        for id in ("gmail_a","gmail_b","yahoo"):
            self.accounts[id]=Account.parse({
                "id":id,"owner":id,"repository":id+"/worker",
                "workflow":"quotaflow-worker.yml","ref":"main","token_env":"QF_"+id.upper(),
                "profiles":["smoke"],"minimum_reserve_usd":0.5})
        self.budgets={id:{"remaining_usd":5,"source":"manual","as_of_utc":utc_now()} for id in self.accounts}
        self.job=Job.parse({
            "id":"job1","project":"QuotaFlow","profile":"smoke","estimated_usd":0.3,
            "priority":1,"target_accounts":["yahoo","gmail_b","gmail_a"],
            "inputs_digest":"1"*64})
        self.priority=("gmail_a","gmail_b","yahoo")

    def event(self,owner,pct,seed="1",time=None):
        return {"schema":1,"source":"gmail_app_script","event_id":hashlib.sha256(seed.encode()).hexdigest(),
                "owner_id":owner,"product":"github_actions","threshold_pct":pct,
                "observed_at_utc":time or utc_now(),"owner_identity_verified":True}

    def ingest(self,event):
        f=Path(self.tmp.name)/"alert.json"
        f.write_text(json.dumps(event),encoding="utf-8")
        return ingest_verified_alert(self.db,load_alert(f),self.accounts)

    def test_prioritize_gmail_a_despite_more_balance_on_b(self):
        self.budgets["gmail_b"]["remaining_usd"]=20
        self.assertEqual(choose(self.job,self.accounts,self.budgets,self.db,self.priority)[0],"gmail_a")

    def test_75_warn_keeps_first_account(self):
        self.assertEqual(self.ingest(self.event("gmail_a",75)),"warn")
        self.assertEqual(choose(self.job,self.accounts,self.budgets,self.db,self.priority)[0],"gmail_a")

    def test_85_holds_only_first_account(self):
        self.assertEqual(self.ingest(self.event("gmail_a",85)),"hold")
        self.assertEqual(choose(self.job,self.accounts,self.budgets,self.db,self.priority)[0],"gmail_b")

    def test_90_holds_second_yahoo_last(self):
        self.ingest(self.event("gmail_a",90,"1"))
        self.ingest(self.event("gmail_b",90,"2"))
        self.assertEqual(choose(self.job,self.accounts,self.budgets,self.db,self.priority)[0],"yahoo")

    def test_yahoo_blocks_when_budget_unknown(self):
        self.ingest(self.event("gmail_a",90,"1"))
        self.ingest(self.event("gmail_b",90,"2"))
        self.budgets["yahoo"]["remaining_usd"]=None
        chosen,reasons=choose(self.job,self.accounts,self.budgets,self.db,self.priority)
        self.assertIsNone(chosen)
        self.assertIn(("yahoo","budget_missing_or_stale"),reasons)

    def test_no_auto_resume_on_later_75_email(self):
        self.ingest(self.event("gmail_a",90,"1"))
        self.ingest(self.event("gmail_a",75,"2"))
        self.assertEqual(self.db.account_hold("gmail_a")["level"],"hold")

    def test_duplicate_email_idempotent(self):
        e=self.event("gmail_a",90)
        self.assertEqual(self.ingest(e),"hold")
        self.assertEqual(self.ingest(e),"already_ingested")

    def test_duplicate_id_conflict_rejected(self):
        e=self.event("gmail_a",90)
        self.ingest(e)
        with self.assertRaises(ConfigError):
            self.ingest({**e,"threshold_pct":75})

    def test_bad_sender_provenance_marker_rejected(self):
        e=self.event("gmail_a",90)
        for v in ({**e,"owner_identity_verified":False},{**e,"source":"forwarded_unverified"},
                  {**e,"product":"copilot"}):
            f=Path(self.tmp.name)/"evt.json"
            f.write_text(json.dumps(v),encoding="utf-8")
            with self.assertRaises(ConfigError):load_alert(f)

    def test_unknown_owner_rejected(self):
        with self.assertRaises(ConfigError):
            self.ingest(self.event("unmapped_gmail_user",90))

    def test_manual_resume_requires_new_verification(self):
        self.ingest(self.event("gmail_a",90))
        with self.assertRaises(ConfigError):
            self.db.acknowledge_new_period("gmail_a",observed_at=utc_now(),
                                           verified_budget_available=False,approved=True)
        self.assertEqual(self.db.account_hold("gmail_a")["level"],"hold")

    def test_explicit_budget_resets_hold(self):
        self.ingest(self.event("gmail_a",90,"x",time=(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat().replace("+00:00","Z")))
        self.db.acknowledge_new_period("gmail_a",observed_at=utc_now(),verified_budget_available=True,approved=True)
        self.assertIsNone(self.db.account_hold("gmail_a"))

    def test_routing_order_yahoo_must_be_last(self):
        f=Path(self.tmp.name)/"routing.json"
        f.write_text(json.dumps({"schema":1,"priority":["gmail_a","gmail_b","yahoo"],
                                "yahoo_backup":"yahoo","yahoo_last":True}))
        self.assertEqual(load_routing(f,self.accounts),self.priority)
        f.write_text(json.dumps({"schema":1,"priority":["yahoo","gmail_a","gmail_b"],
                                "yahoo_backup":"yahoo","yahoo_last":True}))
        with self.assertRaises(ConfigError):load_routing(f,self.accounts)

    def test_dispatch_dry_run_observes_hold(self):
        self.db.add(self.job)
        self.ingest(self.event("gmail_a",90))
        result=dispatch_one(self.db,self.accounts,self.budgets,approved=False,
                            routing_priority=self.priority,github_factory=lambda x:1/0)
        self.assertEqual(result["plan"][0]["suggested_owner"],"gmail_b")

    def test_preview_status_shows_accounts_without_private_data(self):
        self.ingest(self.event("gmail_a",90))
        rows=preview_routing(self.db,self.accounts,self.budgets,self.priority)
        self.assertEqual(rows[0]["status"],"held_by_email")
        self.assertEqual(rows[-1]["position"],3)


if __name__=="__main__":
    unittest.main()
