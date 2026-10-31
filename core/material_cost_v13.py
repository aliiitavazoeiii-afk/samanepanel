from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Q

from .material_flow import COLOR_LABELS, ELASTIC, FABRIC, TAILOR, q
from .models import RawMaterialStock


def _round_money(value):
    return int(Decimal(value or 0).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _weighted_unit_price(rows):
    total_qty = Decimal("0")
    total_value = Decimal("0")
    for row in rows:
        qty = max(q(row.quantity), Decimal("0"))
        if qty <= 0:
            continue
        total_qty += qty
        total_value += qty * Decimal(int(row.unit_price or 0))
    if total_qty <= 0:
        return 0
    return _round_money(total_value / total_qty)


def _fabric_price(material_key, fabric_code=""):
    qs = RawMaterialStock.objects.filter(
        active=True,
        kind=FABRIC,
        location=TAILOR,
        material_key=material_key,
    ).order_by("id")
    code = (fabric_code or "").strip()
    if code:
        exact = list(qs.filter(Q(title__iexact=code) | Q(note__icontains=code)))
        if exact:
            return _weighted_unit_price(exact)
    return _weighted_unit_price(list(qs))


def _elastic_price(material_key, variant):
    rows = list(
        RawMaterialStock.objects.filter(
            active=True,
            kind=ELASTIC,
            location=TAILOR,
            material_key=material_key,
            variant=str(variant),
        ).order_by("id")
    )
    return _weighted_unit_price(rows)


def _used_elastic(values, field, remain_field):
    delivered = max(q(values.get(field)), Decimal("0"))
    remain_raw = values.get(remain_field)
    if remain_raw in (None, ""):
        return delivered
    return max(delivered - max(q(remain_raw), Decimal("0")), Decimal("0"))


def calculate_color_cost(material_key, values, wage):
    values = values or {}
    cut_qty = max(q(values.get("cut")), Decimal("0"))
    if cut_qty <= 0:
        return {
            "unit_cost": 0,
            "fabric_price": 0,
            "elastic16_price": 0,
            "elastic25_price": 0,
            "fabric_cost": 0,
            "elastic_cost": 0,
            "labor_cost": int(wage or 0),
            "total_cost": 0,
        }

    fabric_qty = max(q(values.get("weight")), Decimal("0"))
    elastic16_qty = _used_elastic(values, "elastic16", "remain16")
    elastic25_qty = _used_elastic(values, "elastic25", "remain25")

    fabric_price = _fabric_price(material_key, values.get("fabric_code"))
    elastic16_price = _elastic_price(material_key, "16")
    elastic25_price = _elastic_price(material_key, "25")

    fabric_cost = _round_money(fabric_qty * Decimal(fabric_price))
    elastic_cost = _round_money(
        elastic16_qty * Decimal(elastic16_price)
        + elastic25_qty * Decimal(elastic25_price)
    )
    labor_cost = int(wage or 0)
    total_cost = fabric_cost + elastic_cost + labor_cost
    unit_cost = _round_money(Decimal(total_cost) / cut_qty) if cut_qty else 0

    return {
        "unit_cost": unit_cost,
        "fabric_price": fabric_price,
        "elastic16_price": elastic16_price,
        "elastic25_price": elastic25_price,
        "fabric_cost": fabric_cost,
        "elastic_cost": elastic_cost,
        "labor_cost": labor_cost,
        "total_cost": total_cost,
    }


def apply_costs_to_input_data(input_data):
    input_data = input_data or {}
    breakdown = {}
    for material_key in COLOR_LABELS:
        values = input_data.setdefault(material_key, {})
        try:
            wage = int(str(values.get("wage") or 0).replace("٬", "").replace(",", ""))
        except Exception:
            wage = 0
        result = calculate_color_cost(material_key, values, wage)
        values["cost"] = str(result["unit_cost"]) if result["unit_cost"] else ""
        breakdown[material_key] = result
    return input_data, breakdown
