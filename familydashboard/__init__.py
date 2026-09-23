import os

from flask import Flask, redirect, request, url_for
from flask_login import current_user

from .config import Config
from .extensions import csrf, db, login_manager, migrate

# Endpoints reachable without logging in.
PUBLIC_ENDPOINTS = {"auth.login", "static"}


def create_app(config_class: type = Config) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        os.makedirs(app.instance_path, exist_ok=True)
        db_path = os.path.join(app.instance_path, "familydashboard.sqlite3")
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = None

    from . import models

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(models.User, int(user_id))

    @app.before_request
    def require_login():
        if request.endpoint in PUBLIC_ENDPOINTS or current_user.is_authenticated:
            return None
        return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))

    from .auth.routes import bp as auth_bp
    from .main.routes import bp as main_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    from . import template_helpers

    template_helpers.register(app)

    from .cli import register_cli

    register_cli(app)
    return app
