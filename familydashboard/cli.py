import click
from flask import Flask

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
        click.echo(f"Created {'admin ' if admin else ''}user {username}.")

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
        click.echo(f"Password updated for {user.username}.")

    @app.cli.command("sync-calendars")
    def sync_calendars():
        """Refresh every subscribed calendar feed (run from cron)."""
        from .services.ics import sync_feed

        for feed in CalendarFeed.query.all():
            ok = sync_feed(feed)
            click.echo(f"{'ok  ' if ok else 'FAIL'} {feed.name}" + ("" if ok else f": {feed.last_error}"))

    @app.cli.command("seed-demo")
    def seed_demo_command():
        """Fill an empty database with a demo family, recipes, lists and events."""
        from .seed import seed_demo

        if User.query.count():
            raise click.ClickException("The database already has users; seed-demo only runs on an empty database.")
        info = seed_demo()
        click.echo(f"Seeded demo data. Log in as {', '.join(info['users'])} with password {info['password']!r}.")
