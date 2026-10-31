from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache

from .brand_colors import title_for_material_key
from .material_flow import ELASTIC, FABRIC, TAILOR, WAREHOUSE, q
from .models import RawMaterialStock


def round_money(value):
    return int(Decimal(value or 0).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def weighted_unit_price(rows):
    rows = list(rows)
    total_qty = Decimal("0")
    total_value = Decimal("0")
    for row in rows:
        qty = max(q(row.quantity), Decimal("0"))
        if qty <= 0:
            continue
        total_qty += qty
        total_value += qty * Decimal(int(row.unit_price or 0))
    if total_qty > 0:
        return round_money(total_value / total_qty)

    # Live costing should keep the latest known active unit price even if that stock
    # row has just reached zero, instead of collapsing the finished-goods cost to 0.
    for row in reversed(rows):
        price = int(row.unit_price or 0)
        if price > 0:
            return price
    return 0


def _material_rows(*, kind, location, material_key, variant=None):
    filters = {
        "active": True,
        "kind": kind,
        "location": location,
        "material_key": material_key,
    }
    if variant is not None:
        filters["variant"] = str(variant)
    return list(RawMaterialStock.objects.filter(**filters).order_by("id"))


@lru_cache(maxsize=512)
def fabric_price(material_key, fabric_code=""):
    """Return the live weighted price per kg for this fabric color/model.

    The material-report code is descriptive only. Costing is intentionally based on
    the current finished unit price of the color/model itself: first the stock at the
    tailor, and if that color has no usable tailor price, the warehouse stock.
    """
    tailor_price = weighted_unit_price(
        _material_rows(kind=FABRIC, location=TAILOR, material_key=material_key)
    )
    if tailor_price > 0:
        return tailor_price

    return weighted_unit_price(
        _material_rows(kind=FABRIC, location=WAREHOUSE, material_key=material_key)
    )


@lru_cache(maxsize=512)
def elastic_price(material_key, variant):
    # Elastic costing must come from the current stock held by the tailor.
    return weighted_unit_price(
        _material_rows(
            kind=ELASTIC,
            location=TAILOR,
            material_key=material_key,
            variant=str(variant),
        )
    )


def used_elastic(values, field, remain_field):
    delivered = max(q((values or {}).get(field)), Decimal("0"))
    remain_raw = (values or {}).get(remain_field)
    if remain_raw in (None, ""):
        return delivered
    return max(delivered - max(q(remain_raw), Decimal("0")), Decimal("0"))


def calculate_model_cost(material_key, values, wage):
    """Live finished unit cost for one material/color.

    Formula, without hidden multipliers:
      fabric per piece = (fabric kg * live fabric price/kg) / cut
      labor per piece  = total tailor wage / cut
      elastic per piece = ((used 16 kg * price16/kg) + (used 25 kg * price25/kg)) / cut
      unit cost = fabric per piece + labor per piece + elastic per piece

    `used` elastic remains delivery minus returned/remain quantity, preserving the
    existing material-consumption semantics.
    """
    values = values or {}
    cut_qty = max(q(values.get("cut")), Decimal("0"))
    fabric_qty = max(q(values.get("weight")), Decimal("0"))
    elastic16_qty = used_elastic(values, "elastic16", "remain16")
    elastic25_qty = used_elastic(values, "elastic25", "remain25")

    elastic16_key = (values.get("elastic16_key") or material_key or "").strip()
    elastic25_key = (values.get("elastic25_key") or material_key or "").strip()

    f_price = fabric_price(material_key, values.get("fabric_code"))
    e16_price = elastic_price(elastic16_key, "16") if elastic16_key else 0
    e25_price = elastic_price(elastic25_key, "25") if elastic25_key else 0

    fabric_cost_exact = fabric_qty * Decimal(f_price)
    elastic16_cost_exact = elastic16_qty * Decimal(e16_price)
    elastic25_cost_exact = elastic25_qty * Decimal(e25_price)
    labor_cost_exact = Decimal(int(wage or 0))
    elastic_cost_exact = elastic16_cost_exact + elastic25_cost_exact
    total_cost_exact = fabric_cost_exact + labor_cost_exact + elastic_cost_exact

    if cut_qty > 0:
        fabric_unit_cost = fabric_cost_exact / cut_qty
        labor_unit_cost = labor_cost_exact / cut_qty
        elastic_unit_cost = elastic_cost_exact / cut_qty
        unit_cost = round_money(fabric_unit_cost + labor_unit_cost + elastic_unit_cost)
    else:
        fabric_unit_cost = Decimal("0")
        labor_unit_cost = Decimal("0")
        elastic_unit_cost = Decimal("0")
        unit_cost = 0

    fabric_cost = round_money(fabric_cost_exact)
    elastic16_cost = round_money(elastic16_cost_exact)
    elastic25_cost = round_money(elastic25_cost_exact)
    labor_cost = round_money(labor_cost_exact)
    total_cost = round_money(total_cost_exact)

    return {
        "unit_cost": unit_cost,
        "fabric_price": f_price,
        "elastic16_price": e16_price,
        "elastic25_price": e25_price,
        "fabric_cost": fabric_cost,
        "elastic16_cost": elastic16_cost,
        "elastic25_cost": elastic25_cost,
        "elastic_cost": elastic16_cost + elastic25_cost,
        "labor_cost": labor_cost,
        "total_cost": total_cost,
        "cut_qty": cut_qty,
        "fabric_unit_cost": round_money(fabric_unit_cost),
        "labor_unit_cost": round_money(labor_unit_cost),
        "elastic_unit_cost": round_money(elastic_unit_cost),
        "fabric_key": material_key,
        "fabric_label": title_for_material_key(material_key),
        "elastic16_key": elastic16_key,
        "elastic25_key": elastic25_key,
    }


def reset_price_cache():
    fabric_price.cache_clear()
    elastic_price.cache_clear()


def live_cost_catalog(material_keys, elastic_keys):
    material_keys = list(dict.fromkeys(k for k in material_keys if k))
    elastic_keys = list(dict.fromkeys(k for k in elastic_keys if k))
    return {
        "fabric": {key: fabric_price(key) for key in material_keys},
        "elastic16": {key: elastic_price(key, "16") for key in elastic_keys},
        "elastic25": {key: elastic_price(key, "25") for key in elastic_keys},
    }
