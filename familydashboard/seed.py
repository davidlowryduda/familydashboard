"""Demo data so a fresh install has something to click around in."""

from datetime import datetime, time, timedelta

from .extensions import db
from .models import USER_COLORS, Event, Ingredient, List, ListItem, Message, Recipe, RecipeComponent, Todo, User
from .services.quantities import parse_line
from .services.recipes import add_recipe_to_list, add_to_list
from .timeutil import local_today, to_utc_naive

DEMO_PASSWORD = "family123"


def _recipe(name, servings, lines, instructions=""):
    r = Recipe(name=name, servings=servings, instructions=instructions)
    db.session.add(r)
    for n, line in enumerate(lines):
        if isinstance(line, tuple):  # (batches, sub-recipe)
            r.components.append(RecipeComponent(subrecipe=line[1], quantity=line[0], position=n))
            continue
        optional = line.endswith("(optional)")
        p = parse_line(line.removesuffix("(optional)").strip())
        r.components.append(RecipeComponent(
            ingredient=Ingredient.get_or_create(p.name), quantity=p.quantity, unit=p.unit,
            note=p.note, optional=optional, position=n,
        ))
    return r


def seed_demo() -> dict:
    people = [("mom", "Mom", True), ("dad", "Dad", True), ("sam", "Sam", False), ("alex", "Alex", False)]
    users = {}
    for n, (username, name, admin) in enumerate(people):
        u = User(username=username, display_name=name, is_admin=admin, color=USER_COLORS[n])
        u.set_password(DEMO_PASSWORD)
        db.session.add(u)
        users[username] = u
    db.session.flush()

    dough = _recipe("Pizza dough", None, [
        "3 cups flour", "1 tsp yeast", "1 tsp salt", "1 tsp sugar", "2 tbsp olive oil", "1 cup warm water",
    ], "Mix, knead 8 minutes, let rise 1 hour.")
    sauce = _recipe("Tomato sauce", None, [
        "1 can crushed tomatoes", "2 cloves garlic, minced", "1 tbsp olive oil", "1/2 tsp salt", "1 tsp dried oregano",
    ], "Sauté garlic in oil, add tomatoes and simmer 20 minutes.")
    pizza = _recipe("Pizza night", 4, [
        (1, dough), (1, sauce), "8 oz mozzarella, shredded", "1 bunch basil (optional)", "4 oz pepperoni (optional)",
    ], "Stretch dough, spread sauce, top, bake at 475°F for 12-15 minutes.")
    tacos = _recipe("Tacos", 4, [
        "1 lb ground beef", "8 tortillas", "1 head lettuce", "2 tomatoes, diced", "1 cup cheddar, shredded",
        "1 onion, diced", "2 tsp cumin", "1 tsp chili powder", "1 tsp salt",
    ])
    _recipe("Pancakes", 4, [
        "1 1/2 cups flour", "3 1/2 tsp baking powder", "1 tbsp sugar", "1/4 tsp salt", "1 1/4 cups milk",
        "1 egg", "3 tbsp butter, melted", "maple syrup (optional)",
    ])

    groceries = List(name="Groceries", kind="shopping")
    hardware = List(name="Hardware store", kind="general")
    db.session.add_all([groceries, hardware])
    for text in ("1 gallon milk", "12 eggs", "bananas", "coffee", "paper towels"):
        p = parse_line(text)
        add_to_list(groceries, Ingredient.get_or_create(p.name), p.name, p.quantity, p.unit, user_id=users["mom"].id)
    add_recipe_to_list(groceries, pizza, user_id=users["dad"].id)
    add_recipe_to_list(groceries, tacos, user_id=users["mom"].id)
    for text in ("Furnace filter 16x25", "Light bulbs (A19, warm)", "Wood glue"):
        db.session.add(ListItem(list=hardware, text=text, manual=True))

    today = local_today()
    db.session.add_all([
        Todo(title="Take out recycling", assigned_to=users["sam"], due_date=today, created_by=users["mom"]),
        Todo(title="Sign field trip form", assigned_to=users["dad"], due_date=today + timedelta(days=1), created_by=users["mom"]),
        Todo(title="Practice piano 20 min", assigned_to=users["alex"], created_by=users["mom"]),
        Todo(title="Schedule dentist appointments", assigned_to=users["mom"], due_date=today + timedelta(days=5), created_by=users["dad"]),
        Todo(title="Water the plants", created_by=users["dad"]),
    ])
    db.session.add_all([
        Message(body="Welcome to the family dashboard! 🎉 Post notes for everyone here.", author=users["mom"], pinned=True),
        Message(body="Soccer moved to 5:30 on Thursday.", author=users["dad"]),
        Message(body="Can we have pizza this weekend??", author=users["sam"]),
    ])

    def at(day_offset, hh, mm, hours=1.0):
        start = to_utc_naive(datetime.combine(today + timedelta(days=day_offset), time(hh, mm)))
        return start, start + timedelta(hours=hours)

    for title, (start, end), who, where in [
        ("Soccer practice", at(0, 17, 30, 1.5), "dad", "Field 3"),
        ("Piano lesson", at(1, 16, 0), "mom", ""),
        ("Parent-teacher conference", at(3, 18, 0, 0.5), "mom", "Room 12"),
        ("Pizza night", at(4, 18, 0, 2), "sam", "Home"),
    ]:
        db.session.add(Event(title=title, start=start, end=end, location=where, created_by=users[who]))
    trip = datetime.combine(today + timedelta(days=9), time())
    db.session.add(Event(title="Camping trip", start=trip, end=trip + timedelta(days=3), all_day=True, created_by=users["dad"]))

    db.session.commit()
    return {"users": [u for u, *_ in people], "password": DEMO_PASSWORD}
