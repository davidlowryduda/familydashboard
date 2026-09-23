"""Read-only calendar subscriptions (Google Calendar / Outlook "secret ICS" links).

Each sync downloads the feed, expands recurring events over a window around
today, and replaces that feed's stored events.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import recurring_ical_events
import requests
from flask import current_app
from icalendar import Calendar

from ..extensions import db
from ..models import CalendarFeed, Event
from ..timeutil import local_today, to_utc_naive, utcnow

USER_AGENT = "FamilyDashboard/0.1 (+calendar sync)"


@dataclass
class ParsedEvent:
    uid: str
    title: str
    start: datetime
    end: datetime
    all_day: bool
    location: str
    description: str


def normalize_url(url: str) -> str:
    url = url.strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    return url


def is_valid_url(url: str) -> bool:
    return normalize_url(url).lower().startswith(("https://", "http://"))


def fetch(url: str) -> bytes:
    resp = requests.get(
        normalize_url(url),
        timeout=current_app.config["CALENDAR_FETCH_TIMEOUT"],
        headers={"User-Agent": USER_AGENT},
    )
    resp.raise_for_status()
    return resp.content


def _as_utc_naive(value: datetime) -> datetime:
    # Floating times (no TZID) are taken to be in the family's timezone.
    return to_utc_naive(value)


def parse(data: bytes, window_start: date, window_end: date) -> list[ParsedEvent]:
    cal = Calendar.from_ical(data)
    events = []
    for comp in recurring_ical_events.of(cal, skip_bad_series=True).between(window_start, window_end):
        if str(comp.get("STATUS", "")).upper() == "CANCELLED":
            continue
        dtstart = comp.get("DTSTART")
        if dtstart is None:
            continue
        start = dtstart.dt
        dtend = comp.get("DTEND")
        if dtend is not None:
            end = dtend.dt
        elif comp.get("DURATION") is not None:
            end = start + comp.get("DURATION").dt
        else:
            end = start + (timedelta(days=1) if not isinstance(start, datetime) else timedelta(0))

        all_day = not isinstance(start, datetime)
        if all_day:
            start_dt = datetime.combine(start, time())
            end_dt = datetime.combine(end if not isinstance(end, datetime) else end.date(), time())
            if end_dt <= start_dt:
                end_dt = start_dt + timedelta(days=1)
        else:
            start_dt = _as_utc_naive(start)
            end_dt = _as_utc_naive(end) if isinstance(end, datetime) else start_dt
            end_dt = max(end_dt, start_dt)

        events.append(ParsedEvent(
            uid=str(comp.get("UID", ""))[:500],
            title=(str(comp.get("SUMMARY", "")).strip() or "(busy)")[:300],
            start=start_dt,
            end=end_dt,
            all_day=all_day,
            location=str(comp.get("LOCATION", "")).strip()[:300],
            description=str(comp.get("DESCRIPTION", "")).strip()[:5000],
        ))
    return events


def sync_window() -> tuple[date, date]:
    today = local_today()
    cfg = current_app.config
    return today - timedelta(days=cfg["CALENDAR_PAST_DAYS"]), today + timedelta(days=cfg["CALENDAR_FUTURE_DAYS"])


def sync_feed(feed: CalendarFeed) -> bool:
    """Refresh one feed. Returns True on success; errors are stored on the feed."""
    feed.last_synced_at = utcnow()
    try:
        parsed = parse(fetch(feed.ics_url), *sync_window())
    except Exception as exc:  # network, HTTP or parse errors all end up on the feed
        feed.last_error = f"{type(exc).__name__}: {exc}"[:1000]
        db.session.commit()
        return False

    Event.query.filter_by(feed_id=feed.id).delete()
    for p in parsed:
        db.session.add(Event(
            feed_id=feed.id, uid=p.uid, title=p.title, start=p.start, end=p.end,
            all_day=p.all_day, location=p.location, description=p.description,
        ))
    feed.last_error = None
    db.session.commit()
    return True


def stale_feeds(max_age_minutes: int | None = None) -> list[CalendarFeed]:
    if max_age_minutes is None:
        max_age_minutes = current_app.config["CALENDAR_STALE_MINUTES"]
    cutoff = utcnow() - timedelta(minutes=max_age_minutes)
    return CalendarFeed.query.filter(
        (CalendarFeed.last_synced_at.is_(None)) | (CalendarFeed.last_synced_at < cutoff)
    ).all()
