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

// Gmail API READONLY backend tests: no GmailApp, no real network, no credentials.
const manifest=JSON.parse(fs.readFileSync("integrations/google_apps_script/appsscript.json","utf8"));
assert.deepEqual(manifest.oauthScopes,[
  "https://www.googleapis.com/auth/gmail.readonly",
  "https://www.googleapis.com/auth/script.external_request",
  "https://www.googleapis.com/auth/script.scriptapp"
]);
assert.equal(/\bGmailApp\s*\./.test(code),false);
const b64url=txt=>Buffer.from(txt,"utf8").toString("base64url");
const payload={
  id:"a1b2c3d4e5f6",
  internalDate:String(Date.parse("2026-11-12T12:30:00Z")),
  payload:{
    mimeType:"multipart/alternative",
    headers:[
      {name:"From",value:"GitHub <billing@github.com>"},
      {name:"Subject",value:"GitHub Actions usage reached 90%"},
      {name:"Authentication-Results",value:"mx.google.com; dkim=pass header.d=github.com; spf=pass"}
    ],
    parts:[
      {mimeType:"text/plain",body:{data:b64url("For account-one: You have used 90% of your GitHub Actions minutes allowance.")}},
      {mimeType:"text/html",body:{data:b64url("<b>Not used</b>")}}
    ]
  }
};
sandbox.Utilities.newBlob=(bytes)=>({getDataAsString:()=>Buffer.from(bytes).toString("utf8")});
sandbox.Utilities.base64DecodeWebSafe=(data)=>Array.from(Buffer.from(data,"base64url"));
sandbox.ScriptApp={getOAuthToken:()=>"fake-readonly-token"};
let issuedRequests=[];
sandbox.UrlFetchApp={fetch:(url,options)=>{
  issuedRequests.push({url,method:options.method});
  assert.ok(url.startsWith("https://gmail.googleapis.com/gmail/v1/users/me/messages"));
  assert.equal(options.method,"get");
  assert.equal(options.headers.Authorization,"Bearer fake-readonly-token");
  const data=url.includes("?format=full")?payload:{messages:[{id:payload.id}]};
  return {getResponseCode:()=>200,getContentText:()=>JSON.stringify(data)};
}};
const ids=sandbox.qfListMessageIds_();
assert.deepEqual(Array.from(ids),[payload.id]);
const loaded=sandbox.qfMessageFromApi_(sandbox.qfGmailApi_("/"+payload.id+"?format=full"));
assert.equal(loaded.getFrom(),"GitHub <billing@github.com>");
assert.equal(loaded.getSubject(),"GitHub Actions usage reached 90%");
assert.equal(loaded.getDate().toISOString(),"2026-11-12T12:30:00.000Z");
const event=sandbox.qfParse_(loaded,owners);
assert.equal(event.owner_id,"gmail_a");
assert.equal(event.threshold_pct,90);
assert.equal(issuedRequests.length,2);
assert.equal(issuedRequests.some(x=>x.method!=="get"),false);
// Full-mail scope cannot be silently reintroduced via manifest changes.
assert.equal(manifest.oauthScopes.includes("https://mail.google.com/"),false);
assert.equal(manifest.oauthScopes.includes("https://www.googleapis.com/auth/gmail.modify"),false);
assert.equal(manifest.oauthScopes.includes("https://www.googleapis.com/auth/gmail.send"),false);
console.log("Gmail REST readonly backend: 13 assertions PASS");


// Exact real-world GitHub Actions included-minutes email SUBJECT supplied
// by the operator, with synthetic sender/auth and without any private body.
const twoAccounts={"aliyousefiyan":"owner_a","aliyousefiyan70-code":"owner_b"};
const realSubject="[GitHub] You have used 100% of the Actions minutes included for the aliyousefiyan account";
const exactSample=message({
  subject:realSubject,
  body:"",
  sender:"GitHub <billing@github.com>",
  auth:"mx.google.com; dkim=pass header.d=github.com;"
});
assert.equal(sandbox.qfParse_(exactSample,twoAccounts).owner_id,"owner_a");
assert.equal(sandbox.qfParse_(exactSample,twoAccounts).threshold_pct,100);
assert.equal(sandbox.qfDiagnosticReason_(exactSample,twoAccounts),"recognized_candidate");
assert.equal(sandbox.qfDiagnosticReason_(message({subject:realSubject,body:"",auth:""}),twoAccounts),"authentication_header_missing");
assert.equal(sandbox.qfDiagnosticReason_(message({subject:realSubject,body:"",auth:"dkim=fail header.d=github.com"}),twoAccounts),"github_dkim_unverified");
assert.equal(sandbox.qfDiagnosticReason_(message({subject:realSubject,body:"",sender:"bad@spoof.invalid"}),twoAccounts),"sender_domain_unverified");
assert.equal(sandbox.qfDiagnosticReason_(message({
  subject:"[GitHub] You have used 100% of the Actions minutes included for the aliyousefiyan70-code account",body:""
}),twoAccounts),"recognized_candidate");
assert.equal(sandbox.qfParse_(message({
  subject:"[GitHub] You have used 100% of the Actions minutes included for the aliyousefiyan70-code account",body:""
}),twoAccounts).owner_id,"owner_b");
// Bounded diagnostic read-only mode may not trigger any private GitHub writes.
let noWriteLogged="";
sandbox.PropertiesService={getScriptProperties:()=>({
  getProperty:(name)=>({
    QF_DRY_RUN:"true",
    QF_OWNER_MAP_JSON:JSON.stringify(twoAccounts)
  })[name]||""
})};
sandbox.console.log=(item)=>{noWriteLogged=String(item)};
sandbox.diagnoseQuotaFlowAlerts();
const diagnostic=JSON.parse(noWriteLogged);
assert.equal(diagnostic.mode,"historic_readonly");
assert.equal(diagnostic.lookback_days,90);
assert.equal(diagnostic.no_remote_writes,true);
assert.equal(issuedRequests.every(x=>x.method==="get"),true);
assert.equal(diagnostic.scanned,1);
assert.equal(Object.values(diagnostic.reason_counts).reduce((x,y)=>x+y,0),1);
assert.equal(Object.keys(diagnostic).includes("subject"),false);
console.log("Real 100% subject + bounded privacy-safe Gmail diagnosis: 14 assertions PASS");


