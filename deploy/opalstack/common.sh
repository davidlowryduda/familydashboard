# Shared setup for the Opalstack control scripts. Sourced, not run directly.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$APP_DIR"

if [ ! -f .env ]; then
    echo "Missing $APP_DIR/.env; copy deploy/opalstack/env.example to .env and fill it in." >&2
    exit 1
fi
set -a
# shellcheck disable=SC1091
source .env
set +a

: "${PORT:?Set PORT in .env to the port Opalstack assigned to the app}"
LOG_DIR="${LOG_DIR:-$APP_DIR/instance/logs}"
PIDFILE="$APP_DIR/instance/gunicorn.pid"
UV="${UV:-$(command -v uv || echo "$HOME/.local/bin/uv")}"
mkdir -p "$APP_DIR/instance" "$LOG_DIR"

# With gunicorn daemonized, stderr goes nowhere, so app logs need a file.
export LOG_FILE="${LOG_FILE:-$LOG_DIR/app.log}"

is_running() {
    [ -f "$PIDFILE" ] || return 1
    local pid
    pid="$(cat "$PIDFILE")"
    kill -0 "$pid" 2>/dev/null || return 1
    # Must be a live gunicorn (not a zombie, not an unrelated process reusing the pid).
    [[ "$(ps -p "$pid" -o stat= 2>/dev/null)" != Z* ]] && ps -p "$pid" -o args= | grep -q gunicorn
}
