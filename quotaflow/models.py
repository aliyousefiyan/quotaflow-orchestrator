"""Strict schema validation; a config file never contains secrets."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import re
from typing import Any

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]{0,150}$")
ENV = re.compile(r"^[A-Z][A-Z0-9_]*$")

class ConfigError(ValueError):
    """Unsafe or invalid configuration."""


def timestamp(value: str) -> datetime:
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as ex:
        raise ConfigError("A timezone-aware ISO timestamp is required") from ex
    if d.tzinfo is None:
        raise ConfigError("A timezone-aware ISO timestamp is required")
    return d.astimezone(timezone.utc)


def exact_fields(raw: dict, required: set, optional: set = frozenset()):
    if not isinstance(raw, dict) or not required <= raw.keys() or raw.keys() - (required | optional):
        raise ConfigError("Required, allowed configuration keys do not match")


def number(value: Any, *, nonnegative=True) -> float:
    if type(value) not in (float, int) or (nonnegative and value < 0) or value != value or value in (float("inf"), -float("inf")):
        raise ConfigError("Invalid finite nonnegative number")
    return float(value)


@dataclass(frozen=True)
class Account:
    id: str
    owner: str
    repository: str
    workflow: str
    ref: str
    token_env: str
    profiles: tuple[str, ...]
    minimum_reserve_usd: float = 0.25
    public_standard_runner: bool = False
    github_actions_self_token: bool = False

    @classmethod
    def parse(cls, value):
        exact_fields(value, {"id", "owner", "repository", "workflow", "ref", "token_env", "profiles"}, {"minimum_reserve_usd", "public_standard_runner", "github_actions_self_token"})
        for key in ("id", "owner"):
            if not isinstance(value[key], str) or not NAME.fullmatch(value[key]):
                raise ConfigError(f"Invalid {key}")
        if not isinstance(value["repository"], str) or not REPO.fullmatch(value["repository"]) or value["repository"].split("/")[0].lower() != value["owner"].lower():
            raise ConfigError("Repository must belong to configured owner")
        if not isinstance(value["workflow"], str) or not re.fullmatch(r"[\w.-]+\.ya?ml", value["workflow"]):
            raise ConfigError("Workflow must be a YAML filename, not a path")
        if not isinstance(value["ref"], str) or not REF.fullmatch(value["ref"]) or ".." in value["ref"]:
            raise ConfigError("Invalid ref")
        if not isinstance(value["token_env"], str) or not ENV.fullmatch(value["token_env"]):
            raise ConfigError("Token environment variable must be an uppercase name")
        profiles = value["profiles"]
        if not isinstance(profiles, list) or not profiles or any(not isinstance(p, str) or not NAME.fullmatch(p) for p in profiles) or len(set(profiles)) != len(profiles):
            raise ConfigError("Profiles must be a nonempty unique allowlist")
        if type(value.get("public_standard_runner", False)) is not bool:
            raise ConfigError("Invalid public runner flag")
        if type(value.get("github_actions_self_token", False)) is not bool:
            raise ConfigError("Invalid GitHub Actions self-token flag")
        if value.get("github_actions_self_token", False) and not value.get("public_standard_runner", False):
            raise ConfigError("GitHub Actions self token is permitted only for verified public standard runners")
        return cls(value["id"], value["owner"], value["repository"], value["workflow"], value["ref"], value["token_env"], tuple(profiles), number(value.get("minimum_reserve_usd", .25)), value.get("public_standard_runner", False), value.get("github_actions_self_token", False))


@dataclass(frozen=True)
class Job:
    id: str
    project: str
    profile: str
    estimated_usd: float
    priority: int
    target_accounts: tuple[str, ...]
    inputs_digest: str

    @classmethod
    def parse(cls, raw):
        exact_fields(raw, {"id", "project", "profile", "estimated_usd", "priority", "target_accounts", "inputs_digest"})
        for key in ("id", "project", "profile"):
            if not isinstance(raw[key], str) or not NAME.fullmatch(raw[key]):
                raise ConfigError(f"Invalid job {key}")
        if type(raw["priority"]) is not int or not 0 <= raw["priority"] <= 9:
            raise ConfigError("Priority must be integer 0..9, lower runs first")
        if not isinstance(raw["target_accounts"], list) or not raw["target_accounts"] or any(not isinstance(a, str) or not NAME.fullmatch(a) for a in raw["target_accounts"]) or len(set(raw["target_accounts"])) != len(raw["target_accounts"]):
            raise ConfigError("Nonempty unique account choices required")
        if not isinstance(raw["inputs_digest"], str) or not re.fullmatch(r"[a-f0-9]{64}", raw["inputs_digest"]):
            raise ConfigError("A real input SHA256 digest is required")
        return cls(raw["id"], raw["project"], raw["profile"], number(raw["estimated_usd"]), raw["priority"], tuple(raw["target_accounts"]), raw["inputs_digest"])


def load_accounts(path: str | Path) -> dict[str, Account]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    exact_fields(data, {"schema", "accounts"})
    if data["schema"] != 1 or not isinstance(data["accounts"], list):
        raise ConfigError("Unsupported config version")
    acc = [Account.parse(x) for x in data["accounts"]]
    if not acc or len({a.id for a in acc}) != len(acc):
        raise ConfigError("Unique nonempty account IDs required")
    return {a.id: a for a in acc}


def load_budgets(path: str | Path) -> dict[str, dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    exact_fields(data, {"schema", "accounts"})
    if data["schema"] != 1 or not isinstance(data["accounts"], dict):
        raise ConfigError("Unsupported budgets version")
    for value in data["accounts"].values():
        exact_fields(value, {"as_of_utc", "source", "remaining_usd"}, {"note"})
        if value["source"] not in ("manual", "verified_billing"):
            raise ConfigError("Quota source must be manual or verified_billing")
        if value["remaining_usd"] is not None:
            number(value["remaining_usd"])
        if value["as_of_utc"] is not None:
            timestamp(value["as_of_utc"])
    return data["accounts"]
