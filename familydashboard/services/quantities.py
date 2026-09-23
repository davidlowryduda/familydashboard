"""Parse free text like "1 1/2 cups flour, sifted" into quantity, unit, name and note."""

import re
from dataclasses import dataclass
from fractions import Fraction

UNICODE_FRACTIONS = {"¼": "1/4", "½": "1/2", "¾": "3/4", "⅓": "1/3", "⅔": "2/3", "⅛": "1/8"}

# Canonical unit -> spellings people type. Single letters are left out on
# purpose ("t" vs "T" is too easy to get wrong).
UNIT_ALIASES = {
    "cup": ["cup", "cups", "c."],
    "tbsp": ["tbsp", "tbsps", "tbs", "tablespoon", "tablespoons"],
    "tsp": ["tsp", "tsps", "teaspoon", "teaspoons"],
    "lb": ["lb", "lbs", "pound", "pounds"],
    "oz": ["oz", "ounce", "ounces"],
    "g": ["g", "gram", "grams"],
    "kg": ["kg", "kilo", "kilos", "kilogram", "kilograms"],
    "ml": ["ml", "milliliter", "milliliters"],
    "l": ["l", "liter", "liters", "litre", "litres"],
    "pint": ["pint", "pints", "pt"],
    "quart": ["quart", "quarts", "qt"],
    "gallon": ["gallon", "gallons", "gal"],
    "can": ["can", "cans"],
    "jar": ["jar", "jars"],
    "bottle": ["bottle", "bottles"],
    "box": ["box", "boxes"],
    "bag": ["bag", "bags"],
    "package": ["package", "packages", "pkg", "pkgs", "pack", "packs"],
    "clove": ["clove", "cloves"],
    "bunch": ["bunch", "bunches"],
    "head": ["head", "heads"],
    "slice": ["slice", "slices"],
    "stick": ["stick", "sticks"],
    "pinch": ["pinch", "pinches"],
    "dozen": ["dozen", "doz"],
    "loaf": ["loaf", "loaves"],
}
_ALIAS_TO_UNIT = {alias: unit for unit, aliases in UNIT_ALIASES.items() for alias in aliases}
_PLURALS = {"box": "boxes", "bunch": "bunches", "pinch": "pinches", "loaf": "loaves"}
_UNPLURAL = {"tbsp", "tsp", "lb", "oz", "g", "kg", "ml", "l", "dozen"}

_QTY_RE = re.compile(r"^\s*(\d+\s+\d+/\d+|\d+/\d+|\d*\.\d+|\d+)(?:\s*(?:-|to)\s*(?:\d+/\d+|\d*\.\d+|\d+))?\s*")


@dataclass
class Parsed:
    quantity: float | None
    unit: str
    name: str
    note: str = ""


def normalize_unit(unit: str) -> str:
    u = unit.strip().lower()
    return _ALIAS_TO_UNIT.get(u, _ALIAS_TO_UNIT.get(u.rstrip("."), u))


def parse_quantity(text: str | None) -> float | None:
    """'1 1/2' -> 1.5, '½' -> 0.5, '' -> None. Raises ValueError on garbage."""
    if text is None or not text.strip():
        return None
    t = text.strip()
    for glyph, frac in UNICODE_FRACTIONS.items():
        t = t.replace(glyph, f" {frac}")
    total = Fraction(0)
    for part in t.split():
        total += Fraction(part)
    if total < 0:
        raise ValueError("negative quantity")
    return float(total)


def parse_line(text: str) -> Parsed:
    """Split "2 cups flour, sifted" into (2.0, "cup", "flour", "sifted").

    A range like "2-3 onions" takes the upper bound so the shopping list has enough.
    """
    t = text.strip()
    for glyph, frac in UNICODE_FRACTIONS.items():
        t = re.sub(rf"(\d)\s*{glyph}", rf"\1 {frac}", t).replace(glyph, frac)

    quantity = None
    m = _QTY_RE.match(t)
    if m:
        range_upper = re.search(r"(?:-|to)\s*(\d+/\d+|\d*\.\d+|\d+)\s*$", m.group(0).strip())
        quantity = parse_quantity(range_upper.group(1) if range_upper else m.group(1))
        t = t[m.end():]
    elif re.match(r"^an?\s+", t, re.IGNORECASE):  # "a can of tomatoes"
        quantity = 1.0
        t = re.sub(r"^an?\s+", "", t, flags=re.IGNORECASE)

    unit = ""
    first, _, rest = t.partition(" ")
    if quantity is not None and rest.strip() and normalize_unit(first) in UNIT_ALIASES:
        unit = normalize_unit(first)
        t = re.sub(r"^of\s+", "", rest.strip())

    name, _, note = t.partition(",")
    return Parsed(quantity, unit, name.strip(), note.strip())


def display_unit(unit: str, quantity: float | None) -> str:
    if not unit or quantity is None or quantity <= 1 or unit in _UNPLURAL:
        return unit
    return _PLURALS.get(unit, unit + "s")
