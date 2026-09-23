# Family Dashboard

A small self-hosted dashboard for the family: calendar, todos, message board, lists and recipes.
Flask + SQLite + htmx.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env            # then edit SECRET_KEY and FAMILY_TZ
.venv/bin/flask db upgrade
.venv/bin/flask create-user mom --name Mom --admin
.venv/bin/flask run
```
