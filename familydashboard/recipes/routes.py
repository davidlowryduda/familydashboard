from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import Ingredient, List, ListItem, Recipe, RecipeComponent, normalize_name
from ..services.quantities import parse_line, parse_quantity
from ..services.recipes import RecipeCycleError, build_tree, would_create_cycle

bp = Blueprint("recipes", __name__, url_prefix="/recipes")

RECIPE_FIELDS = ("name", "servings", "source_url", "instructions", "notes")


def search_recipes(q: str):
    query = Recipe.query
    if q:
        like = f"%{q.strip().lower()}%"
        uses_ingredient = Recipe.components.any(
            RecipeComponent.ingredient.has(Ingredient.name.like(like))
        )
        query = query.filter(or_(func.lower(Recipe.name).like(like), uses_ingredient))
    return query.order_by(Recipe.name).all()


def _apply_form(recipe: Recipe) -> str | None:
    """Copy form fields onto a recipe. Returns an error message, if any."""
    name = request.form.get("name", "").strip()
    if not name:
        return "A recipe needs a name."
    clash = Recipe.query.filter(func.lower(Recipe.name) == name.lower(), Recipe.id != recipe.id).first()
    if clash:
        return f"There's already a recipe called {clash.name}."
    recipe.name = name[:200]
    servings = request.form.get("servings", "").strip()
    recipe.servings = int(servings) if servings.isdigit() else None
    recipe.source_url = request.form.get("source_url", "").strip()[:1000]
    recipe.instructions = request.form.get("instructions", "").strip()
    recipe.notes = request.form.get("notes", "").strip()
    return None


@bp.route("/")
def index():
    q = request.args.get("q", "")
    return render_template("recipes/index.html", recipes=search_recipes(q), q=q)


@bp.route("/new", methods=["GET", "POST"])
def new():
    recipe = Recipe()
    if request.method == "POST":
        error = _apply_form(recipe)
        if error:
            flash(error, "error")
        else:
            db.session.add(recipe)
            db.session.commit()
            flash("Recipe created. Now add its ingredients.", "ok")
            return redirect(url_for("recipes.show", recipe_id=recipe.id))
    return render_template("recipes/form.html", recipe=recipe)


@bp.route("/<int:recipe_id>")
def show(recipe_id):
    recipe = db.get_or_404(Recipe, recipe_id)
    try:
        tree = build_tree(recipe)
    except RecipeCycleError:
        tree = []
    other_recipes = Recipe.query.filter(Recipe.id != recipe.id).order_by(Recipe.name).all()
    return render_template(
        "recipes/show.html",
        recipe=recipe,
        tree=tree,
        subrecipe_choices=[r for r in other_recipes if not would_create_cycle(recipe, r)],
        ingredient_names=[n for (n,) in db.session.query(Ingredient.name).order_by(Ingredient.name)],
        shopping_lists=List.query.filter_by(kind="shopping", archived=False).order_by(List.name).all(),
        used_in=sorted({c.recipe for c in recipe.used_in}, key=lambda r: r.name),
    )


@bp.route("/<int:recipe_id>/edit", methods=["GET", "POST"])
def edit(recipe_id):
    recipe = db.get_or_404(Recipe, recipe_id)
    if request.method == "POST":
        error = _apply_form(recipe)
        if error:
            flash(error, "error")
        else:
            db.session.commit()
            return redirect(url_for("recipes.show", recipe_id=recipe.id))
    return render_template("recipes/form.html", recipe=recipe)


@bp.route("/<int:recipe_id>/delete", methods=["POST"])
def delete(recipe_id):
    recipe = db.get_or_404(Recipe, recipe_id)
    if recipe.used_in:
        names = ", ".join(sorted({c.recipe.name for c in recipe.used_in}))
        flash(f"{recipe.name} is used in {names}. Remove it there first.", "error")
        return redirect(url_for("recipes.show", recipe_id=recipe.id))
    db.session.delete(recipe)
    db.session.commit()
    flash(f"Deleted {recipe.name}.", "ok")
    return redirect(url_for("recipes.index"))


def _next_position(recipe: Recipe) -> int:
    return max((c.position for c in recipe.components), default=-1) + 1


@bp.route("/<int:recipe_id>/components", methods=["POST"])
def add_component(recipe_id):
    recipe = db.get_or_404(Recipe, recipe_id)
    optional = bool(request.form.get("optional"))
    if request.form.get("kind") == "recipe":
        sub = db.session.get(Recipe, int(request.form.get("subrecipe_id") or 0))
        if sub is None:
            flash("Pick a recipe to include.", "error")
        elif would_create_cycle(recipe, sub):
            flash(f"{sub.name} already uses {recipe.name}, so it can't go inside it.", "error")
        else:
            try:
                batches = parse_quantity(request.form.get("quantity"))
            except (ValueError, ZeroDivisionError):
                batches = None
            recipe.components.append(RecipeComponent(
                subrecipe=sub, quantity=batches, optional=optional,
                note=request.form.get("note", "").strip()[:200], position=_next_position(recipe),
            ))
            db.session.commit()
    else:
        text = request.form.get("text", "").strip()
        if text:
            parsed = parse_line(text)
            if not parsed.name:
                flash("Couldn't find an ingredient name in that line.", "error")
            else:
                recipe.components.append(RecipeComponent(
                    ingredient=Ingredient.get_or_create(parsed.name), quantity=parsed.quantity,
                    unit=parsed.unit, note=parsed.note[:200], optional=optional,
                    position=_next_position(recipe),
                ))
                db.session.commit()
    return redirect(url_for("recipes.show", recipe_id=recipe.id) + "#components")


@bp.route("/<int:recipe_id>/components/<int:component_id>/delete", methods=["POST"])
def delete_component(recipe_id, component_id):
    comp = db.get_or_404(RecipeComponent, component_id)
    if comp.recipe_id != recipe_id:
        abort(404)
    db.session.delete(comp)
    db.session.commit()
    return redirect(url_for("recipes.show", recipe_id=recipe_id) + "#components")


@bp.route("/<int:recipe_id>/components/<int:component_id>/move", methods=["POST"])
def move_component(recipe_id, component_id):
    recipe = db.get_or_404(Recipe, recipe_id)
    comps = list(recipe.components)
    idx = next((n for n, c in enumerate(comps) if c.id == component_id), None)
    if idx is None:
        abort(404)
    swap = idx - 1 if request.form.get("direction") == "up" else idx + 1
    if 0 <= swap < len(comps):
        comps[idx], comps[swap] = comps[swap], comps[idx]
        for n, c in enumerate(comps):
            c.position = n
        db.session.commit()
    return redirect(url_for("recipes.show", recipe_id=recipe.id) + "#components")


@bp.route("/ingredients", methods=["GET", "POST"])
def ingredients():
    if request.method == "POST":
        ing = db.get_or_404(Ingredient, int(request.form.get("id", 0)))
        if request.form.get("action") == "delete":
            in_recipes = RecipeComponent.query.filter_by(ingredient_id=ing.id).count()
            if in_recipes:
                flash(f"{ing.name} is used in {in_recipes} recipe line(s).", "error")
            else:
                ListItem.query.filter_by(ingredient_id=ing.id).update({"ingredient_id": None})
                db.session.delete(ing)
                db.session.commit()
            return redirect(url_for("recipes.ingredients"))
        name = normalize_name(request.form.get("name", ing.name))
        category = request.form.get("category", ing.category)
        if name:
            ing.name = name
        if category in Ingredient.CATEGORIES:
            ing.category = category
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash(f"An ingredient called {name} already exists.", "error")
        return redirect(url_for("recipes.ingredients") + f"#ing-{ing.id}")
    items = Ingredient.query.order_by(Ingredient.category, Ingredient.name).all()
    return render_template("recipes/ingredients.html", ingredients=items, categories=Ingredient.CATEGORIES)
