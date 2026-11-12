"""Canonical project ownership: a stable home is NOT a pooled execution quota.

This registry is an optional operator-reviewed, local/private JSON file.
It never moves project files, creates repositories or permits private source
replication. Only explicit, stateless allowlisted profiles may use a backup.
"""
from __future__ import annotations
import json
from pathlib import Path
from .models import ConfigError, NAME, REPO, exact_fields

# Only the existing deterministic, synthetic worker profiles may be delegated.
# Project source, trading services and market datasets are never portable here.
SAFE_PORTABLE_PROFILES = frozenset({"smoke", "sample_compute"})
VALID_STATUS = frozenset({"verified_repository", "proposed_home"})

def load_project_registry(path, accounts):
    raw=json.loads(Path(path).read_text(encoding="utf-8"))
    exact_fields(raw, {"schema","projects"})
    if raw["schema"]!=1 or not isinstance(raw["projects"],list) or not raw["projects"]:
        raise ConfigError("Nonempty versioned project registry required")
    table={}
    seen=set()
    for item in raw["projects"]:
        exact_fields(item, {"project","aliases","home_account","home_repository","status","portable_profiles"},
                     {"notes"})
        project=item["project"]
        if not isinstance(project,str) or not NAME.fullmatch(project):
            raise ConfigError("Project identity must be an exact simple name")
        aliases=item["aliases"]
        if not isinstance(aliases,list) or not all(isinstance(x,str) and NAME.fullmatch(x) for x in aliases):
            raise ConfigError("Aliases must be simple identifiers")
        if len(set(aliases))!=len(aliases) or project in aliases:
            raise ConfigError("Duplicate project aliases")
        ids=[project,*aliases]
        if any(x.lower() in seen for x in ids):
            raise ConfigError("Project IDs and aliases must be globally unique")
        seen.update(x.lower() for x in ids)
        home=item["home_account"]
        if home not in accounts:
            raise ConfigError(f"Unknown canonical home account for project {project}")
        repo=item["home_repository"]
        if repo is not None:
            if not isinstance(repo,str) or not REPO.fullmatch(repo):
                raise ConfigError("Invalid home repository reference")
            if repo.split("/")[0].lower()!=accounts[home].owner.lower():
                raise ConfigError("Project home repository owner differs from canonical account")
        status=item["status"]
        if status not in VALID_STATUS or (status=="verified_repository" and repo is None):
            raise ConfigError("Unverified or invalid project repository ownership")
        portable=item["portable_profiles"]
        if not isinstance(portable,list) or len(set(portable))!=len(portable) or any(x not in SAFE_PORTABLE_PROFILES for x in portable):
            raise ConfigError("Only allowlisted non-sensitive deterministic profiles may be portable")
        if status!="verified_repository" and portable:
            raise ConfigError("Projects awaiting home verification may not delegate compute")
        if "notes" in item and (not isinstance(item["notes"],str) or len(item["notes"])>1500):
            raise ConfigError("Notes must be short, non-sensitive strings")
        table[project]={
            "project":project,"aliases":tuple(aliases),"home_account":home,
            "home_repository":repo,"status":status,
            "portable_profiles":tuple(portable),
            "notes":item.get("notes","")
        }
    return table

def resolve_project(table, identity):
    for project,info in table.items():
        if identity.lower()==project.lower() or identity.lower() in (x.lower() for x in info["aliases"]):
            return info
    return None

def authorize_project_runner(job, account_id, table):
    info=resolve_project(table,job.project)
    if info is None:
        return "unknown_project_blocked"
    if info["status"]!="verified_repository":
        return "project_home_not_verified"
    if account_id==info["home_account"]:
        return None
    if job.profile not in info["portable_profiles"]:
        return "cross_account_private_project_blocked"
    # Even for a permitted generic profile, normal account budgets/identity,
    # runner profile allowlists and explicit dispatch approval are mandatory.
    return None

def project_home_report(table, identity):
    info=resolve_project(table,identity)
    if info is None:
        raise ConfigError("Project is not mapped in the canonical registry")
    return {k:info[k] for k in ("project","aliases","home_account",
                                "home_repository","status","portable_profiles","notes")}
