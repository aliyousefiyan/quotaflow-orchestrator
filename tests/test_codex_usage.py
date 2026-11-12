import unittest
from datetime import datetime, timezone, timedelta
from quotaflow.codex_usage import summarize_rate_limits,plan_ai_tasks,CodexLimitError

class CodexBudgetTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime.now(timezone.utc)
        self.budget={"as_of_utc":self.now.isoformat(),"shared_remaining_pct":70}
        self.tasks=[{"id":"t1","project":"EMA","surface":"codex","estimated_pct":10,"description":"Review test-only diff"},
                    {"id":"t2","project":"Router","surface":"work","estimated_pct":20,"description":"Analyze risk docs"}]
    def test_parse_real_like_rate_windows(self):
        raw={"rateLimitsByLimitId":{"codex":{"limitId":"codex","planType":"plus","primary":{"usedPercent":61,"windowDurationMins":300,"resetsAt":1794493510},"secondary":{"usedPercent":48,"windowDurationMins":10080,"resetsAt":1794902777}}}}
        s=summarize_rate_limits(raw)
        self.assertEqual(s["windows"][0]["primary"]["remaining_percent"],39)
        self.assertEqual(s["windows"][0]["secondary"]["remaining_percent"],52)
        self.assertEqual(s["work_shared_monthly_credit"],"unknown_not_inferred")
    def test_legacy_bucket_fallback(self):
        r=summarize_rate_limits({"rateLimits":{"limitId":"codex","primary":{"usedPercent":20}}})
        self.assertEqual(r["windows"][0]["primary"]["remaining_percent"],80)
    def test_invalid_result_fails(self):
        with self.assertRaises(CodexLimitError):summarize_rate_limits(None)
    def test_fresh_budget_requires_manual_approval(self):
        r=plan_ai_tasks(self.tasks,self.budget,now=self.now)
        self.assertEqual(r["tasks"][0]["status"],"manual_agent_approval_required")
        self.assertEqual(r["tasks"][1]["status"],"manual_agent_approval_required")
        self.assertEqual(r["estimated_available_after_planning"],40)
    def test_unknown_budget_blocks_all(self):
        r=plan_ai_tasks(self.tasks,{"as_of_utc":None,"shared_remaining_pct":None},now=self.now)
        self.assertTrue(all(t["status"]=="blocked_shared_credit_unknown" for t in r["tasks"]))
    def test_stale_budget_blocks(self):
        past=(self.now-timedelta(days=1)).isoformat()
        r=plan_ai_tasks(self.tasks,{"as_of_utc":past,"shared_remaining_pct":99},now=self.now)
        self.assertEqual(r["tasks"][0]["status"],"blocked_shared_credit_unknown")
    def test_emergency_reserve(self):
        r=plan_ai_tasks(self.tasks,{"as_of_utc":self.now.isoformat(),"shared_remaining_pct":38},now=self.now)
        self.assertEqual(r["tasks"][0]["status"],"blocked_shared_credit_reserve")
    def test_shared_budget_not_double_allocated(self):
        r=plan_ai_tasks(self.tasks,{"as_of_utc":self.now.isoformat(),"shared_remaining_pct":50},now=self.now)
        self.assertEqual(r["tasks"][0]["status"],"manual_agent_approval_required")
        self.assertEqual(r["tasks"][1]["status"],"blocked_shared_credit_reserve")
    def test_unknown_surface_rejected(self):
        with self.assertRaises(ValueError):
            plan_ai_tasks([{**self.tasks[0],"surface":"github_actions"}],self.budget)
    def test_unknown_fields_rejected(self):
        with self.assertRaises(ValueError):
            plan_ai_tasks([{**self.tasks[0],"command":"curl"}],self.budget)
