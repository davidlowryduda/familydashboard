from flask import Blueprint, abort, redirect, render_template, request, url_for
from flask_login import current_user

from ..extensions import db
from ..models import Message
from ..template_helpers import is_htmx

bp = Blueprint("messages", __name__, url_prefix="/board")

PAGE_SIZE = 50


def board_query():
    return Message.query.order_by(Message.pinned.desc(), Message.created_at.desc())


def _get_modifiable(message_id: int) -> Message:
    message = db.get_or_404(Message, message_id)
    if not message.can_modify(current_user):
        abort(403)
    return message


@bp.route("/")
def index():
    return render_template("messages/index.html", messages=board_query().limit(PAGE_SIZE).all())


@bp.route("/", methods=["POST"])
def create():
    body = request.form.get("body", "").strip()
    if body:
        message = Message(body=body[:5000], author_id=current_user.id)
        db.session.add(message)
        db.session.commit()
        if is_htmx():
            return render_template("messages/_message.html", m=message)
    return redirect(url_for("messages.index"))


@bp.route("/<int:message_id>/edit", methods=["GET", "POST"])
def edit(message_id):
    message = _get_modifiable(message_id)
    if request.method == "POST":
        body = request.form.get("body", "").strip()
        if body:
            message.body = body[:5000]
            db.session.commit()
        return redirect(url_for("messages.index"))
    return render_template("messages/edit.html", m=message)


@bp.route("/<int:message_id>/pin", methods=["POST"])
def pin(message_id):
    # Anyone can pin or unpin; pins are a shared "keep this on top" signal.
    message = db.get_or_404(Message, message_id)
    message.pinned = not message.pinned
    db.session.commit()
    return redirect(url_for("messages.index"))


@bp.route("/<int:message_id>/delete", methods=["POST"])
def delete(message_id):
    message = _get_modifiable(message_id)
    db.session.delete(message)
    db.session.commit()
    if is_htmx():
        return ""
    return redirect(url_for("messages.index"))
