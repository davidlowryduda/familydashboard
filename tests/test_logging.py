import logging

from familydashboard.models import CalendarFeed
from familydashboard.services import ics

from .conftest import login
from .test_calendar import fake_get


def messages(records, level):
    return [r["message"] for r in records if r["level"].name == level]


def test_failed_login_is_logged(app, parent, logs):
    login(app.test_client(), "mom", "wrong")
    assert any("Failed login for 'mom'" in m for m in messages(logs, "WARNING"))


def test_successful_login_is_logged(app, parent, logs):
    login(app.test_client(), "mom")
    assert any(m.startswith("mom logged in") for m in messages(logs, "INFO"))


def test_feed_failure_logged_without_secret_url(app, parent, logs):
    feed = CalendarFeed(owner_id=parent.id, name="Work", ics_url="https://example.com/private-token/basic.ics")
    from familydashboard.extensions import db

    db.session.add(feed)
    db.session.commit()
    err = ics.requests.HTTPError(f"500 Server Error: oops for url: {feed.ics_url}")
    with fake_get() as get:
        get.return_value.raise_for_status.side_effect = err
        ics.sync_feed(feed)
    assert "private-token" not in feed.last_error and "<feed url>" in feed.last_error
    warnings = messages(logs, "WARNING")
    assert any("'Work'" in m and "failed to sync" in m for m in warnings)
    assert not any("private-token" in m for m in warnings)


def test_standard_logging_is_routed_to_loguru(app, logs):
    logging.getLogger("werkzeug").warning("hello from werkzeug")
    assert "hello from werkzeug" in messages(logs, "WARNING")



def test_default_secret_key_warning_only_for_default(monkeypatch):
    import familydashboard
    from familydashboard.config import DEV_SECRET_KEY, Config, TestConfig

    def warnings_for(key):
        seen = []
        monkeypatch.setattr(familydashboard.logger, "warning", lambda msg, *a: seen.append(msg))
        monkeypatch.setattr(Config, "SECRET_KEY", key)  # as if SECRET_KEY came from .env

        class Cfg(TestConfig):
            TESTING = False
            SECRET_KEY = key

        familydashboard.create_app(Cfg)
        return [m for m in seen if "SECRET_KEY" in m]

    assert warnings_for(DEV_SECRET_KEY)
    assert not warnings_for("a-real-secret")
