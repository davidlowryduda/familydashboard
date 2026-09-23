import os
from datetime import timedelta


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    # When unset, create_app() points this at instance/familydashboard.sqlite3.
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    FAMILY_TZ = os.environ.get("FAMILY_TZ", "America/New_York")

    # Loguru level (TRACE, DEBUG, INFO, WARNING, ...). LOG_FILE adds a rotating file sink.
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
    LOG_FILE = os.environ.get("LOG_FILE")

    # Shared kitchen tablets stay logged in for a long time when "remember me" is ticked.
    REMEMBER_COOKIE_DURATION = timedelta(days=90)
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SAMESITE = "Lax"

    # Calendar feeds older than this are re-fetched when the calendar page is opened.
    CALENDAR_STALE_MINUTES = int(os.environ.get("CALENDAR_STALE_MINUTES", "15"))
    CALENDAR_PAST_DAYS = 30
    CALENDAR_FUTURE_DAYS = 180
    CALENDAR_FETCH_TIMEOUT = 15


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
    LOG_LEVEL = "WARNING"
    LOG_FILE = None
    FAMILY_TZ = "America/New_York"
