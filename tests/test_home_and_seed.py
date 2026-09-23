from familydashboard.models import List, ListItem, Recipe, User
from familydashboard.seed import DEMO_PASSWORD, seed_demo

from .conftest import login


def test_home_shows_widgets(client, kid):
    client.post("/todos/", data={"title": "Mine to do", "assigned_to_id": ""})
    client.post("/board/", data={"body": "hello family"})
    client.post("/lists/", data={"name": "Groceries", "kind": "shopping"})
    page = client.get("/").data.decode()
    assert "hello family" in page
    assert "Groceries" in page
    assert "Nothing on the calendar today." in page


def test_seed_demo_builds_a_usable_family(app):
    seed_demo()
    assert User.query.count() == 4
    groceries = List.query.filter_by(name="Groceries").one()
    flour = next(i for i in groceries.items if i.text == "flour")
    assert flour.quantity == 3 and [r.name for r in flour.recipes] == ["Pizza night"]
    salt = [i for i in groceries.items if i.text == "salt" and i.unit == "tsp"][0]
    assert salt.quantity == 2.5  # 1 dough + 0.5 sauce + 1 tacos
    assert {r.name for r in salt.recipes} == {"Pizza night", "Tacos"}
    assert not any(i.text == "basil" for i in groceries.items)  # optional skipped
    assert Recipe.query.count() == 5

    c = app.test_client()
    login(c, "sam", DEMO_PASSWORD)
    for path in ["/", "/calendar/", "/calendar/agenda", "/calendar/feeds", "/todos/", "/board/", "/lists/",
                 f"/lists/{groceries.id}", "/recipes/", "/recipes/ingredients",
                 f"/recipes/{Recipe.query.filter_by(name='Pizza night').one().id}",
                 f"/lists/{groceries.id}/add-recipe?recipe=Pancakes&scale=2", "/account"]:
        assert c.get(path).status_code == 200, path
    assert ListItem.query.count() > 10
