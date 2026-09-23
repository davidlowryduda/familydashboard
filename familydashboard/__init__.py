import os

from flask import Flask, redirect, request, url_for
from flask_login import current_user
from loguru import logger
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config
from .extensions import csrf, db, login_manager, migrate
from .logs import configure_logging

# Endpoints reachable without logging in.
PUBLIC_ENDPOINTS = {"auth.login", "static"}


def create_app(config_class: type = Config) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        os.makedirs(app.instance_path, exist_ok=True)
        db_path = os.path.join(app.instance_path, "familydashboard.sqlite3")
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    configure_logging(app)
    if app.config["BEHIND_PROXY"]:
        # Trust exactly one proxy hop for client IP, scheme and host.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    if app.config["SECRET_KEY"] == Config.SECRET_KEY and not app.testing:
        logger.warning("SECRET_KEY is the development default; set it in .env before real use")

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
    from .calendar.routes import bp as calendar_bp
    from .lists.routes import bp as lists_bp
    from .main.routes import bp as main_bp
    from .messages.routes import bp as messages_bp
    from .recipes.routes import bp as recipes_bp
    from .todos.routes import bp as todos_bp

    for bp in (auth_bp, main_bp, calendar_bp, todos_bp, messages_bp, lists_bp, recipes_bp):
        app.register_blueprint(bp)

    from . import template_helpers

    template_helpers.register(app)

    from .cli import register_cli

    register_cli(app)
    logger.debug("App created (database: {})", app.config["SQLALCHEMY_DATABASE_URI"])
    return app
