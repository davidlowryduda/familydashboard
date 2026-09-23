import pytest

from familydashboard.extensions import db
from familydashboard.models import Ingredient, List, ListItem, Recipe, RecipeComponent
from familydashboard.services.quantities import parse_line
from familydashboard.services.recipes import (
    add_recipe_to_list,
    add_to_list,
    expand,
    merge_lines,
    remove_recipe_from_list,
    would_create_cycle,
)


def ing(name, category=None):
    return Ingredient.get_or_create(name, category)


def recipe(name, *components):
    r = Recipe(name=name)
    db.session.add(r)
    for n, (qty, unit, what) in enumerate(components):
        if isinstance(what, Recipe):
            r.components.append(RecipeComponent(subrecipe=what, quantity=qty, position=n))
        else:
            r.components.append(RecipeComponent(ingredient=ing(what), quantity=qty, unit=unit, position=n))
    db.session.add(r)
    db.session.commit()
    return r


@pytest.fixture
def pizza(app):
    dough = recipe("Pizza dough", (3, "cup", "flour"), (1, "tsp", "yeast"), (1, "tsp", "salt"))
    sauce = recipe("Tomato sauce", (1, "can", "crushed tomatoes"), (2, "clove", "garlic"), (0.5, "tsp", "salt"))
    return recipe("Pizza", (1, "", dough), (1, "", sauce), (8, "oz", "mozzarella"), (None, "", "basil"))


def test_expand_walks_chain_and_scales(pizza):
    lines = expand(pizza, scale=2)
    by_name = {(line.ingredient.name, line.unit): line for line in lines}
    assert by_name[("flour", "cup")].quantity == 6
    assert by_name[("flour", "cup")].path == ("Pizza", "Pizza dough")
    assert by_name[("mozzarella", "oz")].quantity == 16
    assert by_name[("basil", "")].quantity is None


def test_subrecipe_batches_multiply(app):
    inner = recipe("Inner", (2, "cup", "sugar"))
    middle = recipe("Middle", (3, "", inner))
    outer = recipe("Outer", (2, "", middle))
    [line] = expand(outer)
    assert line.quantity == 12
    assert line.path == ("Outer", "Middle", "Inner")


def test_merge_same_ingredient_and_unit(pizza):
    merged = {(m.ingredient.name, m.unit): m for m in merge_lines(expand(pizza))}
    assert merged[("salt", "tsp")].quantity == 1.5
    assert len(merged[("salt", "tsp")].paths) == 2


def test_different_units_stay_separate(app):
    r = recipe("Mixed", (1, "cup", "milk"), (2, "tbsp", "milk"))
    assert len(merge_lines(expand(r))) == 2


def test_cycle_detection(app):
    a = recipe("A", (1, "cup", "water"))
    b = recipe("B", (1, "", a))
    c = recipe("C", (1, "", b))
    assert would_create_cycle(a, c)  # A -> C -> B -> A
    assert would_create_cycle(a, a)
    assert not would_create_cycle(c, a)


def test_add_recipe_to_list_merges_and_tags(app, pizza):
    lst = List(name="Groceries", kind="shopping")
    db.session.add(lst)
    add_to_list(lst, ing("flour"), "flour", 2, "cup")  # already needed for something else
    add_recipe_to_list(lst, pizza)
    db.session.commit()

    flour = ListItem.query.filter_by(text="flour").one()
    assert flour.quantity == 5
    assert [r.name for r in flour.recipes] == ["Pizza"]
    assert flour.manual

    salt = ListItem.query.filter_by(text="salt").one()
    assert salt.quantity == 1.5
    # Optional-free: basil has no quantity but is still added.
    assert ListItem.query.filter_by(text="basil").one().quantity is None


def test_add_recipe_twice_accumulates(app, pizza):
    lst = List(name="Groceries", kind="shopping")
    db.session.add(lst)
    add_recipe_to_list(lst, pizza)
    add_recipe_to_list(lst, pizza)
    db.session.commit()
    assert ListItem.query.filter_by(text="mozzarella").one().quantity == 16


def test_excluded_and_optional(app):
    r = Recipe(name="Salad")
    r.components.append(RecipeComponent(ingredient=ing("lettuce"), quantity=1, unit="head"))
    r.components.append(RecipeComponent(ingredient=ing("croutons"), quantity=1, unit="cup", optional=True))
    r.components.append(RecipeComponent(ingredient=ing("olive oil"), quantity=2, unit="tbsp"))
    db.session.add(r)
    lst = List(name="G", kind="shopping")
    db.session.add(lst)
    add_recipe_to_list(lst, r, excluded_keys={(ing("olive oil").id, "tbsp")})
    db.session.commit()
    assert sorted(i.text for i in lst.items) == ["lettuce"]


def test_checked_items_are_not_merged_into(app, pizza):
    lst = List(name="G", kind="shopping")
    db.session.add(lst)
    item = add_to_list(lst, ing("mozzarella"), "mozzarella", 8, "oz")
    item.checked = True
    add_recipe_to_list(lst, pizza)
    db.session.commit()
    assert ListItem.query.filter_by(text="mozzarella").count() == 2


def test_remove_recipe_keeps_manual_quantities(app, pizza):
    taco = recipe("Tacos", (1, "tsp", "salt"), (1, "lb", "ground beef"))
    lst = List(name="G", kind="shopping")
    db.session.add(lst)
    add_to_list(lst, ing("flour"), "flour", 2, "cup")
    add_recipe_to_list(lst, pizza)
    add_recipe_to_list(lst, taco)
    db.session.commit()

    remove_recipe_from_list(lst, pizza)
    db.session.commit()
    remaining = {i.text: i for i in lst.items}
    assert remaining["flour"].quantity == 2 and remaining["flour"].recipes == []
    assert remaining["salt"].quantity == 1 and [r.name for r in remaining["salt"].recipes] == ["Tacos"]
    assert "mozzarella" not in remaining and "yeast" not in remaining
    assert "ground beef" in remaining


def test_ingredient_plural_matching(app):
    onion = ing("Onion")
    assert ing("onions").id == onion.id
    assert ing("  ONION ").id == onion.id
    tomato = ing("tomatoes")
    assert ing("tomato").id == tomato.id


@pytest.mark.parametrize("text,expected", [
    ("2 cups flour, sifted", (2, "cup", "flour", "sifted")),
    ("milk", (None, "", "milk", "")),
    ("1 1/2 tsp salt", (1.5, "tsp", "salt", "")),
    ("½ cup sugar", (0.5, "cup", "sugar", "")),
    ("a can of tomatoes", (1, "can", "tomatoes", "")),
    ("2-3 lbs chicken thighs", (3, "lb", "chicken thighs", "")),
    ("12 eggs", (12, "", "eggs", "")),
])
def test_parse_line(text, expected):
    p = parse_line(text)
    assert (p.quantity, p.unit, p.name, p.note) == expected


# --- HTTP level -------------------------------------------------------------

def test_shopping_list_flow(client, pizza):
    client.post("/lists/", data={"name": "Groceries", "kind": "shopping"})
    lst = List.query.one()
    client.post(f"/lists/{lst.id}/items", data={"text": "2 lbs apples"})
    client.post(f"/lists/{lst.id}/items", data={"text": "1 cup flour", "recipe_id": str(pizza.id)})

    preview = client.get(f"/lists/{lst.id}/add-recipe?recipe=pizza&scale=1")
    assert preview.status_code == 200
    assert b"via Pizza dough" in preview.data

    flour = Ingredient.find("flour")
    keep = [f"{flour.id}:cup", f"{Ingredient.find('mozzarella').id}:oz"]
    client.post(f"/lists/{lst.id}/add-recipe", data={"recipe": str(pizza.id), "scale": "1", "include": keep})
    items = {i.text: i for i in lst.items}
    assert items["flour"].quantity == 4
    assert items["mozzarella"].quantity == 8
    assert "yeast" not in items
    assert items["apples"].unit == "lb"

    page = client.get(f"/lists/{lst.id}").data.decode()
    assert "for Pizza" in page and "4 cups" in page


def test_list_toggle_and_clear(client):
    client.post("/lists/", data={"name": "Chores", "kind": "general"})
    lst = List.query.one()
    client.post(f"/lists/{lst.id}/items", data={"text": "2 socks"}, headers={"HX-Request": "true"})
    item = lst.items[0]
    assert item.text == "2 socks" and item.quantity is None  # plain lists don't parse
    client.post(f"/lists/{lst.id}/items/{item.id}/toggle", headers={"HX-Request": "true"})
    assert item.checked
    client.post(f"/lists/{lst.id}/clear-checked")
    assert ListItem.query.count() == 0


def test_recipe_crud_and_cycle_rejected(client):
    client.post("/recipes/new", data={"name": "Dough"})
    client.post("/recipes/new", data={"name": "Pizza"})
    dough, pizza = Recipe.query.filter_by(name="Dough").one(), Recipe.query.filter_by(name="Pizza").one()
    client.post(f"/recipes/{dough.id}/components", data={"kind": "ingredient", "text": "3 cups flour"})
    client.post(f"/recipes/{pizza.id}/components", data={"kind": "recipe", "subrecipe_id": str(dough.id), "quantity": "2"})
    assert pizza.components[0].subrecipe_id == dough.id and pizza.components[0].quantity == 2

    client.post(f"/recipes/{dough.id}/components", data={"kind": "recipe", "subrecipe_id": str(pizza.id)})
    assert len(dough.components) == 1  # cycle refused

    resp = client.post(f"/recipes/{dough.id}/delete")
    assert db.session.get(Recipe, dough.id) is not None  # still used by Pizza
    assert resp.status_code == 302

    found = client.get("/recipes/?q=flour").data
    assert b"<h2>Dough</h2>" in found and b"<h2>Pizza</h2>" not in found  # search matches direct ingredients
