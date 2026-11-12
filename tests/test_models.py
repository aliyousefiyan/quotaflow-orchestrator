import json, tempfile, unittest
from pathlib import Path
from quotaflow.models import Account, ConfigError, Job, load_accounts, load_budgets, timestamp

A={"id":"alpha","owner":"alpha","repository":"alpha/worker","workflow":"worker.yml","ref":"main","token_env":"GH_ALPHA_TOKEN","profiles":["unit","sample"],"minimum_reserve_usd":0.5}
J={"id":"task1","project":"EMA","profile":"unit","estimated_usd":0.7,"priority":1,"target_accounts":["alpha"],"inputs_digest":"0"*64}

class ModelsTests(unittest.TestCase):
    def test_good_account(self): self.assertEqual(Account.parse(A).owner,"alpha")
    def test_cross_account_repo_rejected(self):
        with self.assertRaises(ConfigError): Account.parse({**A,"repository":"beta/worker"})
    def test_bad_env_rejected(self):
        with self.assertRaises(ConfigError): Account.parse({**A,"token_env":"../../token"})
    def test_unknown_account_field_rejected(self):
        with self.assertRaises(ConfigError): Account.parse({**A,"shell":"curl private"})
    def test_empty_profiles_rejected(self):
        with self.assertRaises(ConfigError): Account.parse({**A,"profiles":[]})
    def test_self_repo_mode_forbids_private_budget_bypass(self):
        with self.assertRaises(ConfigError):
            Account.parse({**A,"github_actions_self_token":True})
        with self.assertRaises(ConfigError):
            Account.parse({**A,"github_actions_self_token":"true","public_standard_runner":True})
    def test_self_repo_mode_explicit_public_only(self):
        a=Account.parse({**A,"public_standard_runner":True,"github_actions_self_token":True})
        self.assertTrue(a.github_actions_self_token)
    def test_good_job(self): self.assertEqual(Job.parse(J).profile,"unit")
    def test_unknown_job_field_rejected(self):
        with self.assertRaises(ConfigError): Job.parse({**J,"shell":"rm -rf /"})
    def test_missing_digest_rejected(self):
        with self.assertRaises(ConfigError): Job.parse({**J,"inputs_digest":"unknown"})
    def test_negative_cost_rejected(self):
        with self.assertRaises(ConfigError): Job.parse({**J,"estimated_usd":-1})
    def test_duplicate_targets_rejected(self):
        with self.assertRaises(ConfigError): Job.parse({**J,"target_accounts":["alpha","alpha"]})
    def test_naive_budget_time_rejected(self):
        with self.assertRaises(ConfigError): timestamp("2026-11-12T12:00:00")
    def test_load_files(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"a.json";p.write_text(json.dumps({"schema":1,"accounts":[A]}))
            self.assertIn("alpha",load_accounts(p))
            b=Path(d)/"b.json";b.write_text(json.dumps({"schema":1,"accounts":{"alpha":{"as_of_utc":None,"source":"manual","remaining_usd":None}}}))
            self.assertIsNone(load_budgets(b)["alpha"]["remaining_usd"])
