"""Recipe dependency chains and adding recipes to shopping lists.

A recipe's components are either ingredients or other recipes (sub-recipes).
``expand`` walks that tree, multiplying quantities through each level, and
``add_recipe_to_list`` merges the result into a shopping list, tagging every
item with the recipe it is for.
"""

from dataclasses import dataclass, field

from ..extensions import db
from ..models import Ingredient, List, ListItem, ListItemRecipe, Recipe, RecipeComponent
from .quantities import display_unit

EPSILON = 1e-9


class RecipeCycleError(ValueError):
    pass


@dataclass
class ExpandedLine:
    ingredient: Ingredient
    quantity: float | None
    unit: str
    path: tuple[str, ...]  # recipe names from the top recipe down to the one using this line
    optional: bool = False
    note: str = ""


@dataclass
class TreeNode:
    """One component in a scaled, fully expanded recipe tree (used for previews)."""

    component: RecipeComponent
    quantity: float | None
    children: list["TreeNode"] = field(default_factory=list)

    @property
    def is_subrecipe(self) -> bool:
        return self.component.subrecipe is not None


@dataclass
class MergedLine:
    ingredient: Ingredient
    quantity: float | None
    unit: str
    paths: list[tuple[str, ...]] = field(default_factory=list)
    optional: bool = True
    notes: list[str] = field(default_factory=list)

    @property
    def unit_label(self) -> str:
        return display_unit(self.unit, self.quantity)


def _mul(quantity: float | None, factor: float) -> float | None:
    return None if quantity is None else quantity * factor


def _add(a: float | None, b: float | None) -> float | None:
    """Sum quantities where None means "some, amount unspecified"."""
    if a is None and b is None:
        return None
    return (a or 0) + (b or 0)


def would_create_cycle(recipe: Recipe, subrecipe: Recipe) -> bool:
    """True if using ``subrecipe`` inside ``recipe`` would make recipe depend on itself."""
    if recipe.id == subrecipe.id:
        return True
    seen: set[int] = set()
    stack = [subrecipe]
    while stack:
        current = stack.pop()
        if current.id in seen:
            continue
        seen.add(current.id)
        for comp in current.components:
            if comp.subrecipe is None:
                continue
            if comp.subrecipe is recipe:
                return True
            stack.append(comp.subrecipe)
    return False


def build_tree(recipe: Recipe, scale: float = 1.0, _stack: tuple[int, ...] = ()) -> list[TreeNode]:
    if recipe.id in _stack:
        raise RecipeCycleError(f"Recipe {recipe.name!r} includes itself.")
    stack = _stack + (recipe.id,)
    nodes = []
    for comp in recipe.components:
        if comp.subrecipe is not None:
            batches = (comp.quantity if comp.quantity is not None else 1.0) * scale
            nodes.append(TreeNode(comp, batches, build_tree(comp.subrecipe, batches, stack)))
        else:
            nodes.append(TreeNode(comp, _mul(comp.quantity, scale)))
    return nodes


def expand(recipe: Recipe, scale: float = 1.0) -> list[ExpandedLine]:
    """Flatten a recipe (and all its sub-recipes) into scaled ingredient lines.

    For a sub-recipe component the quantity is a number of batches (blank = 1).
    """
    lines: list[ExpandedLine] = []

    def walk(nodes: list[TreeNode], path: tuple[str, ...], optional: bool) -> None:
        for node in nodes:
            comp = node.component
            if node.is_subrecipe:
                walk(node.children, path + (comp.subrecipe.name,), optional or comp.optional)
            else:
                lines.append(ExpandedLine(comp.ingredient, node.quantity, comp.unit, path, optional or comp.optional, comp.note))

    walk(build_tree(recipe, scale), (recipe.name,), False)
    return lines


def merge_lines(lines: list[ExpandedLine]) -> list[MergedLine]:
    """Combine lines for the same ingredient and unit. Different units stay separate."""
    merged: dict[tuple[int, str], MergedLine] = {}
    for line in lines:
        key = (line.ingredient.id, line.unit)
        m = merged.get(key)
        if m is None:
            m = merged[key] = MergedLine(line.ingredient, line.quantity, line.unit)
        else:
            m.quantity = _add(m.quantity, line.quantity)
        m.paths.append(line.path)
        m.optional = m.optional and line.optional
        if line.note and line.note not in m.notes:
            m.notes.append(line.note)
    return sorted(merged.values(), key=lambda m: (Ingredient.CATEGORIES.index(m.ingredient.category)
                                                   if m.ingredient.category in Ingredient.CATEGORIES else 99,
                                                   m.ingredient.name))


def add_to_list(
    lst: List,
    ingredient: Ingredient | None,
    text: str,
    quantity: float | None,
    unit: str,
    recipe: Recipe | None = None,
    user_id: int | None = None,
) -> ListItem:
    """Add one item to a list, merging into an unchecked item with the same ingredient and unit."""
    item = None
    if ingredient is not None:
        item = next(
            (i for i in lst.items if not i.checked and i.ingredient is ingredient and i.unit == unit),
            None,
        )
    if item is None:
        item = ListItem(list=lst, text=text, ingredient=ingredient, quantity=quantity, unit=unit, added_by_id=user_id)
        db.session.add(item)
    else:
        item.quantity = _add(item.quantity, quantity)

    if recipe is None:
        item.manual = True
    else:
        link = next((link for link in item.recipe_links if link.recipe is recipe), None)
        if link is None:
            item.recipe_links.append(ListItemRecipe(recipe=recipe, quantity=quantity))
        else:
            link.quantity = _add(link.quantity, quantity)
    return item


def add_recipe_to_list(
    lst: List,
    recipe: Recipe,
    scale: float = 1.0,
    excluded_keys: set[tuple[int, str]] | None = None,
    include_optional: bool = False,
    user_id: int | None = None,
) -> list[ListItem]:
    """Add every ingredient a recipe needs (through all sub-recipes) to ``lst``.

    ``excluded_keys`` holds (ingredient_id, unit) pairs to skip, e.g. things
    already in the pantry. Optional ingredients are skipped unless asked for.
    """
    excluded_keys = excluded_keys or set()
    items = []
    for line in merge_lines(expand(recipe, scale)):
        if (line.ingredient.id, line.unit) in excluded_keys:
            continue
        if line.optional and not include_optional:
            continue
        items.append(add_to_list(lst, line.ingredient, line.ingredient.name, line.quantity, line.unit, recipe, user_id))
    return items


def remove_recipe_from_list(lst: List, recipe: Recipe) -> int:
    """Take a recipe's contribution back off a list. Returns how many items were deleted.

    Items that are left with nothing (no other recipe, not typed in by hand)
    are deleted; others just lose the recipe's quantity and tag.
    """
    deleted = 0
    for item in list(lst.items):
        link = next((link for link in item.recipe_links if link.recipe is recipe), None)
        if link is None:
            continue
        if item.quantity is not None and link.quantity is not None:
            item.quantity = item.quantity - link.quantity
            if item.quantity < EPSILON:
                item.quantity = None
        item.recipe_links.remove(link)
        if not item.checked and not item.manual and not item.recipe_links:
            db.session.delete(item)
            deleted += 1
    return deleted


def recipes_on_list(lst: List) -> list[Recipe]:
    seen = {}
    for item in lst.items:
        for link in item.recipe_links:
            seen[id(link.recipe)] = link.recipe
    return sorted(seen.values(), key=lambda r: r.name)
