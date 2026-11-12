"""GitHub REST operations with owner identity proof and no token logging."""
from __future__ import annotations
import base64
import json
import os
from urllib import request, error, parse
from .models import Account

class GitHubError(RuntimeError):
    pass

class GitHub:
    def __init__(self, account: Account, transport=None, environ=None):
        self.account = account
        self.env = os.environ if environ is None else environ
        self.transport = transport
        self.token = self.env.get(account.token_env)
        if not self.token:
            raise GitHubError(f"Missing token in environment variable {account.token_env}")

    def api(self, path, method="GET", body=None):
        if not path.startswith("/") or "://" in path:
            raise GitHubError("Only relative GitHub API paths are accepted")
        headers = {"Accept": "application/vnd.github+json", "Authorization": "Bearer " + self.token,
                   "X-GitHub-Api-Version": "2026-03-10", "User-Agent": "QuotaFlow/0.1"}
        payload = json.dumps(body).encode() if body is not None else None
        if payload is not None:
            headers["Content-Type"] = "application/json"
        req = request.Request("https://api.github.com" + path, data=payload, headers=headers, method=method)
        try:
            if self.transport is None:
                with request.urlopen(req, timeout=20) as res:
                    raw, status = res.read(), res.status
            else:
                status, raw = self.transport(req)
            if not 200 <= status <= 299:
                raise GitHubError(f"GitHub returned HTTP {status} for {method} {path.split('?')[0]}")
            return json.loads(raw) if raw else None
        except error.HTTPError as exc:
            # Do not print provider error bodies: they can contain private details.
            raise GitHubError(f"GitHub HTTP {exc.code} for {method} {path.split('?')[0]}") from None
        except (error.URLError, TimeoutError) as exc:
            raise GitHubError(f"GitHub network/timeout problem for {method} {path.split('?')[0]}") from None

    def verify(self):
        # Repo-scoped Actions tokens are GitHub App tokens, not human account tokens.
        # This explicit self-repo-only mode is limited to PUBLIC standard runner jobs.
        self_token = self.account.github_actions_self_token
        if self_token:
            if (self.env.get("GITHUB_ACTIONS") != "true"
                or self.env.get("GITHUB_REPOSITORY", "").lower() != self.account.repository.lower()
                or self.env.get("GITHUB_REPOSITORY_OWNER", "").lower() != self.account.owner.lower()):
                raise GitHubError("GitHub Actions self-token requires exact current repo and owner")
        else:
            who = self.api("/user")
            if not isinstance(who, dict) or who.get("login", "").lower() != self.account.owner.lower():
                raise GitHubError("Token user differs from configured repository owner; routing disabled")
        repo_name = self.account.repository
        repo = self.api("/repos/" + repo_name)
        if not isinstance(repo, dict) or repo.get("full_name", "").lower() != repo_name.lower() or repo.get("owner", {}).get("login", "").lower() != self.account.owner.lower():
            raise GitHubError("Repository ownership not verified")
        if repo.get("archived") is True:
            raise GitHubError("Archived repository is not dispatchable")
        if self.account.public_standard_runner and repo.get("private") is not False:
            raise GitHubError("Repository is not verified public; free public compute claim rejected")
        if self_token and (repo.get("private") is not False
                           or self.account.ref != repo.get("default_branch")):
            raise GitHubError("Self-repo token may dispatch only the current public default branch")
        wf_name = parse.quote(self.account.workflow)
        wf = self.api("/repos/" + repo_name + "/actions/workflows/" + wf_name)
        if not isinstance(wf, dict) or wf.get("state") != "active":
            raise GitHubError("Target workflow must be active")
        contents = self.api("/repos/" + repo_name + "/contents/.github/workflows/" + wf_name + "?ref=" + parse.quote(self.account.ref, safe=""))
        if not isinstance(contents, dict) or contents.get("encoding") != "base64":
            raise GitHubError("Cannot verify exact workflow source")
        try:
            source = base64.b64decode(contents.get("content", "")).decode()
        except (ValueError, UnicodeDecodeError):
            raise GitHubError("Workflow source unreadable") from None
        if ("QUOTAFLOW_WORKER_V1" not in source or
            "run-name: QuotaFlow" not in source or
            "workflow_dispatch:" not in source or
            "github.event.inputs.profile" not in source and "inputs.profile" not in source):
            raise GitHubError("Worker contract not present in repository workflow")
        return {"owner": repo["owner"]["login"] if self_token else who["login"],
                "auth_mode": "repo_scoped_actions_self" if self_token else "human_owner",
                "repository": repo["full_name"], "workflow": wf.get("name"),
                "private": repo["private"], "verified_source": True}

    def dispatch(self, job_id: str, profile: str):
        if profile not in self.account.profiles:
            raise GitHubError("Profile outside account allowlist")
        path = "/repos/" + self.account.repository + "/actions/workflows/" + parse.quote(self.account.workflow) + "/dispatches"
        return self.api(path, "POST", {"ref": self.account.ref, "inputs": {"job_id": job_id, "profile": profile}})

    def find_run(self, job_id: str):
        path = "/repos/" + self.account.repository + "/actions/workflows/" + parse.quote(self.account.workflow) + "/runs?event=workflow_dispatch&per_page=100"
        data = self.api(path)
        runs = data.get("workflow_runs", []) if isinstance(data, dict) else []
        matches = [r for r in runs if r.get("display_title") == "QuotaFlow " + job_id and r.get("head_branch") == self.account.ref]
        if len(matches) > 1:
            raise GitHubError("Multiple runs match job ID; manual reconciliation required")
        return matches[0] if matches else None

    def billing_probe(self):
        # Read-only endpoints; GitHub may return 404/403 depending on token scope and API version.
        path = "/users/" + self.account.owner + "/settings/billing/usage/summary"
        obj = self.api(path)
        return {"response_keys": sorted(obj) if isinstance(obj, dict) else [], "note": "Report only; does not autonomously set spendable quota"}
