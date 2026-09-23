import calendar as pycal
from datetime import date, datetime, time, timedelta

from flask import Blueprint, abort, flash, make_response, redirect, render_template, request, url_for
from flask_login import current_user
from loguru import logger

from ..extensions import db
from ..models import CalendarFeed, Event
from ..services.events import events_by_day
from ..services.ics import is_valid_url, stale_feeds, sync_feed
from ..timeutil import local_today, to_local, to_utc_naive

bp = Blueprint("calendar", __name__, url_prefix="/calendar")

FEED_COLORS = ["#457b9d", "#e76f51", "#2a9d8f", "#8e7dbe", "#f4a261", "#6a994e", "#d62828", "#e9c46a"]
AGENDA_DAYS = 14


def _parse_month(value: str | None) -> date:
    try:
        return datetime.strptime(value or "", "%Y-%m").date()
    except ValueError:
        return local_today().replace(day=1)


@bp.route("/")
def index():
    month = _parse_month(request.args.get("month"))
    weeks = pycal.Calendar(firstweekday=6).monthdatescalendar(month.year, month.month)  # weeks start Sunday
    days = events_by_day(weeks[0][0], weeks[-1][-1])
    prev_month = (month - timedelta(days=1)).replace(day=1)
    next_month = (month + timedelta(days=32)).replace(day=1)
    return render_template(
        "calendar/month.html", month=month, weeks=weeks, days=days,
        prev_month=prev_month, next_month=next_month,
        has_stale=bool(stale_feeds()),
    )


@bp.route("/agenda")
def agenda():
    start = local_today()
    days = events_by_day(start, start + timedelta(days=AGENDA_DAYS - 1))
    return render_template(
        "calendar/agenda.html", start=start, dates=[start + timedelta(days=n) for n in range(AGENDA_DAYS)],
        days=days, has_stale=bool(stale_feeds()),
    )


@bp.route("/sync-stale", methods=["POST"])
def sync_stale():
    """Called by htmx after a calendar page loads so slow feeds don't block rendering."""
    feeds = stale_feeds()
    changed = any([sync_feed(f) for f in feeds])
    resp = make_response("")
    if changed:
        resp.headers["HX-Refresh"] = "true"
    return resp


# --- Local events -------------------------------------------------------------

def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _parse_time(value: str | None) -> time | None:
    try:
        return time.fromisoformat(value) if value else None
    except ValueError:
        return None


def _apply_event_form(ev: Event) -> str | None:
    title = request.form.get("title", "").strip()
    start_date = _parse_date(request.form.get("start_date"))
    if not title or start_date is None:
        return "An event needs a title and a date."
    end_date = _parse_date(request.form.get("end_date")) or start_date
    start_time = _parse_time(request.form.get("start_time"))
    end_time = _parse_time(request.form.get("end_time"))
    if end_date < start_date:
        return "The event can't end before it starts."

    if request.form.get("all_day") or start_time is None:
        ev.all_day = True
        ev.start = datetime.combine(start_date, time())
        ev.end = datetime.combine(end_date + timedelta(days=1), time())  # stored end is exclusive
    else:
        ev.all_day = False
        ev.start = to_utc_naive(datetime.combine(start_date, start_time))
        if end_time is None:
            ev.end = ev.start + timedelta(hours=1)
        else:
            ev.end = to_utc_naive(datetime.combine(end_date, end_time))
            if ev.end < ev.start:
                return "The event can't end before it starts."
    ev.title = title[:300]
    ev.location = request.form.get("location", "").strip()[:300]
    ev.description = request.form.get("description", "").strip()
    return None


def _form_values(ev: Event) -> dict:
    if ev.start is None:
        d = _parse_date(request.args.get("date")) or local_today()
        return {"start_date": d, "end_date": d, "start_time": "", "end_time": "", "all_day": False}
    if ev.all_day:
        return {"start_date": ev.start.date(), "end_date": (ev.end - timedelta(days=1)).date(),
                "start_time": "", "end_time": "", "all_day": True}
    s, e = to_local(ev.start), to_local(ev.end)
    return {"start_date": s.date(), "end_date": e.date(), "start_time": s.strftime("%H:%M"),
            "end_time": e.strftime("%H:%M"), "all_day": False}


def _month_of(ev: Event) -> str:
    d = ev.start.date() if ev.all_day else to_local(ev.start).date()
    return d.strftime("%Y-%m")


@bp.route("/events/new", methods=["GET", "POST"])
def new_event():
    ev = Event()
    if request.method == "POST":
        error = _apply_event_form(ev)
        if error:
            flash(error, "error")
        else:
            ev.created_by_id = current_user.id
            db.session.add(ev)
            db.session.commit()
            return redirect(url_for("calendar.index", month=_month_of(ev)))
    return render_template("calendar/event_form.html", ev=ev, v=_form_values(ev))


@bp.route("/events/<int:event_id>", methods=["GET", "POST"])
def event(event_id):
    ev = db.get_or_404(Event, event_id)
    if request.method == "POST":
        if not ev.is_local:
            abort(403)
        error = _apply_event_form(ev)
        if error:
            flash(error, "error")
        else:
            db.session.commit()
            return redirect(url_for("calendar.index", month=_month_of(ev)))
    if not ev.is_local:
        return render_template("calendar/event_view.html", ev=ev)
    return render_template("calendar/event_form.html", ev=ev, v=_form_values(ev))


@bp.route("/events/<int:event_id>/delete", methods=["POST"])
def delete_event(event_id):
    ev = db.get_or_404(Event, event_id)
    if not ev.is_local:
        abort(403)
    month = _month_of(ev)
    db.session.delete(ev)
    db.session.commit()
    return redirect(url_for("calendar.index", month=month))


# --- Feeds ------------------------------------------------------------------

def _get_own_feed(feed_id: int) -> CalendarFeed:
    feed = db.get_or_404(CalendarFeed, feed_id)
    if feed.owner_id != current_user.id and not current_user.is_admin:
        abort(403)
    return feed


@bp.route("/feeds", methods=["GET", "POST"])
def feeds():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        url = request.form.get("ics_url", "").strip()
        color = request.form.get("color", FEED_COLORS[0])
        if not name or not is_valid_url(url):
            flash("Give the calendar a name and an https:// or webcal:// link.", "error")
            return redirect(url_for("calendar.feeds"))
        feed = CalendarFeed(owner_id=current_user.id, name=name[:100], ics_url=url[:1000],
                            color=color if color in FEED_COLORS else FEED_COLORS[0])
        db.session.add(feed)
        db.session.commit()
        logger.info("{} connected calendar feed {!r}", current_user.username, feed.name)
        if sync_feed(feed):
            flash(f"Added {feed.name} with {len(feed.events)} events.", "ok")
        else:
            flash(f"Added {feed.name}, but the first sync failed: {feed.last_error}", "error")
        return redirect(url_for("calendar.feeds"))
    all_feeds = CalendarFeed.query.order_by(CalendarFeed.name).all()
    return render_template("calendar/feeds.html", feeds=all_feeds, colors=FEED_COLORS)


@bp.route("/feeds/<int:feed_id>/sync", methods=["POST"])
def sync(feed_id):
    feed = db.get_or_404(CalendarFeed, feed_id)
    if sync_feed(feed):
        flash(f"Refreshed {feed.name}.", "ok")
    else:
        flash(f"Couldn't refresh {feed.name}: {feed.last_error}", "error")
    return redirect(request.referrer or url_for("calendar.feeds"))


@bp.route("/feeds/<int:feed_id>/delete", methods=["POST"])
def delete_feed(feed_id):
    feed = _get_own_feed(feed_id)
    db.session.delete(feed)
    db.session.commit()
    logger.info("{} removed calendar feed {!r}", current_user.username, feed.name)
    flash(f"Removed {feed.name}.", "ok")
    return redirect(url_for("calendar.feeds"))


@bp.route("/feeds/<int:feed_id>/color", methods=["POST"])
def feed_color(feed_id):
    feed = _get_own_feed(feed_id)
    if request.form.get("color") in FEED_COLORS:
        feed.color = request.form["color"]
        db.session.commit()
    return redirect(url_for("calendar.feeds"))
