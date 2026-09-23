"""Gunicorn settings: `gunicorn --config gunicorn.conf.py`.

Everything can be overridden from the environment or .env (loaded here,
because gunicorn doesn't read .env on its own the way the flask CLI does).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

wsgi_app = "familydashboard:create_app()"

# Listen only on localhost; a reverse proxy (e.g. Opalstack's nginx) faces the internet.
bind = os.environ.get("GUNICORN_BIND") or f"127.0.0.1:{os.environ.get('PORT', '8000')}"

# One process with a few threads is plenty for a family. It also keeps SQLite
# writes and loguru's LOG_FILE rotation in a single process.
workers = int(os.environ.get("GUNICORN_WORKERS", "1"))
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
timeout = 60  # calendar feed syncs can take a while on slow upstreams

# Request lines go through loguru (see familydashboard/logs.py) when enabled.
accesslog = "-" if os.environ.get("ACCESS_LOG", "").lower() in {"1", "true", "yes", "on"} else None
