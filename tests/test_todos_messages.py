from familydashboard.models import Message, Todo

HX = {"HX-Request": "true"}


def test_todo_lifecycle(client, kid):
    resp = client.post("/todos/", data={"title": "Take out trash", "assigned_to_id": str(kid.id), "due_date": "2030-01-02"}, headers=HX)
    assert resp.status_code == 200
    assert b"Take out trash" in resp.data
    todo = Todo.query.one()
    assert todo.assigned_to_id == kid.id
    assert str(todo.due_date) == "2030-01-02"

    resp = client.post(f"/todos/{todo.id}/toggle", headers=HX)
    assert b"checked" in resp.data
    assert todo.done and todo.done_at is not None

    assert b"Take out trash" not in client.get("/todos/?filter=open").data
    assert b"Take out trash" in client.get("/todos/?filter=done").data

    client.post(f"/todos/{todo.id}/toggle")
    assert not todo.done and todo.done_at is None

    client.post(f"/todos/{todo.id}/delete", headers=HX)
    assert Todo.query.count() == 0


def test_todo_blank_title_ignored(client):
    client.post("/todos/", data={"title": "   "})
    assert Todo.query.count() == 0


def test_mine_filter(client, kid_client, kid):
    client.post("/todos/", data={"title": "Homework", "assigned_to_id": str(kid.id)})
    client.post("/todos/", data={"title": "Pay bills"})
    page = kid_client.get("/todos/?filter=mine").data
    assert b"Homework" in page and b"Pay bills" not in page


def test_clear_done(client):
    client.post("/todos/", data={"title": "a"})
    client.post("/todos/", data={"title": "b"})
    client.post(f"/todos/{Todo.query.filter_by(title='a').one().id}/toggle")
    client.post("/todos/clear-done")
    assert [t.title for t in Todo.query.all()] == ["b"]


def test_edit_todo(client):
    client.post("/todos/", data={"title": "a"})
    todo = Todo.query.one()
    client.post(f"/todos/{todo.id}/edit", data={"title": "Renamed", "notes": "hi", "due_date": "", "assigned_to_id": ""})
    assert todo.title == "Renamed" and todo.notes == "hi"


def test_post_and_delete_message(client):
    resp = client.post("/board/", data={"body": "Soccer at 5!"}, headers=HX)
    assert b"Soccer at 5!" in resp.data
    msg = Message.query.one()
    assert b"Soccer at 5!" in client.get("/board/").data
    client.post(f"/board/{msg.id}/delete", headers=HX)
    assert Message.query.count() == 0


def test_message_body_is_escaped(client):
    client.post("/board/", data={"body": "<script>alert(1)</script>"})
    assert b"<script>alert(1)</script>" not in client.get("/board/").data


def test_only_author_or_admin_can_modify(client, kid_client):
    client.post("/board/", data={"body": "from mom"})
    mom_msg = Message.query.one()
    assert kid_client.post(f"/board/{mom_msg.id}/delete").status_code == 403
    assert kid_client.post(f"/board/{mom_msg.id}/edit", data={"body": "hacked"}).status_code == 403

    kid_client.post("/board/", data={"body": "from sam"})
    sam_msg = Message.query.filter_by(body="from sam").one()
    # Admins can moderate anyone's message.
    assert client.post(f"/board/{sam_msg.id}/delete").status_code == 302
    assert Message.query.count() == 1


def test_pinned_messages_first(client):
    client.post("/board/", data={"body": "older"})
    client.post("/board/", data={"body": "newer"})
    older = Message.query.filter_by(body="older").one()
    client.post(f"/board/{older.id}/pin")
    page = client.get("/board/").data.decode()
    assert page.index("older") < page.index("newer")
