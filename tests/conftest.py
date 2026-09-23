import pytest
from flask import g
from flask.testing import FlaskClient

from familydashboard import create_app
from familydashboard.config import TestConfig
from familydashboard.extensions import db
from familydashboard.models import User


class Client(FlaskClient):
    """Tests keep one app context open so they can use the db directly.

    Flask reuses that context (and ``g``) for every request, so drop
    Flask-Login's cached user to let each client act as its own user.
    """

    def open(self, *args, **kwargs):
        g.pop("_login_user", None)
        return super().open(*args, **kwargs)


@pytest.fixture
def app():
    app = create_app(TestConfig)
    app.test_client_class = Client
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def make_user(username, password="secret1", admin=False, name=None):
    user = User(username=username, display_name=name or username.capitalize(), is_admin=admin)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def parent(app):
    return make_user("mom", admin=True)


@pytest.fixture
def kid(app):
    return make_user("sam")


def login(client, username, password="secret1"):
    return client.post("/login", data={"username": username, "password": password})


@pytest.fixture
def client(app, parent):
    """A client logged in as the admin parent."""
    c = app.test_client()
    login(c, "mom")
    return c


@pytest.fixture
def kid_client(app, kid):
    c = app.test_client()
    login(c, "sam")
    return c
