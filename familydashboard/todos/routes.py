from datetime import date

from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import case

from ..extensions import db
from ..models import Todo, User, set_completed
from ..template_helpers import is_htmx

bp = Blueprint("todos", __name__, url_prefix="/todos")

FILTERS = {"open": "Open", "mine": "Mine", "done": "Done", "all": "All"}


def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _parse_user_id(value: str | None) -> int | None:
    if value and value.isdigit() and db.session.get(User, int(value)):
        return int(value)
    return None


def open_todos_query():
    return Todo.query.filter_by(done=False).order_by(
        case((Todo.due_date.is_(None), 1), else_=0), Todo.due_date, Todo.created_at
    )


@bp.route("/")
def index():
    current = request.args.get("filter", "open")
    if current not in FILTERS:
        current = "open"
    if current == "done":
        query = Todo.query.filter_by(done=True).order_by(Todo.done_at.desc())
    elif current == "all":
        query = Todo.query.order_by(Todo.done, Todo.created_at.desc())
    else:
        query = open_todos_query()
        if current == "mine":
            query = query.filter(Todo.assigned_to_id == current_user.id)
    return render_template(
        "todos/index.html",
        todos=query.all(),
        filters=FILTERS,
        current=current,
        users=User.query.order_by(User.display_name).all(),
        done_count=Todo.query.filter_by(done=True).count(),
    )


@bp.route("/", methods=["POST"])
def create():
    title = request.form.get("title", "").strip()
    if title:
        todo = Todo(
            title=title[:200],
            due_date=_parse_date(request.form.get("due_date")),
            assigned_to_id=_parse_user_id(request.form.get("assigned_to_id")),
            created_by_id=current_user.id,
        )
        db.session.add(todo)
        db.session.commit()
        if is_htmx():
            return render_template("todos/_row.html", todo=todo)
    return redirect(url_for("todos.index"))


@bp.route("/<int:todo_id>/toggle", methods=["POST"])
def toggle(todo_id):
    todo = db.get_or_404(Todo, todo_id)
    set_completed(todo, not todo.done)
    db.session.commit()
    if is_htmx():
        return render_template("todos/_row.html", todo=todo)
    return redirect(request.referrer or url_for("todos.index"))


@bp.route("/<int:todo_id>/edit", methods=["GET", "POST"])
def edit(todo_id):
    todo = db.get_or_404(Todo, todo_id)
    if request.method == "POST":
        todo.title = request.form.get("title", todo.title).strip()[:200] or todo.title
        todo.notes = request.form.get("notes", "").strip()
        todo.due_date = _parse_date(request.form.get("due_date"))
        todo.assigned_to_id = _parse_user_id(request.form.get("assigned_to_id"))
        db.session.commit()
        return redirect(url_for("todos.index"))
    return render_template("todos/edit.html", todo=todo, users=User.query.order_by(User.display_name).all())


@bp.route("/<int:todo_id>/delete", methods=["POST"])
def delete(todo_id):
    todo = db.get_or_404(Todo, todo_id)
    db.session.delete(todo)
    db.session.commit()
    if is_htmx():
        return ""
    return redirect(url_for("todos.index"))


@bp.route("/clear-done", methods=["POST"])
def clear_done():
    Todo.query.filter_by(done=True).delete()
    db.session.commit()
    return redirect(url_for("todos.index"))
