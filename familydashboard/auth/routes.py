from urllib.parse import urlsplit

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ..extensions import db
from ..models import USER_COLORS, User
from ..template_helpers import admin_required

bp = Blueprint("auth", __name__)

MIN_PASSWORD_LENGTH = 6


def _safe_next(target: str | None) -> str:
    """Only allow redirects to local paths."""
    if target and urlsplit(target).netloc == "" and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("main.home")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user is None or not user.check_password(password):
            flash("Wrong username or password.", "error")
            return render_template("auth/login.html", username=username), 401
        login_user(user, remember=bool(request.form.get("remember")))
        return redirect(_safe_next(request.args.get("next")))
    return render_template("auth/login.html")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@bp.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "password":
            if not current_user.check_password(request.form.get("current", "")):
                flash("Current password is incorrect.", "error")
            elif len(request.form.get("new", "")) < MIN_PASSWORD_LENGTH:
                flash(f"New password must be at least {MIN_PASSWORD_LENGTH} characters.", "error")
            elif request.form.get("new") != request.form.get("confirm"):
                flash("New passwords don't match.", "error")
            else:
                current_user.set_password(request.form["new"])
                db.session.commit()
                flash("Password changed.", "ok")
        elif action == "profile":
            name = request.form.get("display_name", "").strip()
            if name:
                current_user.display_name = name
            color = request.form.get("color", "")
            if color.startswith("#") and len(color) == 7:
                current_user.color = color
            db.session.commit()
            flash("Profile updated.", "ok")
        return redirect(url_for("auth.account"))
    return render_template("auth/account.html", colors=USER_COLORS)


@bp.route("/users", methods=["GET", "POST"])
@admin_required
def users():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        display_name = request.form.get("display_name", "").strip() or username
        password = request.form.get("password", "")
        if not username or len(password) < MIN_PASSWORD_LENGTH:
            flash(f"Username and a password of at least {MIN_PASSWORD_LENGTH} characters are required.", "error")
        elif User.query.filter_by(username=username).first():
            flash("That username is taken.", "error")
        else:
            count = User.query.count()
            user = User(
                username=username,
                display_name=display_name,
                is_admin=bool(request.form.get("is_admin")),
                color=USER_COLORS[count % len(USER_COLORS)],
            )
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash(f"Added {display_name}.", "ok")
        return redirect(url_for("auth.users"))
    return render_template("auth/users.html", users=User.query.order_by(User.display_name).all())


@bp.route("/users/<int:user_id>/password", methods=["POST"])
@admin_required
def reset_password(user_id):
    user = db.get_or_404(User, user_id)
    password = request.form.get("password", "")
    if len(password) < MIN_PASSWORD_LENGTH:
        flash(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.", "error")
    else:
        user.set_password(password)
        db.session.commit()
        flash(f"Password reset for {user.display_name}.", "ok")
    return redirect(url_for("auth.users"))


@bp.route("/users/<int:user_id>/admin", methods=["POST"])
@admin_required
def toggle_admin(user_id):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        abort(400, "You can't remove your own admin rights.")
    user.is_admin = not user.is_admin
    db.session.commit()
    return redirect(url_for("auth.users"))


@bp.route("/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete_user(user_id):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        abort(400, "You can't delete yourself.")
    db.session.delete(user)
    db.session.commit()
    flash(f"Removed {user.display_name}.", "ok")
    return redirect(url_for("auth.users"))
