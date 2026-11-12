// Offline Apps Script parser tests. No Gmail account, token, network or GitHub API.
"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const crypto=require("node:crypto");
const code=fs.readFileSync("integrations/google_apps_script/Code.gs","utf8");
const sandbox={
  console:{log(){}},
  Utilities:{
    DigestAlgorithm:{SHA_256:"SHA256"},
    Charset:{UTF_8:"UTF-8"},
    computeDigest(_,text){return Array.from(crypto.createHash("sha256").update(text).digest());},
    computeHmacSha256Signature(text,key){return Array.from(crypto.createHmac("sha256",key).update(text).digest());}
  }
};
vm.createContext(sandbox);
vm.runInContext(code,sandbox,{timeout:2000,filename:"Code.gs"});
const owners={"account-one":"gmail_a","account-two":"gmail_b"};
function message({subject="GitHub Actions usage reached 90%",body="For account-one: You have used 90% of your GitHub Actions minutes allowance.",
sender="GitHub <billing@github.com>",
auth="mx.google.com; dkim=pass header.d=github.com; spf=pass",
id="gmail-message-123"}={}){
  return {getSubject(){return subject;},getPlainBody(){return body;},
          getFrom(){return sender;},getHeader(key){return key==="Authentication-Results"?auth:"";},
          getId(){return id;},getDate(){return new Date("2026-11-12T12:30:00Z");}};
}
function parsed(opts){return sandbox.qfParse_(message(opts),owners)}
assert.equal(parsed({}).owner_id,"gmail_a");
assert.equal(parsed({}).threshold_pct,90);
assert.equal(parsed({body:"For account-two: You have used 90% of your GitHub Actions minutes allowance."}).owner_id,"gmail_b");
assert.equal(parsed({body:"Both account-one and account-two reached 90% of GitHub Actions minutes."}),null);
assert.equal(parsed({sender:"Spammer <alerts@github.com.evil.invalid>"}),null);
assert.equal(parsed({auth:"dkim=fail header.d=github.com"}),null);
assert.equal(parsed({auth:"spf=pass header.from=github.com; dkim=pass header.d=attacker.invalid"}),null);
assert.equal(parsed({subject:"GitHub Actions storage usage reached 90%"}),null);
assert.equal(parsed({subject:"GitHub Actions minutes reached 75%",body:"For account-one: You have used 75% of your Actions minutes."}).threshold_pct,75);
assert.equal(parsed({body:"For unknown-user: You have used 90% of GitHub Actions minutes."}),null);
assert.equal(parsed({subject:"Copilot budget reached 90%",body:"For account-one: Copilot usage at 90%."}),null);
assert.equal(parsed({subject:"GitHub Actions usage alert",body:"For account-one: You have used 90% of GitHub Actions minutes."}).owner_id,"gmail_a");
assert.match(parsed({}).event_id,/^[0-9a-f]{64}$/);
assert.equal(sandbox.qfOwner_("account-one account-two",owners),null);
console.log("Gmail Apps Script parser offline: 14 assertions PASS");
