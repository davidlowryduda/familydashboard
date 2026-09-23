# Family Dashboard

A small self-hosted dashboard for the family: **calendar**, **todos**, a **message board**, **lists**, and **recipes**.
It's built with Flask, SQLite and htmx. There's no JavaScript build step, and it works on phones, tablets and desktops.

## Features

- **Calendar**: family events (all-day or timed), plus read-only subscriptions to Google, Outlook or iCloud calendars through their secret ICS links. Month and 14-day agenda views.
- **Todos**: quick-add with an optional assignee and due date. Tap to check off, and filter by open, mine or done.
- **Message board**: one-to-all notes. Pin important ones. Only the author or an admin can edit or delete a message.
- **Lists**: plain checklists, or shopping lists where:
  - you type items naturally (`2 lbs apples`, `1 1/2 cups flour`) and they're matched to shared ingredients;
  - items are grouped by store section;
  - each item shows which recipe(s) it's **for**.
- **Recipes**: made from ingredients *and other recipes*. For example, *Pizza night* uses *Pizza dough* and *Tomato sauce*.
  - Adding a recipe to a shopping list expands the whole chain, scales it, merges duplicates (e.g. salt from dough + sauce), and lets you untick what's already in the pantry.
  - Taking a recipe off a list removes only what that recipe added.
- **Accounts**: one login per family member. Admins (parents) add people and reset passwords.

## Quick start

The project is managed with [uv](https://docs.astral.sh/uv/). It pins Python in `.python-version` and exact dependency versions in `uv.lock`.

```bash
uv sync                           # creates .venv with the app and dev tools
cp .env.example .env              # set SECRET_KEY and FAMILY_TZ
uv run flask db upgrade           # creates instance/familydashboard.sqlite3
uv run flask create-user mom --name Mom --admin
uv run flask run --host 0.0.0.0
```

Open http://localhost:5000 and log in. Add the rest of the family under **Users** (top right, admins only).

To try things out with sample data instead, run this on an empty database:

```bash
uv run flask seed-demo            # users mom, dad, sam, alex; password family123
```

## Configuration (`.env`)

| Variable | Default | Meaning |
| --- | --- | --- |
| `SECRET_KEY` | dev value | **Set this** to a long random string. It signs login cookies. |
| `FAMILY_TZ` | `America/New_York` | Timezone for displaying and entering times. |
| `DATABASE_URL` | `instance/familydashboard.sqlite3` | SQLAlchemy URL if you want the DB elsewhere. |
| `CALENDAR_STALE_MINUTES` | `15` | How old a calendar feed can get before opening the calendar refreshes it. |
| `BEHIND_PROXY` | `false` | Trust one reverse proxy's `X-Forwarded-For/Proto/Host` headers (real client IPs, https URLs). |
| `SECURE_COOKIES` | `false` | Send login cookies only over HTTPS. Turn on once the site is served over HTTPS. |
| `LOG_LEVEL` | `INFO` | Loguru level: `DEBUG`, `INFO`, `WARNING`, ... (`TRACE` also shows SQL). |
| `LOG_FILE` | unset | Also write logs to this file, rotated at 10 MB with 5 old files kept. |

## Logging

Logging uses [loguru](https://github.com/Delgan/loguru). Log messages from Flask, werkzeug, gunicorn and SQLAlchemy are routed through it too, so everything shares one format on stderr (and in `LOG_FILE` if set).

The app logs:

- logins, including failed attempts with the remote address;
- user management;
- calendar sync results and timings (secret feed URLs are redacted);
- recipes added to or removed from lists.

In code, use `from loguru import logger`.

## Useful commands

```bash
uv run flask create-user NAME [--name "Display"] [--admin]
uv run flask reset-password NAME
uv run flask sync-calendars       # refresh all calendar feeds
uv run flask seed-demo            # demo data (empty DB only)
uv run flask backup-db [--dir DIR] [--keep 14]   # online SQLite backup, prunes old copies
uv run flask db migrate -m "..." && uv run flask db upgrade   # after changing models.py
uv run pytest                     # run the tests
uv add PACKAGE                    # add a dependency (updates pyproject.toml and uv.lock)
```

`FLASK_APP` is set in the committed `.flaskenv`, so the `flask` commands work without extra setup.

## Connecting Google / Outlook calendars

On the dashboard, go to **Calendar → Calendars**, and paste the calendar's secret ICS link. The page explains where to find it for Google, Outlook and iCloud.

- Events are **read-only**; change them in Google or Outlook.
- Events refresh in the background when someone opens the calendar and the feed is more than 15 minutes old. You can also press Refresh, or run cron:

```cron
*/30 * * * * cd /path/to/familydashboard && uv run --no-dev flask sync-calendars
```

## Running it for real

**Opalstack:** follow [docs/deploy-opalstack.md](docs/deploy-opalstack.md). The scripts in `deploy/opalstack/` handle start, stop, keep-alive, redeploys and backups.


For anything beyond your laptop, use gunicorn instead of `flask run`:

```bash
uv sync --no-dev --extra prod
uv run --no-dev --extra prod gunicorn -w 2 -b 0.0.0.0:8000 "familydashboard:create_app()"
```

Options for later:

- **Raspberry Pi or home server**: run the gunicorn command above from a systemd unit with `WorkingDirectory` set to the checkout and `EnvironmentFile` pointing at `.env`.
- **Access away from home**: don't expose it to the internet directly. [Tailscale](https://tailscale.com) (or another VPN) gives every family phone access with zero port forwarding. If you do expose it, serve it over HTTPS behind a reverse proxy and set `BEHIND_PROXY=true` and `SECURE_COOKIES=true`.
- **Docker**: a slim Python image that runs the gunicorn command above, with `instance/` mounted as a volume so the SQLite file survives upgrades.
- **Backups**: all data lives in the one SQLite file. `uv run flask backup-db` copies it safely while the app is running, into `instance/backups/`, and keeps the newest 14 copies. Run it from cron, and copy the backups off the server now and then.

## Project layout

```
familydashboard/
  __init__.py        app factory; every page requires login except /login
  models.py          all database tables
  logs.py            loguru setup (routes standard logging into loguru)
  services/          recipe expansion, quantity parsing, ICS sync, calendar queries
  auth/ main/ todos/ messages/ lists/ recipes/ calendar/   one blueprint per area
  templates/ static/ Jinja templates, CSS and vendored htmx
deploy/opalstack/    start/stop/restart/update scripts, .env and crontab templates
docs/                deployment guide
gunicorn.conf.py     production server settings (reads .env)
migrations/          Alembic migrations (flask db ...)
tests/               pytest suite
```
