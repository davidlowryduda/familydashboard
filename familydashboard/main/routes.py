from datetime import timedelta

from flask import Blueprint, render_template
from flask_login import current_user
from sqlalchemy import or_

from ..models import List, Todo
from ..messages.routes import board_query
from ..services.events import events_by_day
from ..timeutil import local_today
from ..todos.routes import open_todos_query

bp = Blueprint("main", __name__)

DUE_SOON_DAYS = 3


@bp.route("/")
def home():
    today = local_today()
    tomorrow = today + timedelta(days=1)
    days = events_by_day(today, tomorrow)
    my_todos = open_todos_query().filter(Todo.assigned_to_id == current_user.id).limit(8).all()
    due_soon = (
        open_todos_query()
        .filter(Todo.due_date <= today + timedelta(days=DUE_SOON_DAYS))
        .filter(or_(Todo.assigned_to_id.is_(None), Todo.assigned_to_id != current_user.id))
        .limit(8)
        .all()
    )
    return render_template(
        "main/home.html",
        today_events=days.get(today, []),
        tomorrow_events=days.get(tomorrow, []),
        tomorrow=tomorrow,
        my_todos=my_todos,
        due_soon=due_soon,
        messages=board_query().limit(3).all(),
        shopping_lists=List.query.filter_by(archived=False).order_by(List.kind.desc(), List.name).all(),
    )
