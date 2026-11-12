"""GitHub Actions billing is tracked by UTC calendar month, never rolling days."""
from __future__ import annotations
from datetime import datetime, timezone

def utc_month_start(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Billing time requires timezone-aware datetime")
    moment=value.astimezone(timezone.utc)
    return datetime(moment.year,moment.month,1,tzinfo=timezone.utc)

def billing_month(value: datetime) -> str:
    return utc_month_start(value).strftime("%Y-%m")

def same_billing_period(observed: datetime, now: datetime) -> bool:
    if observed.tzinfo is None or now.tzinfo is None:
        raise ValueError("UTC-aware timestamps required")
    return billing_month(observed)==billing_month(now)
