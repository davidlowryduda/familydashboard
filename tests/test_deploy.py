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
