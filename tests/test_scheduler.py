import json, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from quotaflow.models import Account,Job
from quotaflow.db import QueueDB
from quotaflow.scheduler import choose,plan,dispatch_one,sync,budget_fresh
from quotaflow.github_api import GitHubError
from .test_models import A,J

class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=QueueDB(Path(self.tmp.name)/"queue.db");self.addCleanup(self.db.close)
        self.accounts={"alpha":Account.parse(A)}
        self.job=Job.parse(J)
        self.now=datetime.now(timezone.utc)
        self.budgets={"alpha":{"as_of_utc":self.now.isoformat(),"source":"manual","remaining_usd":3.0}}
    def test_fresh(self):self.assertTrue(budget_fresh(self.budgets["alpha"]))
    def test_stale(self):
        x={**self.budgets["alpha"],"as_of_utc":(self.now-timedelta(hours=20)).isoformat()}
        self.assertFalse(budget_fresh(x))
    def test_missing_quota_blocks(self):
        self.assertIsNone(choose(self.job,self.accounts,{},self.db)[0])
    def test_reserve_blocks(self):
        self.assertIsNone(choose(self.job,self.accounts,{"alpha":{**self.budgets["alpha"],"remaining_usd":1.0}},self.db)[0])
    def test_choose_good(self):self.assertEqual(choose(self.job,self.accounts,self.budgets,self.db)[0],"alpha")
    def test_duplicate_enqueue_idempotent(self):
        self.assertEqual(self.db.add(self.job),"queued")
        self.assertEqual(self.db.add(self.job),"already_queued")
    def test_immutable_id_rejects_mutation(self):
        self.db.add(self.job)
        with self.assertRaises(ValueError):self.db.add(Job.parse({**J,"profile":"sample"}))
    def test_dry_run_does_not_call_github(self):
        self.db.add(self.job)
        r=dispatch_one(self.db,self.accounts,self.budgets,approved=False,github_factory=lambda a:1/0)
        self.assertEqual(r["status"],"dry_run")
        self.assertEqual(self.db.get(self.job.id)["status"],"queued")
    def test_dispatch_with_preflight(self):
        self.db.add(self.job)
        events=[]
        class Fake:
            def __init__(self,a):events.append(("init",a.owner))
            def verify(self):events.append(("verify",));return {"verified":True}
            def dispatch(self,job_id,profile):events.append(("dispatch",job_id,profile))
        result=dispatch_one(self.db,self.accounts,self.budgets,approved=True,github_factory=Fake)
        self.assertEqual(result["status"],"dispatched")
        self.assertEqual(events[-1],("dispatch","task1","unit"))
        self.assertEqual(self.db.open_count("alpha"),1)
    def test_ambiguous_no_retry(self):
        self.db.add(self.job)
        class Fake:
            def __init__(self,a):pass
            def verify(self):pass
            def dispatch(self,*args):raise GitHubError("timeout")
        result=dispatch_one(self.db,self.accounts,self.budgets,approved=True,github_factory=Fake)
        self.assertEqual(result["status"],"ambiguous")
        self.assertEqual(dispatch_one(self.db,self.accounts,self.budgets,approved=True,github_factory=Fake)["status"],"no_eligible_queued_jobs")
    def test_running_and_success_sync(self):
        self.db.add(self.job)
        self.db.transition("task1","queued","dispatching",target="alpha",budget_as_of=self.budgets["alpha"]["as_of_utc"])
        self.db.transition("task1","dispatching","dispatched")
        class Fake:
            def __init__(self,a):pass
            def verify(self):pass
            def find_run(self,id):return {"id":10,"display_title":"QuotaFlow task1","status":"completed","conclusion":"success"}
        result=sync(self.db,self.accounts,github_factory=Fake)
        self.assertEqual(result[0]["status"],"success")
        self.assertEqual(self.db.open_count("alpha"),0)
    def test_recent_allocation_deducts(self):
        self.db.add(self.job)
        self.db.transition("task1","queued","dispatching",target="alpha",budget_as_of=self.budgets["alpha"]["as_of_utc"])
        self.db.transition("task1","dispatching","dispatched")
        self.assertGreater(self.db.reserved_since("alpha",self.budgets["alpha"]["as_of_utc"]),.6)
    def test_busy_owner_blocks_second(self):
        self.db.add(self.job)
        self.db.transition("task1","queued","dispatching",target="alpha",budget_as_of=self.budgets["alpha"]["as_of_utc"])
        other=Job.parse({**J,"id":"second"})
        self.assertIsNone(choose(other,self.accounts,self.budgets,self.db)[0])
    def test_missing_profile_blocks(self):
        other=Job.parse({**J,"profile":"unapproved"})
        self.assertIsNone(choose(other,self.accounts,self.budgets,self.db)[0])
    def test_no_ai_share_pretence(self):
        # AI usage is deliberately absent: a GitHub owner budget does not grant Codex credits.
        self.assertFalse(any('codex' in k.lower() for k in self.budgets['alpha']))
