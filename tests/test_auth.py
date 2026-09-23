from familydashboard.extensions import db
from familydashboard.models import User

from .conftest import login


def test_anonymous_redirected_to_login(app):
    resp = app.test_client().get("/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_login_page_is_public(app):
    assert app.test_client().get("/login").status_code == 200


def test_bad_login(app, parent):
    resp = login(app.test_client(), "mom", "wrong")
    assert resp.status_code == 401


def test_login_and_logout(app, parent):
    c = app.test_client()
    resp = login(c, "MOM")  # usernames are case-insensitive
    assert resp.status_code == 302
    assert c.get("/").status_code == 200
    c.post("/logout")
    assert c.get("/").status_code == 302


def test_login_next_is_local_only(app, parent):
    c = app.test_client()
    resp = c.post("/login?next=https://evil.example/", data={"username": "mom", "password": "secret1"})
    assert resp.headers["Location"] == "/"
    c.post("/logout")
    resp = c.post("/login?next=/account", data={"username": "mom", "password": "secret1"})
    assert resp.headers["Location"] == "/account"


def test_users_page_admin_only(client, kid_client):
    assert client.get("/users").status_code == 200
    assert kid_client.get("/users").status_code == 403
    assert kid_client.post("/users", data={"username": "x", "password": "secret1"}).status_code == 403


def test_admin_adds_user(client, app):
    client.post("/users", data={"username": "Dad", "display_name": "Dad", "password": "hunter22"})
    user = User.query.filter_by(username="dad").one()
    assert user.check_password("hunter22")
    assert not user.is_admin


def test_change_own_password(kid_client, kid):
    resp = kid_client.post("/account", data={"action": "password", "current": "secret1", "new": "newpass1", "confirm": "newpass1"})
    assert resp.status_code == 302
    db.session.refresh(kid)
    assert kid.check_password("newpass1")


def test_change_password_requires_current(kid_client, kid):
    kid_client.post("/account", data={"action": "password", "current": "nope", "new": "newpass1", "confirm": "newpass1"})
    db.session.refresh(kid)
    assert kid.check_password("secret1")


def test_admin_cannot_delete_self(client, parent):
    assert client.post(f"/users/{parent.id}/delete").status_code == 400
