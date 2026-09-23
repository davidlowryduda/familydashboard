"""Time helpers.

Datetimes are stored in SQLite as naive UTC. Everything shown to people is
converted to the family's timezone (``FAMILY_TZ``).
"""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from flask import current_app


def family_tz() -> ZoneInfo:
    return ZoneInfo(current_app.config["FAMILY_TZ"])


def utcnow() -> datetime:
    """Current time as naive UTC, the storage format."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_local(dt: datetime) -> datetime:
    """Naive-UTC (or aware) datetime -> aware datetime in the family timezone."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(family_tz())


def to_utc_naive(dt: datetime) -> datetime:
    """Aware datetime, or naive datetime in the family timezone -> naive UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=family_tz())
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def local_now() -> datetime:
    return datetime.now(family_tz())


def local_today() -> date:
    return local_now().date()


def humanize(dt: datetime) -> str:
    """Short relative time like '5m ago' or 'Mar 3'."""
    seconds = (utcnow() - (to_utc_naive(dt) if dt.tzinfo else dt)).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    if seconds < 7 * 86400:
        return f"{int(seconds // 86400)}d ago"
    return to_local(dt).strftime("%b %-d")
