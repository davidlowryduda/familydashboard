from flask_login import UserMixin
from sqlalchemy import CheckConstraint
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db
from .timeutil import utcnow

USER_COLORS = ["#e76f51", "#2a9d8f", "#e9c46a", "#8e7dbe", "#f4a261", "#457b9d", "#d62828", "#6a994e"]


def normalize_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def name_variants(name: str) -> list[str]:
    """The name itself first, then likely singular/plural spellings."""
    variants = [name]
    if name.endswith("ies"):
        variants.append(name[:-3] + "y")
    if name.endswith("oes") or name.endswith("ches") or name.endswith("shes"):
        variants.append(name[:-2])
    if name.endswith("s") and not name.endswith("ss"):
        variants.append(name[:-1])
    if name.endswith("y"):
        variants.append(name[:-1] + "ies")
    if not name.endswith("s"):
        variants += [name + "s", name + "es"]
    return list(dict.fromkeys(variants))


CATEGORY_KEYWORDS = {
    "produce": "apple banana lemon lime orange berry berries grape onion garlic potato tomato lettuce spinach carrot "
               "celery pepper cucumber zucchini broccoli cauliflower mushroom avocado cilantro parsley basil ginger "
               "kale cabbage scallion shallot squash corn pear peach herbs mint",
    "meat & fish": "chicken beef pork turkey bacon sausage ham steak salmon tuna shrimp fish lamb ground",
    "dairy & eggs": "milk butter cheese cheddar mozzarella parmesan yogurt cream egg eggs sour",
    "bakery": "bread bun buns bagel tortilla tortillas pita roll rolls",
    "spices": "salt peppercorn cumin paprika oregano cinnamon nutmeg chili thyme rosemary spice seasoning vanilla",
    "pantry": "flour sugar rice pasta oil vinegar yeast beans lentils oats sauce broth stock honey syrup "
              "baking soda powder noodles cereal peanut nuts chocolate ketchup mustard mayo",
    "frozen": "frozen ice",
    "drinks": "juice coffee tea soda water wine beer",
    "household": "paper towels soap detergent foil wrap trash bags toothpaste shampoo",
}


def guess_category(name: str) -> str:
    """Rough first guess for a new ingredient; people can fix it on the Ingredients page."""
    if "black pepper" in name or "white pepper" in name:
        return "spices"
    words = set(name.split())
    words |= {w[:-1] for w in words if w.endswith("s")} | {w[:-2] for w in words if w.endswith("es")}
    # Check in an order where more specific groups win ("frozen peas", "chili powder").
    for category in ("frozen", "household", "spices", "dairy & eggs", "meat & fish", "bakery", "drinks", "produce", "pantry"):
        if words & set(CATEGORY_KEYWORDS[category].split()):
            return category
    return "other"


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    display_name = db.Column(db.String(64), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    color = db.Column(db.String(16), nullable=False, default=USER_COLORS[0])
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def initial(self) -> str:
        return (self.display_name or self.username)[:1].upper()

    def __repr__(self) -> str:
        return f"<User {self.username}>"


class Todo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    notes = db.Column(db.Text, nullable=False, default="")
    due_date = db.Column(db.Date)
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))
    done = db.Column(db.Boolean, nullable=False, default=False)
    done_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    assigned_to = db.relationship("User", foreign_keys=[assigned_to_id])
    created_by = db.relationship("User", foreign_keys=[created_by_id])


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))
    pinned = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    author = db.relationship("User")

    def can_modify(self, user) -> bool:
        return user.is_admin or user.id == self.author_id


class CalendarFeed(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    ics_url = db.Column(db.String(1000), nullable=False)
    color = db.Column(db.String(16), nullable=False, default="#457b9d")
    last_synced_at = db.Column(db.DateTime)
    last_error = db.Column(db.Text)

    owner = db.relationship("User")
    events = db.relationship("Event", back_populates="feed", cascade="all, delete-orphan", passive_deletes=True)


class Event(db.Model):
    """A calendar event.

    Timed events store ``start``/``end`` as naive UTC. All-day events store the
    local calendar date at midnight (no timezone meaning) and ``end`` is
    exclusive, matching iCalendar semantics.
    """

    id = db.Column(db.Integer, primary_key=True)
    feed_id = db.Column(db.Integer, db.ForeignKey("calendar_feed.id", ondelete="CASCADE"))
    uid = db.Column(db.String(500))
    title = db.Column(db.String(300), nullable=False)
    start = db.Column(db.DateTime, nullable=False, index=True)
    end = db.Column(db.DateTime, nullable=False)
    all_day = db.Column(db.Boolean, nullable=False, default=False)
    location = db.Column(db.String(300), nullable=False, default="")
    description = db.Column(db.Text, nullable=False, default="")
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))

    feed = db.relationship("CalendarFeed", back_populates="events")
    created_by = db.relationship("User")

    @property
    def is_local(self) -> bool:
        return self.feed_id is None

    @property
    def color(self) -> str:
        if self.feed is not None:
            return self.feed.color
        if self.created_by is not None:
            return self.created_by.color
        return "#457b9d"


class Ingredient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    category = db.Column(db.String(40), nullable=False, default="other")
    default_unit = db.Column(db.String(20), nullable=False, default="")

    CATEGORIES = [
        "produce", "meat & fish", "dairy & eggs", "bakery", "pantry",
        "spices", "frozen", "drinks", "household", "other",
    ]

    @classmethod
    def find(cls, name: str) -> "Ingredient | None":
        """Look up by name, tolerating simple plurals ("onions" finds "onion")."""
        variants = name_variants(normalize_name(name))
        matches = cls.query.filter(cls.name.in_(variants)).all()
        if not matches:
            return None
        return min(matches, key=lambda i: variants.index(i.name))

    @classmethod
    def get_or_create(cls, name: str, category: str | None = None) -> "Ingredient":
        ing = cls.find(name)
        if ing is None:
            norm = normalize_name(name)
            ing = cls(name=norm, category=category or guess_category(norm))
            db.session.add(ing)
            db.session.flush()
        return ing


class Recipe(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)
    servings = db.Column(db.Integer)
    instructions = db.Column(db.Text, nullable=False, default="")
    source_url = db.Column(db.String(1000), nullable=False, default="")
    notes = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    components = db.relationship(
        "RecipeComponent",
        foreign_keys="RecipeComponent.recipe_id",
        back_populates="recipe",
        cascade="all, delete-orphan",
        order_by="RecipeComponent.position",
    )
    used_in = db.relationship(
        "RecipeComponent", foreign_keys="RecipeComponent.subrecipe_id", back_populates="subrecipe"
    )


class RecipeComponent(db.Model):
    """One line of a recipe: either an ingredient or another recipe (a sub-recipe).

    For a sub-recipe, ``quantity`` is the number of batches (blank means 1).
    """

    __table_args__ = (
        CheckConstraint(
            "(ingredient_id IS NULL) != (subrecipe_id IS NULL)", name="ingredient_xor_subrecipe"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey("recipe.id", ondelete="CASCADE"), nullable=False)
    ingredient_id = db.Column(db.Integer, db.ForeignKey("ingredient.id", ondelete="RESTRICT"))
    subrecipe_id = db.Column(db.Integer, db.ForeignKey("recipe.id", ondelete="RESTRICT"))
    quantity = db.Column(db.Float)
    unit = db.Column(db.String(20), nullable=False, default="")
    note = db.Column(db.String(200), nullable=False, default="")
    optional = db.Column(db.Boolean, nullable=False, default=False)
    position = db.Column(db.Integer, nullable=False, default=0)

    recipe = db.relationship("Recipe", foreign_keys=[recipe_id], back_populates="components")
    ingredient = db.relationship("Ingredient")
    subrecipe = db.relationship("Recipe", foreign_keys=[subrecipe_id], back_populates="used_in")


class ListItemRecipe(db.Model):
    """Links a list item to a recipe it is needed for (the "recipe indication").

    ``quantity`` is how much of the item that recipe contributed, so the recipe
    can later be taken off the list without disturbing other contributions.
    """

    __tablename__ = "list_item_recipe"

    item_id = db.Column(db.Integer, db.ForeignKey("list_item.id", ondelete="CASCADE"), primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey("recipe.id", ondelete="CASCADE"), primary_key=True)
    quantity = db.Column(db.Float)

    item = db.relationship("ListItem", back_populates="recipe_links")
    recipe = db.relationship("Recipe")


class List(db.Model):
    KINDS = ("shopping", "general")

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    kind = db.Column(db.String(20), nullable=False, default="general")
    archived = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    items = db.relationship(
        "ListItem", back_populates="list", cascade="all, delete-orphan", passive_deletes=True,
        order_by="ListItem.created_at",
    )

    @property
    def is_shopping(self) -> bool:
        return self.kind == "shopping"

    @property
    def open_count(self) -> int:
        return sum(1 for i in self.items if not i.checked)


class ListItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    list_id = db.Column(db.Integer, db.ForeignKey("list.id", ondelete="CASCADE"), nullable=False)
    text = db.Column(db.String(200), nullable=False)
    ingredient_id = db.Column(db.Integer, db.ForeignKey("ingredient.id", ondelete="SET NULL"))
    quantity = db.Column(db.Float)
    unit = db.Column(db.String(20), nullable=False, default="")
    checked = db.Column(db.Boolean, nullable=False, default=False)
    checked_at = db.Column(db.DateTime)
    added_by_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    list = db.relationship("List", back_populates="items")
    ingredient = db.relationship("Ingredient")
    # True when someone typed this item in without tagging a recipe.
    manual = db.Column(db.Boolean, nullable=False, default=False)

    added_by = db.relationship("User")
    recipe_links = db.relationship("ListItemRecipe", back_populates="item", cascade="all, delete-orphan")

    @property
    def recipes(self):
        return sorted((link.recipe for link in self.recipe_links), key=lambda r: r.name)

    @property
    def category(self) -> str:
        return self.ingredient.category if self.ingredient else "other"


def format_quantity(qty: float | None) -> str:
    if qty is None:
        return ""
    if abs(qty - round(qty)) < 1e-9:
        return str(int(round(qty)))
    fractions = {0.25: "¼", 0.5: "½", 0.75: "¾", 1 / 3: "⅓", 2 / 3: "⅔"}
    whole = int(qty)
    for value, glyph in fractions.items():
        if abs((qty - whole) - value) < 0.01:
            return f"{whole}{glyph}" if whole else glyph
    return f"{qty:.2f}".rstrip("0").rstrip(".")


def set_completed(obj, done: bool, flag: str = "done", at: str = "done_at") -> None:
    """Set a completion flag and its timestamp together."""
    setattr(obj, flag, done)
    setattr(obj, at, utcnow() if done else None)
