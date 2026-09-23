# Deploying on Opalstack

This follows Opalstack's own pattern for Python servers:

- The app is a **Proxied Port** application, bound to `127.0.0.1:<port>`.
- A `start` script uses a pidfile.
- Cron re-runs `start` every 10 minutes to revive it if it stopped.
- Opalstack's nginx sits in front and handles the domain and HTTPS (Let's Encrypt).

The scripts live in [`deploy/opalstack/`](../deploy/opalstack/). Paths below assume your shell user is `USER` and the app is named `familydashboard`.

## 1. Control panel

1. **Applications → Add Application.**
   - Type: **Proxied Port** (listed as "CUS - Proxied Port" in some places).
   - Name: `familydashboard`.
   - Note the **port** it's assigned.
2. **Domains:** add the domain you'll use, e.g. `family.example.com`, and point its DNS at Opalstack.
3. **Sites → Add Site.**
   - Select that domain.
   - Route `/` to the `familydashboard` app. Serve it at the root of a (sub)domain, not under a sub-path.
   - Turn on **Let's Encrypt** and **redirect HTTP to HTTPS**.

## 2. First install (over SSH)

```bash
# uv (installs to ~/.local/bin; it also fetches its own Python 3.11)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Code goes into the app directory Opalstack created
cd ~/apps/familydashboard
git clone https://github.com/davidlowryduda/familydashboard.git .   # add -b BRANCH to deploy a specific branch

# Configuration
cp deploy/opalstack/env.example .env
chmod 600 .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # paste as SECRET_KEY
nano .env          # set PORT, SECRET_KEY, FAMILY_TZ and the USER in LOG_DIR

# Install, migrate, start
deploy/opalstack/update
.venv/bin/flask create-user mom --name Mom --admin
```

If `git clone` complains that the directory isn't empty, move Opalstack's placeholder files aside first.

Open `https://family.example.com`, log in, and add the rest of the family under **Users**.

## 3. Cron

```bash
crontab -e
```

Paste in the lines from [`deploy/opalstack/crontab.example`](../deploy/opalstack/crontab.example), with `USER` replaced. They set up:

- the keep-alive every 10 minutes;
- a calendar feed refresh every 30 minutes;
- a nightly database backup.

## Day-to-day

| Task | Command (from `~/apps/familydashboard`) |
| --- | --- |
| Deploy new code | `deploy/opalstack/update` (pull, `uv sync --frozen`, back up the DB, migrate, restart) |
| Restart after editing `.env` | `deploy/opalstack/restart` |
| Stop / start | `deploy/opalstack/stop`, `deploy/opalstack/start` |
| App logs | `~/logs/apps/familydashboard/app.log` (rotated at 10 MB) |
| Gunicorn startup errors | `~/logs/apps/familydashboard/gunicorn.log` |
| Cron job logs | `~/logs/apps/familydashboard/cron.log` |
| Backups | `instance/backups/` (newest 14 kept) |

The database is `instance/familydashboard.sqlite3`. Copy a backup off the server now and then, for example with `scp` or `rsync` from home.

## Notes

- **Client IPs.** After the first login, check `app.log`. The "logged in from ..." line should show your home IP, not `127.0.0.1`. If it shows `127.0.0.1`, the proxy isn't sending `X-Forwarded-For`, so set `BEHIND_PROXY=false` in `.env`. Everything else still works.
- **HTTPS-only cookies.** `SECURE_COOKIES=true` means login cookies are only sent over HTTPS. Keep the site on HTTPS, or logins will silently fail.
- **Resources.** One gunicorn process with 4 threads (`gunicorn.conf.py`) uses little memory. You can tune it with `GUNICORN_THREADS` / `GUNICORN_WORKERS` in `.env`, but keep one worker: log rotation and SQLite writes assume a single process.
- **Python version.** `uv sync` uses the Python pinned in `.python-version`, downloading it if the server doesn't have it. That build ships a current SQLite, independent of the system's.
