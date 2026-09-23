"""Online SQLite backups (safe while the app is serving requests)."""

import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import make_url

PREFIX = "familydashboard-"


def sqlite_path(database_uri: str) -> Path:
    url = make_url(database_uri)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise ValueError("Backups are only supported for a file-based SQLite database.")
    return Path(url.database)


def backup(database_uri: str, dest_dir: Path, keep: int) -> tuple[Path, list[Path]]:
    """Copy the database into dest_dir with SQLite's backup API. Returns (new file, pruned files)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"{PREFIX}{datetime.now():%Y%m%d-%H%M%S}.sqlite3"
    src = sqlite3.connect(sqlite_path(database_uri))
    dst = sqlite3.connect(target)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()

    existing = sorted(dest_dir.glob(f"{PREFIX}*.sqlite3"))
    pruned = existing[:-keep] if keep > 0 else []
    for old in pruned:
        old.unlink()
    return target, pruned
