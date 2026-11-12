import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from quotaflow.db import QueueDB
from quotaflow.issue_alerts import MARKER, import_issue_comments, verify_comment_body, sign_for_tests_only
from quotaflow.models import ConfigError

KEY="this-is-a-private-test-only-very-long-key-that-is-not-a-real-secret"
def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")

def evt(owner="gmail_a", threshold=90):
    x={"schema":1,"source":"gmail_app_script","event_id":hashlib.sha256(b"test-gmail-message-1").hexdigest(),
       "owner_id":owner,"product":"github_actions","threshold_pct":threshold,
       "observed_at_utc":now(),"owner_identity_verified":True}
    x["signature"]=sign_for_tests_only(x,KEY)
    return x

def comment(x):
    return {"body":MARKER+json.dumps(x,separators=(",",":"))}

class SignedIssueAlertTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db=QueueDB(Path(self.temp.name)/"queue.sqlite3")
        self.addCleanup(self.db.close)
        self.owners={"gmail_a","gmail_b","yahoo"}
    def test_valid_verified_comment_holds_owner(self):
        results=import_issue_comments(self.db,[comment(evt())],KEY,self.owners)
        self.assertEqual(results["accepted"],1)
        self.assertEqual(self.db.account_hold("gmail_a")["level"],"hold")
        self.assertIsNone(self.db.account_hold("gmail_b"))
    def test_duplicate_signed_comment_is_idempotent(self):
        x=comment(evt())
        result=import_issue_comments(self.db,[x,x],KEY,self.owners)
        self.assertEqual(result["accepted"],1)
        self.assertEqual(result["duplicates"],1)
    def test_tampered_owner_is_rejected(self):
        x=evt()
        x["owner_id"]="yahoo"
        self.assertIsNone(verify_comment_body(comment(x)["body"],KEY,self.owners))
    def test_tampered_percent_is_rejected(self):
        x=evt()
        x["threshold_pct"]=75
        self.assertIsNone(verify_comment_body(comment(x)["body"],KEY,self.owners))
    def test_forged_comment_without_signature_is_rejected(self):
        x=evt()
        x["signature"]="0"*64
        self.assertIsNone(verify_comment_body(comment(x)["body"],KEY,self.owners))
    def test_non_actions_alert_rejected(self):
        x=evt()
        x["product"]="copilot"
        x["signature"]=sign_for_tests_only(x,KEY)
        self.assertIsNone(verify_comment_body(comment(x)["body"],KEY,self.owners))
    def test_unknown_account_is_rejected(self):
        x=evt(owner="unmapped")
        self.assertIsNone(verify_comment_body(comment(x)["body"],KEY,self.owners))
    def test_unsigned_regular_comments_ignored(self):
        r=import_issue_comments(self.db,[{"body":"please run my shell"}],KEY,self.owners)
        self.assertEqual(r["ignored_or_unverified"],1)
    def test_missing_shared_secret_does_not_import(self):
        with self.assertRaises(ConfigError):
            import_issue_comments(self.db,[comment(evt())],"",self.owners)
    def test_hmac_is_independent_of_json_key_order(self):
        x=evt()
        y=dict(reversed(list(x.items())))
        self.assertIsNotNone(verify_comment_body(comment(y)["body"],KEY,self.owners))
    def test_signed_alert_cannot_clear_existing_hold(self):
        x=evt(threshold=90)
        import_issue_comments(self.db,[comment(x)],KEY,self.owners)
        y=evt(threshold=75)
        y["event_id"]=hashlib.sha256(b"another-mail").hexdigest()
        y["signature"]=sign_for_tests_only(y,KEY)
        import_issue_comments(self.db,[comment(y)],KEY,self.owners)
        self.assertEqual(self.db.account_hold("gmail_a")["level"],"hold")


if __name__=="__main__":
    unittest.main()
