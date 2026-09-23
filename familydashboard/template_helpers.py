from datetime import timedelta
from functools import wraps

from flask import abort, request
from flask_login import current_user

from .models import format_quantity
from .services.quantities import display_unit
from .timeutil import humanize, local_today, to_local


NAV_ITEMS = [
    ("main.home", "Home"),
    ("calendar.index", "Calendar"),
    ("todos.index", "Todos"),
    ("messages.index", "Board"),
    ("lists.index", "Lists"),
    ("recipes.index", "Recipes"),
]


def is_htmx() -> bool:
    return request.headers.get("HX-Request") == "true"


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def _localtime(dt, fmt="%a %b %-d, %-I:%M %p"):
    if dt is None:
        return ""
    return to_local(dt).strftime(fmt)


def _nice_date(d):
    if d is None:
        return ""
    delta = (d - local_today()).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    if delta == -1:
        return "yesterday"
    if 1 < delta < 7:
        return d.strftime("%A")
    return d.strftime("%b %-d")


def _amount(quantity, unit=""):
    """'2 cups', '½ tsp', '3' or '' for an unspecified amount."""
    q = format_quantity(quantity)
    u = display_unit(unit or "", quantity)
    return " ".join(p for p in (q, u) if p)


def register(app):
    app.jinja_env.filters["localtime"] = _localtime
    app.jinja_env.filters["humanize"] = humanize
    app.jinja_env.filters["qty"] = format_quantity
    app.jinja_env.filters["nicedate"] = _nice_date
    app.jinja_env.filters["amount"] = _amount
    app.jinja_env.filters["prevday"] = lambda dt: (dt - timedelta(days=1)).strftime("%A, %B %-d")

    @app.context_processor
    def inject():
        nav = [(ep, label) for ep, label in NAV_ITEMS if ep in app.view_functions]
        return {"is_htmx": is_htmx(), "today": local_today(), "nav_items": nav}
