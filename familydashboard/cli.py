from pathlib import Path

import click
from flask import Flask
from loguru import logger

from .extensions import db
from .models import USER_COLORS, CalendarFeed, User


def register_cli(app: Flask) -> None:
    @app.cli.command("create-user")
    @click.argument("username")
    @click.option("--name", "display_name", help="Display name (defaults to the username).")
    @click.option("--admin", is_flag=True, help="Give this user admin rights.")
    @click.password_option()
    def create_user(username, display_name, admin, password):
        """Create a family member account."""
        username = username.strip().lower()
        if User.query.filter_by(username=username).first():
            raise click.ClickException(f"User {username!r} already exists.")
        count = User.query.count()
        user = User(
            username=username,
            display_name=display_name or username.capitalize(),
            is_admin=admin,
            color=USER_COLORS[count % len(USER_COLORS)],
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        logger.info("Created {}user {} from the CLI", "admin " if admin else "", username)

    @app.cli.command("reset-password")
    @click.argument("username")
    @click.password_option()
    def reset_password(username, password):
        """Set a new password for an existing user."""
        user = User.query.filter_by(username=username.strip().lower()).first()
        if user is None:
            raise click.ClickException(f"No user {username!r}.")
        user.set_password(password)
        db.session.commit()
        logger.info("Reset the password for {} from the CLI", user.username)

    @app.cli.command("sync-calendars")
    def sync_calendars():
        """Refresh every subscribed calendar feed (run from cron). Exits 1 if any feed failed."""
        from .services.ics import sync_feed

        feeds = CalendarFeed.query.all()
        failed = [feed.name for feed in feeds if not sync_feed(feed)]  # each result is logged
        logger.info("Calendar sync finished: {} ok, {} failed", len(feeds) - len(failed), len(failed))
        if failed:
            raise SystemExit(1)

    @app.cli.command("seed-demo")
    def seed_demo_command():
        """Fill an empty database with a demo family, recipes, lists and events."""
        from .seed import seed_demo

        if User.query.count():
            raise click.ClickException("The database already has users; seed-demo only runs on an empty database.")
        info = seed_demo()
        logger.info("Seeded demo data")
        click.echo(f"Seeded demo data. Log in as {', '.join(info['users'])} with password {info['password']!r}.")

    @app.cli.command("backup-db")
    @click.option("--dir", "dest", type=click.Path(file_okay=False, path_type=Path),
                  help="Where to put backups (default: instance/backups).")
    @click.option("--keep", default=14, show_default=True, help="How many backups to keep; older ones are deleted.")
    def backup_db(dest, keep):
        """Back up the SQLite database (safe while the app is running)."""
        from .backup import backup

        dest = dest or Path(app.instance_path) / "backups"
        try:
            target, pruned = backup(app.config["SQLALCHEMY_DATABASE_URI"], dest, keep)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        logger.info("Backed up database to {} (pruned {} old backups)", target, len(pruned))
