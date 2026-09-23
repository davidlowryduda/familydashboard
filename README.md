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

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env              # set SECRET_KEY and FAMILY_TZ
.venv/bin/flask db upgrade        # creates instance/familydashboard.sqlite3
.venv/bin/flask create-user mom --name Mom --admin
.venv/bin/flask run --host 0.0.0.0
```

Open http://localhost:5000 and log in. Add the rest of the family under **Users** (top right, admins only).

To try things out with sample data instead, run this on an empty database:

```bash
.venv/bin/flask seed-demo         # users mom, dad, sam, alex; password family123
```

## Configuration (`.env`)

| Variable | Default | Meaning |
| --- | --- | --- |
| `SECRET_KEY` | dev value | **Set this** to a long random string. It signs login cookies. |
| `FAMILY_TZ` | `America/New_York` | Timezone for displaying and entering times. |
| `DATABASE_URL` | `instance/familydashboard.sqlite3` | SQLAlchemy URL if you want the DB elsewhere. |
| `CALENDAR_STALE_MINUTES` | `15` | How old a calendar feed can get before opening the calendar refreshes it. |

## Useful commands

```bash
flask create-user NAME [--name "Display"] [--admin]
flask reset-password NAME
flask sync-calendars              # refresh all calendar feeds
flask seed-demo                   # demo data (empty DB only)
flask db migrate -m "..." && flask db upgrade   # after changing models.py
pytest                            # run the tests
```

## Connecting Google / Outlook calendars

On the dashboard, go to **Calendar → Calendars**, and paste the calendar's secret ICS link. The page explains where to find it for Google, Outlook and iCloud.

- Events are **read-only**; change them in Google or Outlook.
- Events refresh in the background when someone opens the calendar and the feed is more than 15 minutes old. You can also press Refresh, or run cron:

```cron
*/30 * * * * cd /path/to/familydashboard && .venv/bin/flask sync-calendars >/dev/null
```

## Running it for real

For anything beyond your laptop, use gunicorn instead of `flask run`:

```bash
.venv/bin/pip install -e '.[prod]'
.venv/bin/gunicorn -w 2 -b 0.0.0.0:8000 "familydashboard:create_app()"
```

Options for later:

- **Raspberry Pi or home server**: run gunicorn from a systemd unit with `WorkingDirectory` set to the checkout and `EnvironmentFile` pointing at `.env`.
- **Access away from home**: don't expose it to the internet directly. [Tailscale](https://tailscale.com) (or another VPN) gives every family phone access with zero port forwarding. If you do expose it, put it behind HTTPS (Caddy or nginx), and set `SESSION_COOKIE_SECURE=True` / `REMEMBER_COOKIE_SECURE=True` in `config.py`.
- **Docker**: a slim Python image that runs the gunicorn command above, with `instance/` mounted as a volume so the SQLite file survives upgrades.
- **Backups**: all data lives in the one SQLite file. `sqlite3 instance/familydashboard.sqlite3 ".backup backup.sqlite3"` is safe to run while the app is up.

## Project layout

```
familydashboard/
  __init__.py        app factory; every page requires login except /login
  models.py          all database tables
  services/          recipe expansion, quantity parsing, ICS sync, calendar queries
  auth/ main/ todos/ messages/ lists/ recipes/ calendar/   one blueprint per area
  templates/ static/ Jinja templates, CSS and vendored htmx
migrations/          Alembic migrations (flask db ...)
tests/               pytest suite
```
