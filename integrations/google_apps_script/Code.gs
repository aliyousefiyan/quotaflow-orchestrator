/**
 * QuotaFlow Gmail watcher — OAuth Gmail API READ-ONLY; no full-access mail service.
 * Requires EXACT manifest scopes: gmail.readonly + script.external_request + script.scriptapp.
 * It cannot send, modify or delete messages with this OAuth token.
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
  const cfg={dryRun:p.getProperty("QF_DRY_RUN")!=="false"};
  cfg.QF_OWNER_MAP_JSON=p.getProperty("QF_OWNER_MAP_JSON")||"";
  if(!cfg.QF_OWNER_MAP_JSON) throw new Error("Gmail owner mapping missing");
  // Dry-run intentionally needs NO GitHub token and NO shared HMAC secret.
  const needed=["QF_PRIVATE_REPO","QF_ISSUE_NUMBER","QF_ISSUES_PAT","QF_HMAC_SECRET"];
  for (const k of needed) {
    cfg[k]=p.getProperty(k) || "";
    if(!cfg.dryRun&&!cfg[k]) throw new Error("Missing private QuotaFlow property "+k);
  }
  cfg.owners=JSON.parse(cfg.QF_OWNER_MAP_JSON);
  if (Object.keys(cfg.owners).length!==2) throw new Error("Exactly two Gmail owners must be mapped");
  for(const [name,alias] of Object.entries(cfg.owners)) {
    if(!/^[A-Za-z0-9_.-]{1,64}$/.test(name)||!/^[A-Za-z0-9_.-]{1,64}$/.test(alias))
      throw new Error("Unsafe owner alias");
  }
  if(!cfg.dryRun&&(!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(cfg.QF_PRIVATE_REPO)||
     !/^[1-9]\d*$/.test(cfg.QF_ISSUE_NUMBER))) throw new Error("Unsafe private issue locator");
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
  if(/\b(storage|artifact storage|registry|packages|codespaces|copilot)\b/i.test(subject)) return null;
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
/**
 * Safe reject-reason categories for local investigation. Never log subject,
 * sender address, headers, body, message ID or actual GitHub login.
 * This is only a diagnosis; no security check is bypassed.
 */
function qfDiagnosticReason_(msg,owners) {
  if(qfSender_(msg.getFrom())!=="github.com") return "sender_domain_unverified";
  if(!String(msg.getHeader("Authentication-Results")||""))
    return "authentication_header_missing";
  if(!qfAuthenticated_(msg)) return "github_dkim_unverified";
  const subject=String(msg.getSubject()||"");
  const body=String(msg.getPlainBody()||"").slice(0,18000);
  const text=subject+"\n"+body;
  if(/\b(storage|artifact storage|registry|packages|codespaces|copilot)\b/i.test(subject))
    return "unrelated_billing_product";
  if(!/github\s+actions?\b|\bactions?\s+(minutes|compute|usage|billing|budget)\b/i.test(text))
    return "actions_not_mentioned";
  if(!/\b(used|usage|included|budget|reached|exceeded|threshold|consumed|spend|spent)\b/i.test(text))
    return "no_usage_language";
  const subj=[...subject.matchAll(/\b(75|85|90|100)\s*%/g)].map(m=>Number(m[1]));
  const rest=[...body.matchAll(/(?:used|reached|exceeded|consumed|at)\s+(?:approximately\s+)?(75|85|90|100)\s*%/ig)].map(m=>Number(m[1]));
  if([...new Set(subj.length?subj:rest)].length!==1) return "threshold_missing_or_ambiguous";
  if(!qfOwner_(text,owners)) return "account_missing_or_ambiguous";
  return "recognized_candidate";
}

/**
 * Run manually ONLY with QF_DRY_RUN=true. Diagnose the CURRENT
 * calendar billing month (starting first day 00:00 UTC), not a rolling
 * 7/30/90-day lookback. No email details, logins, content or secrets
 * are printed. NO GitHub writes.
 */
function diagnoseQuotaFlowAlerts() {
  const cfg=qfProperties_();
  if(!cfg.dryRun) throw new Error("Historical diagnostics forbidden outside dry run");
  const ids=qfListMessageIds_(true);
  const reasons={};
  for(const id of ids) {
    const msg=qfMessageFromApi_(qfGmailApi_("/"+encodeURIComponent(id)+"?format=full"));
    const reason=qfDiagnosticReason_(msg,cfg.owners);
    reasons[reason]=(reasons[reason]||0)+1;
  }
  const billing=qfCalendarMonthUtc_();
  console.log(JSON.stringify({mode:"current_calendar_month_readonly",
      billing_period_start_utc:billing.startUtc,
      billing_checked_through_utc:billing.nowUtc,
      scanned:ids.length,reason_counts:reasons,no_remote_writes:true}));
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

/**
 * Gmail REST API integration with a scope-limited Apps Script OAuth token.
 * API path is always under users/me/messages and methods are GET only.
 * The full-access built-in mail service is intentionally not invoked.
 */
function qfCalendarMonthUtc_(reference) {
  const now=reference===undefined?new Date():new Date(reference);
  if(Number.isNaN(now.getTime()))throw new Error("Invalid UTC reference time");
  // This is GitHub's metered billing month: UTC 00:00 on calendar day 1.
  // Query using epoch seconds: Gmail's YYYY/MM/DD form defaults to PST.
  const first=new Date(Date.UTC(now.getUTCFullYear(),now.getUTCMonth(),1));
  return {
    startUtc:first.toISOString(),
    startEpochSeconds:Math.floor(first.getTime()/1000),
    nowUtc:now.toISOString()
  };
}
function qfMonthSearch_(diagnostic,reference) {
  const billing=qfCalendarMonthUtc_(reference);
  // Gmail 'after:' is exclusive: subtract a second to include 00:00:00 UTC.
  const subject=diagnostic?' subject:"Actions minutes"':"";
  // No rolling window, and no future messages are in the mailbox at query time.
  return "from:(github.com)"+subject+
      " after:"+String(billing.startEpochSeconds-1);
}
function qfGmailApi_(suffix) {
  const allowedList="?maxResults=60&q="+encodeURIComponent(qfMonthSearch_(false));
  const allowedHistorical="?maxResults=60&q="+encodeURIComponent(qfMonthSearch_(true));
  if(typeof suffix!=="string" ||
     !(suffix===allowedList || suffix===allowedHistorical || /^\/[A-Za-z0-9_-]{1,200}\?format=full$/.test(suffix)))
    throw new Error("Unsafe Gmail API resource path");
  const url="https://gmail.googleapis.com/gmail/v1/users/me/messages"+suffix;
  const response=UrlFetchApp.fetch(url,{
    method:"get",headers:{"Authorization":"Bearer "+ScriptApp.getOAuthToken(),
                           "Accept":"application/json"},
    muteHttpExceptions:true});
  if(response.getResponseCode()!==200)
    throw new Error("Gmail read-only API status "+response.getResponseCode());
  const raw=JSON.parse(response.getContentText());
  if(!raw || typeof raw!=="object" || Array.isArray(raw))
    throw new Error("Invalid Gmail API JSON response");
  return raw;
}
function qfListMessageIds_(diagnosticReadOnly) {
  // Both monitoring and diagnosis scan from day 1 of the CURRENT UTC month.
  // Diagnosis NEVER sends receipts or alters the processed-message ledger.
  const q=encodeURIComponent(qfMonthSearch_(diagnosticReadOnly===true));
  const response=qfGmailApi_("?maxResults=60&q="+q);
  if(response.nextPageToken)
    throw new Error("Gmail result exceeds safe 60-message window; manual review");
  const items=Array.isArray(response.messages)?response.messages:[];
  if(items.length>60)throw new Error("Gmail result exceeds maximum expected page size");
  const ids=[];
  for(const obj of items) {
    if(!obj || typeof obj.id!=="string" || !/^[A-Za-z0-9_-]{1,200}$/.test(obj.id))
      throw new Error("Invalid Gmail message ID");
    ids.push(obj.id);
  }
  return ids;
}
function qfHeader_(headers,name) {
  if(!Array.isArray(headers)) return "";
  const matches=headers.filter(h=>h && typeof h.name==="string" &&
      h.name.toLowerCase()===name.toLowerCase() && typeof h.value==="string");
  return matches.map(h=>h.value).join("\n").slice(0,10000);
}
function qfPlainPart_(node,depth) {
  if(!node || typeof node!=="object" || depth>8) return "";
  // Never extract attachment payload; do not silently read HTML-only messages.
  if(node.filename) return "";
  if(String(node.mimeType||"").toLowerCase()==="text/plain" &&
     node.body && typeof node.body.data==="string") {
    const data=node.body.data;
    if(data.length>180000) return "";
    const padded=data+"=".repeat((4-data.length%4)%4);
    try {
      return Utilities.newBlob(Utilities.base64DecodeWebSafe(padded))
        .getDataAsString("UTF-8").slice(0,18000);
    } catch(ex) {
      return "";
    }
  }
  if(Array.isArray(node.parts)) {
    for(const part of node.parts.slice(0,30)) {
      const plain=qfPlainPart_(part,depth+1);
      if(plain) return plain;
    }
  }
  return "";
}
function qfMessageFromApi_(resource) {
  if(!resource || typeof resource.id!=="string" || !resource.payload)
    throw new Error("Malformed Gmail full-message response");
  const headers=resource.payload.headers;
  if(!Array.isArray(headers))throw new Error("Missing Gmail API message headers");
  const time=Number(resource.internalDate);
  if(!Number.isFinite(time) || time<=0)throw new Error("Invalid Gmail API received date");
  const received=new Date(time);
  if(Number.isNaN(received.getTime()))throw new Error("Invalid Gmail API timestamp");
  return {
    getId:()=>resource.id,
    getDate:()=>received,
    getFrom:()=>qfHeader_(headers,"From"),
    getSubject:()=>qfHeader_(headers,"Subject"),
    getHeader:(name)=>qfHeader_(headers,name),
    getPlainBody:()=>qfPlainPart_(resource.payload,0)
  };
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
    const ids=qfListMessageIds_();
    for(const id of ids) {
      if(seen.has(id)) continue;
      scanned++;
      const msg=qfMessageFromApi_(qfGmailApi_("/"+encodeURIComponent(id)+"?format=full"));
      const event=qfParse_(msg,cfg.owners);
      if(!event){rejected++;continue;}
      if(!cfg.dryRun) {
        qfComment_(cfg,event);
        processed.push(id);
        seen.add(id);
      }
      accepted++;
    }
    if(!cfg.dryRun) props.setProperty("QF_PROCESSED_IDS_JSON",JSON.stringify(processed.slice(-450)));
    const billing=qfCalendarMonthUtc_();
    console.log(JSON.stringify({dry_run:cfg.dryRun,
        billing_period_start_utc:billing.startUtc,
        billing_checked_through_utc:billing.nowUtc,
        scanned,verified_matches:accepted,manual_review:rejected}));
  } finally {
    lock.releaseLock();
  }
}
