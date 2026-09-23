from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from loguru import logger
from sqlalchemy import func

from ..extensions import db
from ..models import Ingredient, List, ListItem, Recipe, set_completed
from ..services.quantities import parse_line
from ..services.recipes import (
    RecipeCycleError,
    add_recipe_to_list,
    add_to_list,
    build_tree,
    expand,
    merge_lines,
    recipes_on_list,
    remove_recipe_from_list,
)
from ..template_helpers import is_htmx

bp = Blueprint("lists", __name__, url_prefix="/lists")

SCALES = [("0.5", "½×"), ("1", "1×"), ("1.5", "1½×"), ("2", "2×"), ("3", "3×"), ("4", "4×")]


def _get_list(list_id: int) -> List:
    return db.get_or_404(List, list_id)


def _parse_scale(value: str | None) -> float:
    try:
        scale = float(value or 1)
    except ValueError:
        return 1.0
    return scale if 0 < scale <= 20 else 1.0


def item_groups(lst: List) -> tuple[list[tuple[str, list[ListItem]]], list[ListItem]]:
    """Unchecked items grouped (by store category on shopping lists), plus checked items."""
    open_items = [i for i in lst.items if not i.checked]
    checked = sorted((i for i in lst.items if i.checked), key=lambda i: i.checked_at or i.created_at, reverse=True)
    if not lst.is_shopping:
        return [("", open_items)], checked
    order = {c: n for n, c in enumerate(Ingredient.CATEGORIES)}
    groups: dict[str, list[ListItem]] = {}
    for item in sorted(open_items, key=lambda i: (order.get(i.category, 99), i.text)):
        groups.setdefault(item.category, []).append(item)
    return list(groups.items()), checked


def render_items(lst: List):
    groups, checked = item_groups(lst)
    return render_template("lists/_items.html", lst=lst, groups=groups, checked=checked, list_recipes=recipes_on_list(lst))


def _items_response(lst: List):
    if is_htmx():
        return render_items(lst)
    return redirect(url_for("lists.show", list_id=lst.id))


@bp.route("/")
def index():
    lists = List.query.order_by(List.archived, List.kind.desc(), List.name).all()
    return render_template("lists/index.html", lists=lists)


@bp.route("/", methods=["POST"])
def create():
    name = request.form.get("name", "").strip()
    kind = request.form.get("kind", "general")
    if not name:
        flash("Give the list a name.", "error")
        return redirect(url_for("lists.index"))
    lst = List(name=name[:100], kind=kind if kind in List.KINDS else "general")
    db.session.add(lst)
    db.session.commit()
    return redirect(url_for("lists.show", list_id=lst.id))


@bp.route("/<int:list_id>")
def show(list_id):
    lst = _get_list(list_id)
    groups, checked = item_groups(lst)
    ctx = {}
    if lst.is_shopping:
        ctx["ingredient_names"] = [n for (n,) in db.session.query(Ingredient.name).order_by(Ingredient.name)]
        ctx["recipes"] = Recipe.query.order_by(Recipe.name).all()
    return render_template(
        "lists/show.html", lst=lst, groups=groups, checked=checked,
        list_recipes=recipes_on_list(lst), scales=SCALES, **ctx,
    )


@bp.route("/<int:list_id>/items", methods=["POST"])
def add_item(list_id):
    lst = _get_list(list_id)
    text = request.form.get("text", "").strip()[:200]
    if text:
        if lst.is_shopping:
            parsed = parse_line(text)
            name = parsed.name or text
            ingredient = Ingredient.get_or_create(name)
            recipe = None
            if request.form.get("recipe_id", "").isdigit():
                recipe = db.session.get(Recipe, int(request.form["recipe_id"]))
            add_to_list(lst, ingredient, ingredient.name, parsed.quantity, parsed.unit, recipe, current_user.id)
        else:
            db.session.add(ListItem(list=lst, text=text, manual=True, added_by_id=current_user.id))
        db.session.commit()
    return _items_response(lst)


@bp.route("/<int:list_id>/items/<int:item_id>/toggle", methods=["POST"])
def toggle_item(list_id, item_id):
    lst = _get_list(list_id)
    item = db.get_or_404(ListItem, item_id)
    if item.list_id != lst.id:
        abort(404)
    set_completed(item, not item.checked, "checked", "checked_at")
    db.session.commit()
    return _items_response(lst)


@bp.route("/<int:list_id>/items/<int:item_id>/delete", methods=["POST"])
def delete_item(list_id, item_id):
    lst = _get_list(list_id)
    item = db.get_or_404(ListItem, item_id)
    if item.list_id != lst.id:
        abort(404)
    db.session.delete(item)
    db.session.commit()
    db.session.refresh(lst)
    return _items_response(lst)


@bp.route("/<int:list_id>/clear-checked", methods=["POST"])
def clear_checked(list_id):
    lst = _get_list(list_id)
    for item in [i for i in lst.items if i.checked]:
        db.session.delete(item)
    db.session.commit()
    db.session.refresh(lst)
    return _items_response(lst)


@bp.route("/<int:list_id>/settings", methods=["POST"])
def update(list_id):
    lst = _get_list(list_id)
    action = request.form.get("action")
    if action == "rename" and request.form.get("name", "").strip():
        lst.name = request.form["name"].strip()[:100]
    elif action == "archive":
        lst.archived = not lst.archived
    elif action == "delete":
        db.session.delete(lst)
        db.session.commit()
        logger.info("{} deleted list {!r}", current_user.username, lst.name)
        flash(f"Deleted {lst.name}.", "ok")
        return redirect(url_for("lists.index"))
    db.session.commit()
    return redirect(url_for("lists.show", list_id=lst.id))


def _find_recipe(value: str | None) -> Recipe | None:
    if not value:
        return None
    if value.isdigit():
        return db.session.get(Recipe, int(value))
    return Recipe.query.filter(func.lower(Recipe.name) == value.strip().lower()).first()


@bp.route("/<int:list_id>/add-recipe", methods=["GET", "POST"])
def add_recipe(list_id):
    """Preview a recipe's full ingredient list, then add the ticked lines."""
    lst = _get_list(list_id)
    recipe = _find_recipe(request.values.get("recipe"))
    if recipe is None:
        flash("Couldn't find that recipe.", "error")
        return redirect(url_for("lists.show", list_id=lst.id))
    scale = _parse_scale(request.values.get("scale"))
    try:
        lines = merge_lines(expand(recipe, scale))
        tree = build_tree(recipe, scale)
    except RecipeCycleError as exc:
        flash(str(exc), "error")
        return redirect(url_for("lists.show", list_id=lst.id))

    if request.method == "POST":
        included = set(request.form.getlist("include"))
        excluded = {(line.ingredient.id, line.unit) for line in lines if f"{line.ingredient.id}:{line.unit}" not in included}
        items = add_recipe_to_list(lst, recipe, scale, excluded, include_optional=True, user_id=current_user.id)
        db.session.commit()
        logger.info("{} added {} ({}x, {} items) to list {!r}", current_user.username, recipe.name, scale, len(items), lst.name)
        flash(f"Added {len(items)} items for {recipe.name}.", "ok")
        return redirect(url_for("lists.show", list_id=lst.id))

    on_list = {(i.ingredient_id, i.unit) for i in lst.items if not i.checked and i.ingredient_id}
    return render_template(
        "lists/add_recipe.html", lst=lst, recipe=recipe, scale=scale, scales=SCALES,
        lines=lines, tree=tree, on_list=on_list,
    )


@bp.route("/<int:list_id>/recipes/<int:recipe_id>/remove", methods=["POST"])
def remove_recipe(list_id, recipe_id):
    lst = _get_list(list_id)
    recipe = db.get_or_404(Recipe, recipe_id)
    deleted = remove_recipe_from_list(lst, recipe)
    db.session.commit()
    logger.info("{} took {} off list {!r} ({} items removed)", current_user.username, recipe.name, lst.name, deleted)
    flash(f"Took {recipe.name} off the list ({deleted} items removed).", "ok")
    return redirect(url_for("lists.show", list_id=lst.id))
