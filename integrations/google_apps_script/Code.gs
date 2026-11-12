/**
 * QuotaFlow Gmail watcher — user installs this in their own Google Apps Script.
 * It never runs a GitHub workflow; it only writes signed, hold-only notices
 * into an authorized PRIVATE GitHub issue. Secrets stay in Script Properties.
 *
 * Required Script Properties:
 * QF_OWNER_MAP_JSON = {"account-one":"gmail_a","account-two":"gmail_b"}
 * QF_PRIVATE_REPO   = private-owner/private-repository
 * QF_ISSUE_NUMBER   = existing PRIVATE issue number
 * QF_ISSUES_PAT     = fine-grained token, Issues write on only that repository
 * QF_HMAC_SECRET    = shared signing secret (also in private controller secret)
 * QF_DRY_RUN        = true initially, then false after mailbox validation
 *
 * The Yahoo account is the FINAL backup, never auto-unlocked by this Gmail
 * monitor. The Python controller separately requires verified spendable funds.
 */
function qfProperties_() {
  const p=PropertiesService.getScriptProperties();
  const needed=["QF_OWNER_MAP_JSON","QF_PRIVATE_REPO","QF_ISSUE_NUMBER","QF_ISSUES_PAT","QF_HMAC_SECRET"];
  const cfg={};
  for (const k of needed) {
    cfg[k]=p.getProperty(k) || "";
    if (!cfg[k]) throw new Error("Missing private QuotaFlow property "+k);
  }
  cfg.owners=JSON.parse(cfg.QF_OWNER_MAP_JSON);
  if (Object.keys(cfg.owners).length!==2) throw new Error("Exactly two Gmail owners must be mapped");
  for(const [name,alias] of Object.entries(cfg.owners)) {
    if(!/^[A-Za-z0-9_.-]{1,64}$/.test(name)||!/^[A-Za-z0-9_.-]{1,64}$/.test(alias))
      throw new Error("Unsafe owner alias");
  }
  if(!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(cfg.QF_PRIVATE_REPO)||
     !/^[1-9]\d*$/.test(cfg.QF_ISSUE_NUMBER)) throw new Error("Unsafe private issue locator");
  cfg.dryRun=p.getProperty("QF_DRY_RUN")!=="false";
  return cfg;
}
function qfHex_(bytes) {
  return bytes.map(b=>("0"+(b&255).toString(16)).slice(-2)).join("");
}
function qfSha_(text) {
  return qfHex_(Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,text,Utilities.Charset.UTF_8));
}
function qfHmac_(item,key) {
  const canonical=[item.event_id,item.owner_id,item.product,String(item.threshold_pct),item.observed_at_utc].join("|");
  return qfHex_(Utilities.computeHmacSha256Signature(canonical,key,Utilities.Charset.UTF_8));
}
function qfSender_(from) {
  const m=String(from||"").match(/([A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+))\s*>?\s*$/);
  return m?m[2].toLowerCase():null;
}
function qfAuthenticated_(msg) {
  const auth=String(msg.getHeader("Authentication-Results")||"");
  // Require Github-aligned DKIM. Missing/forwarded/ambiguous headers go to review.
  return /\bdkim=pass\b[^;\r\n]{0,160}\bheader\.(?:d=github\.com|i=@github\.com)\b/i.test(auth);
}
function qfOwner_(text,map) {
  const matches=[];
  for(const name of Object.keys(map)) {
    const escaped=name.split("").map(ch=>/[A-Za-z0-9_-]/.test(ch)?ch:"\\"+ch).join("");
    if(new RegExp("(^|[^A-Za-z0-9_.-])"+escaped+"([^A-Za-z0-9_.-]|$)","i").test(text))
      matches.push(map[name]);
  }
  // If an email mentions both accounts, DO NOT guess.
  return matches.length===1?matches[0]:null;
}
function qfParse_(msg,owners) {
  if(qfSender_(msg.getFrom())!=="github.com"||!qfAuthenticated_(msg)) return null;
  const subject=String(msg.getSubject()||"");
  const body=String(msg.getPlainBody()||"").slice(0,18000);
  const text=subject+"\n"+body;
  if(!/github\s+actions?\b|\bactions?\s+(minutes|compute|usage|billing|budget)\b/i.test(text)) return null;
  if(!/\b(used|usage|included|budget|reached|exceeded|threshold|consumed|spend|spent)\b/i.test(text)) return null;
  const subjectPct=[...subject.matchAll(/\b(75|85|90|100)\s*%/g)].map(m=>Number(m[1]));
  const bodyPct=[...body.matchAll(/(?:used|reached|exceeded|consumed|at)\s+(?:approximately\s+)?(75|85|90|100)\s*%/ig)].map(m=>Number(m[1]));
  const percents=[...new Set(subjectPct.length?subjectPct:bodyPct)];
  if(percents.length!==1) return null;
  const owner=qfOwner_(text,owners);
  if(!owner) return null;
  return {schema:1,source:"gmail_app_script",event_id:qfSha_(msg.getId()+"|"+owner),
          owner_id:owner,product:"github_actions",threshold_pct:percents[0],
          observed_at_utc:msg.getDate().toISOString(),owner_identity_verified:true};
}
function qfComment_(cfg,event) {
  const payload={...event,signature:qfHmac_(event,cfg.QF_HMAC_SECRET)};
  const endpoint="https://api.github.com/repos/"+cfg.QF_PRIVATE_REPO+"/issues/"+
                 cfg.QF_ISSUE_NUMBER+"/comments";
  const response=UrlFetchApp.fetch(endpoint,{method:"post",
    headers:{"Authorization":"Bearer "+cfg.QF_ISSUES_PAT,
             "Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"},
    contentType:"application/json",payload:JSON.stringify({
      body:"QUOTAFLOW_ACTIONS_ALERT_V1\n"+JSON.stringify(payload)}),
    muteHttpExceptions:true});
  if(response.getResponseCode()!==201)
    throw new Error("Private GitHub issue receipt failed HTTP "+response.getResponseCode());
}
function installQuotaFlowMonitor() {
  qfProperties_();
  if(ScriptApp.getProjectTriggers().some(t=>t.getHandlerFunction()==="pollGitHubQuotaAlerts")) return;
  ScriptApp.newTrigger("pollGitHubQuotaAlerts").timeBased().everyMinutes(15).create();
}
function pollGitHubQuotaAlerts() {
  const lock=LockService.getScriptLock();
  if(!lock.tryLock(20000)) return;
  try {
    const cfg=qfProperties_(), props=PropertiesService.getScriptProperties();
    const processed=JSON.parse(props.getProperty("QF_PROCESSED_IDS_JSON")||"[]");
    const seen=new Set(processed);
    let scanned=0,accepted=0,rejected=0;
    const threads=GmailApp.search("from:(github.com) newer_than:7d",0,60);
    for(const thread of threads) {
      for(const msg of thread.getMessages()) {
        if(++scanned>120) break;
        const id=msg.getId();
        if(seen.has(id)) continue;
        const event=qfParse_(msg,cfg.owners);
        if(!event){rejected++;continue;}
        if(!cfg.dryRun) {
          qfComment_(cfg,event);
          processed.push(id);
          seen.add(id);
        }
        accepted++;
      }
      if(scanned>120) break;
    }
    if(!cfg.dryRun) props.setProperty("QF_PROCESSED_IDS_JSON",JSON.stringify(processed.slice(-450)));
    console.log(JSON.stringify({dry_run:cfg.dryRun,scanned,verified_matches:accepted,manual_review:rejected}));
  } finally {
    lock.releaseLock();
  }
}
