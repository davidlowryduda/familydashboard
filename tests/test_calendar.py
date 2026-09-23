from datetime import date, datetime
from pathlib import Path
from unittest import mock

import pytest

from familydashboard.extensions import db
from familydashboard.models import CalendarFeed, Event
from familydashboard.services import ics
from familydashboard.services.events import events_by_day

SAMPLE = (Path(__file__).parent / "fixtures" / "sample.ics").read_bytes()


@pytest.fixture
def fixed_today():
    with mock.patch.object(ics, "local_today", return_value=date(2026, 9, 1)):
        yield


def fake_get(content=SAMPLE, status=200):
    resp = mock.Mock(content=content, status_code=status)
    resp.raise_for_status = mock.Mock()
    if status >= 400:
        resp.raise_for_status.side_effect = ics.requests.HTTPError(f"{status} error")
    return mock.patch.object(ics.requests, "get", return_value=resp)


@pytest.fixture
def feed(app, parent):
    f = CalendarFeed(owner_id=parent.id, name="School", ics_url="webcal://example.com/cal.ics")
    db.session.add(f)
    db.session.commit()
    return f


def test_parse_expands_recurrences_and_skips_cancelled(app):
    events = ics.parse(SAMPLE, date(2026, 8, 1), date(2026, 12, 31))
    titles = [e.title for e in events]
    assert titles.count("Soccer practice") == 4
    assert "Cancelled thing" not in titles
    soccer = sorted((e for e in events if e.title == "Soccer practice"), key=lambda e: e.start)
    # 5pm EDT == 21:00 UTC
    assert soccer[0].start == datetime(2026, 9, 1, 21, 0)
    assert soccer[0].end == datetime(2026, 9, 1, 22, 30)
    trip = next(e for e in events if e.title == "Camping trip")
    assert trip.all_day and trip.start == datetime(2026, 9, 11) and trip.end == datetime(2026, 9, 14)


def test_sync_replaces_rather_than_duplicates(app, feed, fixed_today):
    with fake_get() as get:
        assert ics.sync_feed(feed)
        assert ics.sync_feed(feed)
    assert get.call_args[0][0] == "https://example.com/cal.ics"  # webcal:// rewritten
    assert Event.query.filter_by(feed_id=feed.id).count() == 7  # 4 soccer + holiday + trip + late call
    assert feed.last_error is None and feed.last_synced_at is not None


def test_sync_failure_keeps_old_events(app, feed, fixed_today):
    with fake_get():
        ics.sync_feed(feed)
    with fake_get(status=404):
        assert not ics.sync_feed(feed)
    assert "404" in feed.last_error
    assert Event.query.filter_by(feed_id=feed.id).count() == 7


def test_events_by_day_buckets_local_days(app, feed, fixed_today):
    with fake_get():
        ics.sync_feed(feed)
    days = events_by_day(date(2026, 9, 1), date(2026, 9, 30))
    assert [de.event.title for de in days[date(2026, 9, 1)]] == ["Soccer practice"]
    assert days[date(2026, 9, 1)][0].label == "5 PM"
    # 03:00 UTC on the 4th is 11 PM on the 3rd in New York.
    assert [de.event.title for de in days[date(2026, 9, 3)]] == ["Late call"]
    # The trip covers the 11th-13th (DTEND is exclusive).
    for d in (11, 12, 13):
        assert any(de.event.title == "Camping trip" for de in days[date(2026, 9, d)])
    assert not any(de.event.title == "Camping trip" for de in days.get(date(2026, 9, 14), []))


def test_feed_events_are_read_only(client, feed, fixed_today):
    with fake_get():
        ics.sync_feed(feed)
    ev = Event.query.filter_by(feed_id=feed.id).first()
    assert client.get(f"/calendar/events/{ev.id}").status_code == 200
    assert client.post(f"/calendar/events/{ev.id}", data={"title": "x", "start_date": "2026-09-01"}).status_code == 403
    assert client.post(f"/calendar/events/{ev.id}/delete").status_code == 403


def test_local_event_crud(client):
    resp = client.post("/calendar/events/new", data={
        "title": "Dentist", "start_date": "2026-09-15", "start_time": "09:30", "end_time": "10:15",
    })
    assert resp.status_code == 302
    ev = Event.query.one()
    assert not ev.all_day and ev.start == datetime(2026, 9, 15, 13, 30)
    page = client.get("/calendar/?month=2026-09").data
    assert b"Dentist" in page and b"9:30 AM" in page

    client.post(f"/calendar/events/{ev.id}", data={"title": "Birthday", "start_date": "2026-09-20", "all_day": "on"})
    assert ev.all_day and ev.start == datetime(2026, 9, 20) and ev.end == datetime(2026, 9, 21)
    client.post(f"/calendar/events/{ev.id}/delete")
    assert Event.query.count() == 0


def test_event_end_before_start_rejected(client):
    client.post("/calendar/events/new", data={"title": "Oops", "start_date": "2026-09-15", "end_date": "2026-09-14"})
    assert Event.query.count() == 0


def test_add_feed_via_page(client, fixed_today):
    with fake_get():
        client.post("/calendar/feeds", data={"name": "Work", "ics_url": "https://example.com/x.ics", "color": "#457b9d"})
    feed = CalendarFeed.query.one()
    assert len(feed.events) == 7
    assert b"Work" in client.get("/calendar/feeds").data


def test_bad_feed_url_rejected(client):
    client.post("/calendar/feeds", data={"name": "Bad", "ics_url": "file:///etc/passwd"})
    assert CalendarFeed.query.count() == 0


def test_kid_cannot_delete_parents_feed(kid_client, feed):
    assert kid_client.post(f"/calendar/feeds/{feed.id}/delete").status_code == 403


def test_sync_stale_endpoint_refreshes(client, feed, fixed_today):
    with fake_get():
        resp = client.post("/calendar/sync-stale")
    assert resp.headers.get("HX-Refresh") == "true"
    with fake_get() as get:
        resp = client.post("/calendar/sync-stale")
    assert not get.called and "HX-Refresh" not in resp.headers
