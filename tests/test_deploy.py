import pytest

from familydashboard import create_app
from familydashboard.config import TestConfig
from familydashboard.extensions import db

from .conftest import make_user


class ProxiedConfig(TestConfig):
    BEHIND_PROXY = True
    SESSION_COOKIE_SECURE = REMEMBER_COOKIE_SECURE = True


@pytest.fixture
def proxied_app():
    # Created before the `logs` fixture: create_app() resets loguru's sinks.
    app = create_app(ProxiedConfig)
    with app.app_context():
        db.create_all()
        make_user("mom")
        yield app
        db.session.remove()
        db.drop_all()


def test_proxy_headers_are_trusted_when_enabled(proxied_app, logs):
    resp = proxied_app.test_client().post(
        "/login",
        data={"username": "mom", "password": "secret1", "remember": "on"},
        headers={"X-Forwarded-For": "203.0.113.7", "X-Forwarded-Proto": "https"},
    )
    assert resp.status_code == 302
    cookies = resp.headers.getlist("Set-Cookie")
    assert cookies and all("Secure" in c for c in cookies)
    assert any("logged in from 203.0.113.7" in r["message"] for r in logs)


def test_proxy_headers_ignored_by_default(app, parent, logs):
    app.test_client().post(
        "/login", data={"username": "mom", "password": "secret1"}, headers={"X-Forwarded-For": "203.0.113.7"}
    )
    assert not any("203.0.113.7" in r["message"] for r in logs)


def test_backup_db_copies_and_prunes(tmp_path):
    import sqlite3

    from familydashboard.config import TestConfig as Base

    class FileConfig(Base):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'live.sqlite3'}"

    app = create_app(FileConfig)
    with app.app_context():
        db.create_all()
        make_user("mom")
    dest = tmp_path / "backups"
    for n in range(3):
        (dest / f"familydashboard-2000010{n}-000000.sqlite3").parent.mkdir(exist_ok=True)
        (dest / f"familydashboard-2000010{n}-000000.sqlite3").write_bytes(b"")
    result = app.test_cli_runner().invoke(args=["backup-db", "--dir", str(dest), "--keep", "2"])
    assert result.exit_code == 0, result.output
    files = sorted(dest.glob("*.sqlite3"))
    assert len(files) == 2 and "20000102" in files[0].name
    with sqlite3.connect(files[-1]) as conn:
        assert conn.execute("select username from user").fetchall() == [("mom",)]


def test_backup_db_refuses_memory_database(app):
    result = app.test_cli_runner().invoke(args=["backup-db"])
    assert result.exit_code != 0 and "file-based SQLite" in result.output
