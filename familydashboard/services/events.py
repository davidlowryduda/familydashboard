"""Querying events for display, in the family's local time."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import and_, or_

from ..models import Event
from ..timeutil import to_local, to_utc_naive


@dataclass
class DayEvent:
    event: Event
    label: str  # "All day", "3:30 PM", "until 11 AM", ...
    sort_key: tuple


def _local_midnight_utc(d: date) -> datetime:
    return to_utc_naive(datetime.combine(d, time()))


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%-I:%M %p").replace(":00 ", " ")


def events_by_day(first: date, last: date) -> dict[date, list[DayEvent]]:
    """Events touching each local day in [first, last] (inclusive), sorted per day."""
    after = first
    before = last + timedelta(days=1)
    events = Event.query.filter(
        or_(
            and_(Event.all_day.is_(True),
                 Event.start < datetime.combine(before, time()), Event.end > datetime.combine(after, time())),
            and_(Event.all_day.is_(False),
                 Event.start < _local_midnight_utc(before), Event.end >= _local_midnight_utc(after)),
        )
    ).all()

    days: dict[date, list[DayEvent]] = {}
    for ev in events:
        if ev.all_day:
            d, stop = ev.start.date(), ev.end.date()
            while d < stop:
                if first <= d <= last:
                    days.setdefault(d, []).append(DayEvent(ev, "All day", (0, ev.title)))
                d += timedelta(days=1)
            continue

        start, end = to_local(ev.start), to_local(ev.end)
        d = start.date()
        # An event ending exactly at midnight doesn't spill into the next day.
        end_day = (end - timedelta(microseconds=1)).date() if end > start else start.date()
        while d <= end_day:
            if first <= d <= last:
                if d == start.date():
                    label = _fmt_time(start)
                    key = (1, start.time(), ev.title)
                elif d == end_day:
                    label = f"until {_fmt_time(end)}"
                    key = (1, time(), ev.title)
                else:
                    label, key = "All day", (0, ev.title)
                days.setdefault(d, []).append(DayEvent(ev, label, key))
            d += timedelta(days=1)

    for items in days.values():
        items.sort(key=lambda de: de.sort_key)
    return days
