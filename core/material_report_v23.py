from collections import OrderedDict
from copy import deepcopy
import json
from decimal import Decimal
from functools import lru_cache

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from . import material_report_v14 as v14
from . import material_report_v20 as v20
from . import material_report_v22 as v22
from .brand_colors import darma_material_choices, title_for_material_key
from .dateutils import format_jalali, parse_jalali_date
from .material_cost_v23 import calculate_model_cost, live_cost_catalog, reset_price_cache, round_money
from .material_flow import ELASTIC, FABRIC, TAILOR, _consume_rows, q
from .models import (
    AppSetting,
    Brand,
    InventoryModelCost,
    InventoryMovement,
    MaterialReportBlock,
    MaterialReportConsumption,
    MaterialReportOutputApplied,
    MaterialReportOutputLocation,
    RawMaterialStock,
    Size,
    StockBalance,
    StockLocation,
)


BASE_MODELS = [
    ("black", "مشکی"),
    ("white", "سفید"),
    ("navy", "سرمه‌ای"),
    ("pink", "صورتی"),
    ("cream", "کرم"),
]
BASE_KEYS = [key for key, _label in BASE_MODELS]
BASE_LABELS = dict(BASE_MODELS)
LEGACY_OUTPUT_LABELS = dict(v20.OUTPUT_MODELS)

DARMA_OUTPUT_SIZES = [
    ("m", "M"),
    ("l", "L"),
    ("xl", "XL"),
    ("xxl", "XXL"),
    ("3xl", "3XL"),
    ("4xl", "4XL"),
]

INPUT_FIELDS = [
    ("fabric_code", "کد پارچه", "text"),
    ("weight", "وزن پارچه", "decimal"),
    ("elastic16_key", "رنگ / مدل کش 16", "elastic16"),
    ("elastic16", "کش تحویلی 16", "decimal"),
    ("elastic25_key", "رنگ / مدل کش 25", "elastic25"),
    ("elastic25", "کش تحویلی 25", "decimal"),
    ("cut", "برش پارچه", "number"),
    ("wage", "مزد دوخت", "money"),
    ("remain16", "کش مانده 16", "decimal"),
    ("remain25", "کش مانده 25", "decimal"),
    ("cost", "قیمت تمام شده", "money"),
]

USER_VALUE_FIELDS = {
    "fabric_code", "weight", "elastic16", "elastic25", "cut", "remain16", "remain25"
}


@lru_cache(maxsize=512)
def _material_label(key):
    if key in BASE_LABELS:
        return BASE_LABELS[key]
    if key in LEGACY_OUTPUT_LABELS:
        return LEGACY_OUTPUT_LABELS[key]
    label = title_for_material_key(key)
    if label and label != key:
        return label
    stock_title = (
        RawMaterialStock.objects.filter(active=True, material_key=key)
        .exclude(title="")
        .values_list("title", flat=True)
        .first()
    )
    return stock_title or key or "نامشخص"


def _output_sizes_for_brand(brand):
    if brand and brand.name == "Novani":
        return list(v20.NOVANI_OUTPUT_SIZES)
    return list(DARMA_OUTPUT_SIZES)


def _output_sizes_for_block(block):
    return _output_sizes_for_brand(block.brand)


def _values_have_input(values):
    values = values or {}
    return any(str(values.get(field) or "").strip() not in {"", "0", "0.0", "0.000"} for field in USER_VALUE_FIELDS)


def _values_have_output(values):
    values = values or {}
    for size_key, _label in DARMA_OUTPUT_SIZES + v20.NOVANI_OUTPUT_SIZES:
        try:
            if int(str(values.get(size_key) or "0").replace(",", "").replace("٬", "")) > 0:
                return True
        except Exception:
            pass
    return False


def _meta_keys(input_data):
    raw = ((input_data or {}).get("_meta") or {}).get("active_material_keys") or []
    return [str(key).strip() for key in raw if str(key).strip()]


def _active_model_keys(block):
    input_data = block.input_data or {}
    output_data = block.output_data or {}
    keys = list(BASE_KEYS)

    for key in _meta_keys(input_data):
        if key not in keys:
            keys.append(key)

    for key, values in input_data.items():
        if key == "_meta":
            continue
        if _values_have_input(values) and key not in keys:
            keys.append(key)

    for key, values in output_data.items():
        if _values_have_output(values) and key not in keys:
            keys.append(key)

    for key in block.output_applications.filter(quantity__gt=0).values_list("model_key", flat=True).distinct():
        if key and key not in keys:
            keys.append(key)

    for key in block.stock_consumptions.filter(kind=FABRIC, quantity__gt=0).values_list("material_key", flat=True).distinct():
        if key and key not in keys:
            keys.append(key)

    return keys


def _blank_input_data():
    data = {key: {} for key in BASE_KEYS}
    data["_meta"] = {"active_material_keys": list(BASE_KEYS)}
    return data


def _blank_output_data_for_brand(brand):
    sizes = _output_sizes_for_brand(brand)
    return {
        key: {**{size_key: "" for size_key, _label in sizes}, "delivery_date": ""}
        for key in BASE_KEYS
    }


@lru_cache(maxsize=1)
def _material_candidate_base():
    choices = OrderedDict()
    for key, label in darma_material_choices():
        choices[str(key)] = label

    rows = RawMaterialStock.objects.filter(active=True, kind=FABRIC).order_by("id")
    for row in rows:
        key = (row.material_key or "").strip()
        if not key:
            continue
        label = _material_label(key)
        if not label or label == key:
            label = row.title or key
        choices.setdefault(key, label)
    return tuple(choices.items())


def _material_candidates(existing_keys=()):
    choices = OrderedDict(_material_candidate_base())
    for key in existing_keys:
        choices.setdefault(key, _material_label(key))
    return list(choices.items())


@lru_cache(maxsize=2)
def _elastic_choice_base(variant):
    choices = OrderedDict()
    rows = RawMaterialStock.objects.filter(
        active=True,
        kind=ELASTIC,
        location=TAILOR,
        variant=str(variant),
    ).order_by("id")
    for row in rows:
        key = (row.material_key or "").strip()
        if not key:
            continue
        label = _material_label(key)
        if not label or label == key:
            label = row.title or key
        choices.setdefault(key, label)
    return tuple(choices.items())


def _elastic_choices(variant, selected_keys=()):
    choices = OrderedDict(_elastic_choice_base(str(variant)))
    for key in selected_keys:
        if key:
            choices.setdefault(key, _material_label(key))
    return list(choices.items())


def _reset_request_caches():
    reset_price_cache()
    _material_label.cache_clear()
    _material_candidate_base.cache_clear()
    _elastic_choice_base.cache_clear()


def _parse_active_keys(request, block=None, extra_key=None):
    existing = _active_model_keys(block) if block else list(BASE_KEYS)
    raw = (request.POST.get("active_material_keys") or "").strip()
    requested = [part.strip() for part in raw.split(",") if part.strip()]
    keys = list(BASE_KEYS)
    for key in requested + existing:
        if key not in keys:
            keys.append(key)
    if extra_key and extra_key not in keys:
        keys.append(extra_key)
    return keys


def _parse_input(request, keys, dozen_wage):
    data = {"_meta": {"active_material_keys": list(keys)}}
    for key in keys:
        values = {}
        for field_key, _label, field_type in INPUT_FIELDS:
            if field_key in {"wage", "cost"}:
                continue
            value = (request.POST.get(f"in_{key}_{field_key}") or "").strip()
            if field_type == "elastic16" and not value:
                value = key
            if field_type == "elastic25" and not value:
                value = key
            values[field_key] = value

        cut = max(0, v20._int(values.get("cut")))
        wage = v20._wage_for_pieces(cut, dozen_wage) if cut else 0
        values["wage"] = str(wage) if wage else ""
        result = calculate_model_cost(key, values, wage)
        values["cost"] = str(result["unit_cost"]) if result["unit_cost"] else ""
        data[key] = values
    return data


DELIVERY_PART_COUNT = 3


def _delivery_parts(values, size_key):
    values = values or {}
    parts_map = values.get("_delivery_parts") or {}
    raw = parts_map.get(size_key)
    if isinstance(raw, (list, tuple)):
        parts = [str(raw[index] or "").strip() if index < len(raw) else "" for index in range(DELIVERY_PART_COUNT)]
        return parts
    # Backward compatibility: every historical single delivery stays numerically
    # identical and appears in the first box; boxes 2/3 start empty.
    return [str(values.get(size_key) or "").strip(), "", ""]


def _parse_output(request, brand, keys):
    data = {}
    sizes = _output_sizes_for_brand(brand)
    for key in keys:
        row = {}
        parts_map = {}
        for size_key, _size_name in sizes:
            raw_parts = [
                request.POST.get(f"out_{key}_{size_key}_{index}")
                for index in range(1, DELIVERY_PART_COUNT + 1)
            ]
            if any(value is not None for value in raw_parts):
                parts = [str(value or "").strip() for value in raw_parts]
            else:
                # Compatibility for an older cached form posting the old single field.
                legacy = (request.POST.get(f"out_{key}_{size_key}") or "").strip()
                parts = [legacy, "", ""]

            total = sum(max(0, v20._int(value)) for value in parts)
            row[size_key] = str(total) if any(parts) else ""
            parts_map[size_key] = parts

        row["_delivery_parts"] = parts_map
        row["delivery_date"] = (request.POST.get(f"delivery_{key}") or "").strip()
        data[key] = row
    return data


def _selected_brand(request):
    return v20._selected_brand(request)


def _set_block_brand(block, request):
    return v20._set_block_brand(block, request)


def _save_block_data(block, request, extra_key=None):
    brand = _set_block_brand(block, request)
    keys = _parse_active_keys(request, block, extra_key=extra_key)
    dozen_wage = v20._dozen_wage()

    block.date = parse_jalali_date(request.POST.get("date") or format_jalali(block.date))
    block.title = (request.POST.get("title") or "").strip()
    block.note = (request.POST.get("note") or "").strip()
    block.input_data = _parse_input(request, keys, dozen_wage)
    block.output_data = _parse_output(request, brand, keys)
    block.delivery_wage = v20._wage_for_pieces(_output_total(block.output_data, brand, keys), dozen_wage)
    block.save()
    return block


def _applied_map(block):
    return {
        (row.model_key, row.size_key): int(row.quantity or 0)
        for row in block.output_applications.all()
    }


def _target_qty(block, model_key, size_key):
    return max(0, v20._int(((block.output_data or {}).get(model_key, {}) or {}).get(size_key)))


def _output_total(output_data, brand, keys):
    total = 0
    for key in keys:
        values = (output_data or {}).get(key, {}) or {}
        for size_key, _label in _output_sizes_for_brand(brand):
            total += max(0, v20._int(values.get(size_key)))
    return total


def _output_stats(block, keys):
    applied = _applied_map(block)
    entered_total = applied_total = pending_total = 0
    rows = {}
    for key in keys:
        entered_row = applied_row = 0
        for size_key, _label in _output_sizes_for_block(block):
            target = _target_qty(block, key, size_key)
            done = int(applied.get((key, size_key), 0))
            entered_total += target
            applied_total += done
            pending_total += max(0, target - done)
            entered_row += target
            applied_row += done
        rows[key] = {
            "entered": entered_row,
            "applied": applied_row,
            "pending": max(0, entered_row - applied_row),
        }
    return {
        "entered": entered_total,
        "applied": applied_total,
        "pending": pending_total,
        "rows": rows,
    }


def _live_input_data(block, keys):
    source = deepcopy(block.input_data or {})
    live = {"_meta": {"active_material_keys": list(keys)}}
    dozen_wage = v20._dozen_wage()
    for key in keys:
        values = deepcopy(source.get(key, {}) or {})
        values.setdefault("elastic16_key", key)
        values.setdefault("elastic25_key", key)
        cut = max(0, v20._int(values.get("cut")))
        wage = v20._wage_for_pieces(cut, dozen_wage) if cut else 0
        values["wage"] = str(wage) if wage else ""
        result = calculate_model_cost(key, values, wage)
        values["cost"] = str(result["unit_cost"]) if result["unit_cost"] else ""
        values["_cost_breakdown"] = result
        live[key] = values
    return live


def _view_block(block):
    keys = _active_model_keys(block)
    live_input = _live_input_data(block, keys)
    stats = _output_stats(block, keys)
    sizes = _output_sizes_for_block(block)

    selected16 = [live_input.get(key, {}).get("elastic16_key") or key for key in keys]
    selected25 = [live_input.get(key, {}).get("elastic25_key") or key for key in keys]
    choices16 = _elastic_choices("16", selected16)
    choices25 = _elastic_choices("25", selected25)

    input_rows = []
    for field_key, label, field_type in INPUT_FIELDS:
        cells = []
        for key in keys:
            values = live_input.get(key, {}) or {}
            cell = {
                "name": f"in_{key}_{field_key}",
                "value": values.get(field_key, ""),
                "type": field_type,
                "material_key": key,
                "readonly": field_key in {"wage", "cost"},
            }
            if field_type == "elastic16":
                cell["choices"] = choices16
            elif field_type == "elastic25":
                cell["choices"] = choices25
            cells.append(cell)
        input_rows.append({"field_key": field_key, "label": label, "cells": cells})

    output_rows = []
    output_data = block.output_data or {}
    for key in keys:
        values = output_data.get(key, {}) or {}
        cells = []
        for size_key, _label in sizes:
            parts = _delivery_parts(values, size_key)
            cells.append({
                "name": f"out_{key}_{size_key}",
                "value": values.get(size_key, ""),
                "parts": [
                    {
                        "name": f"out_{key}_{size_key}_{index}",
                        "value": parts[index - 1],
                        "index": index,
                    }
                    for index in range(1, DELIVERY_PART_COUNT + 1)
                ],
            })
        row_total = sum(max(0, v20._int(values.get(size_key))) for size_key, _label in sizes)
        cut_source = key
        legacy_source = v22.CUT_SOURCE.get(key, key)
        if legacy_source != key:
            own_cut = max(0, v20._int((live_input.get(key) or {}).get("cut")))
            legacy_cut = max(0, v20._int((live_input.get(legacy_source) or {}).get("cut")))
            if own_cut <= 0 and legacy_cut > 0:
                cut_source = legacy_source
        cut_total = max(0, v20._int((live_input.get(cut_source) or {}).get("cut")))
        applied = stats["rows"][key]["applied"]
        sync_delta = row_total - applied
        output_rows.append({
            "model_key": key,
            "cut_source": cut_source,
            "label": _material_label(key),
            "cells": cells,
            "total": row_total,
            "cut_total": cut_total,
            "cut_diff": row_total - cut_total,
            "cut_diff_abs": abs(row_total - cut_total),
            "applied_total": applied,
            "pending_total": max(0, sync_delta),
            "reduction_total": max(0, -sync_delta),
        })

    total_cost = Decimal("0")
    total_cut = Decimal("0")
    for key in keys:
        result = (live_input.get(key) or {}).get("_cost_breakdown") or {}
        cut_qty = Decimal(result.get("cut_qty") or 0)
        if cut_qty <= 0:
            continue
        total_cut += cut_qty
        total_cost += Decimal(int(result.get("total_cost") or 0))
    average_cost = round_money(total_cost / total_cut) if total_cut > 0 else 0

    used_keys = []
    fabric_codes = []
    for key in keys:
        in_values = live_input.get(key, {}) or {}
        out_values = output_data.get(key, {}) or {}
        if _values_have_input(in_values) or _values_have_output(out_values):
            used_keys.append(key)
        code = str(in_values.get("fabric_code") or "").strip()
        if code and code not in fabric_codes:
            fabric_codes.append(code)

    candidates = [
        (key, label)
        for key, label in _material_candidates(keys)
        if key not in keys
    ]

    all_elastic_keys = [key for key, _label in choices16 + choices25]
    cost_catalog = live_cost_catalog(keys, all_elastic_keys)

    material_model_keys = [
        key for key in keys
        if (
            str((live_input.get(key) or {}).get("fabric_code") or "").strip()
            or q((live_input.get(key) or {}).get("weight")) > 0
            or v20._int((live_input.get(key) or {}).get("cut")) > 0
        )
    ]
    applied_fabric_keys = {
        row.material_key for row in block.stock_consumptions.all()
        if row.kind == FABRIC and q(row.quantity) > 0
    }

    return {
        "obj": block,
        "jalali_date": format_jalali(block.date),
        "active_keys": keys,
        "active_keys_csv": ",".join(keys),
        "model_headers": [{"key": key, "label": _material_label(key)} for key in keys],
        "input_rows": input_rows,
        "output_rows": output_rows,
        "output_sizes": sizes,
        "materials_applied": block.stock_consumptions.exists(),
        "materials_all_applied": bool(material_model_keys) and all(
            key in applied_fabric_keys for key in material_model_keys
        ),
        "material_consumption_count": block.stock_consumptions.count(),
        "output_entered": stats["entered"],
        "output_applied": stats["applied"],
        "output_pending": stats["pending"],
        "output_reduction": sum(row["reduction_total"] for row in output_rows),
        "destination_label": "خورشید دارما" if block.brand.name == "دارما" else "موجودی Novani",
        "average_cost": average_cost,
        "used_model_labels": [_material_label(key) for key in used_keys],
        "fabric_codes": fabric_codes,
        "add_model_choices": candidates,
        "elastic16_choices": choices16,
        "elastic25_choices": choices25,
        "cost_catalog": cost_catalog,
        "cost_catalog_json": json.dumps(cost_catalog, ensure_ascii=False),
    }


def _validate_output_editable(block):
    allowed_sizes = {key for key, _label in _output_sizes_for_block(block)}
    active = set(_active_model_keys(block))
    for applied in block.output_applications.all():
        if int(applied.quantity or 0) <= 0:
            continue
        if applied.size_key not in allowed_sizes:
            raise ValueError(
                f"این صورت یک تحویل قدیمی در سایز {applied.size_key} دارد که با سایزبندی فعلی "
                f"{block.brand.name} سازگار نیست؛ برای حفظ موجودی تغییر خودکار انجام نشد."
            )
        if applied.model_key not in active:
            raise ValueError("مدل دارای تحویل اعمال‌شده از صورت حذف شده است؛ عملیات متوقف شد.")


def _production_objects(block, model_key, size_key):
    label = _material_label(model_key)
    size_name = dict(_output_sizes_for_block(block))[size_key]
    brand = block.brand
    color = v20._find_color(label)
    size = Size.objects.get(name=size_name)
    destination, destination_label = v20._destination_for_brand(brand)
    return brand, color, size, destination, destination_label, label, size_name


def _total_stock_qty(brand, color, size):
    return int(StockBalance.objects.filter(brand=brand, color=color, size=size).aggregate(v=Sum("qty"))["v"] or 0)


def _model_unit_cost(block, model_key, current_cost):
    source_key = v14.COST_SOURCE.get(model_key, model_key)
    values = (block.input_data or {}).get(source_key, {}) or {}
    value = v20._int(values.get("cost"))
    return value if value > 0 else int(current_cost or 61000)


def _sync_darma_stock_costed(block, model_key, size_key, delta, destination=None):
    if delta == 0:
        return
    brand, color, size, default_destination, _destination_label, label, size_name = _production_objects(
        block, model_key, size_key
    )
    destination = destination or default_destination
    if brand.name != "دارما" or destination.key not in {StockLocation.KHORSHID, StockLocation.HOME}:
        raise ValueError("مسیر موجودی تولید دارما معتبر نیست.")

    stock, _ = StockBalance.objects.get_or_create(
        brand=brand, color=color, size=size, location=destination, defaults={"qty": 0}
    )
    stock = StockBalance.objects.select_for_update().get(pk=stock.pk)
    cost_row, _ = InventoryModelCost.objects.get_or_create(
        brand=brand, color=color, size=size, defaults={"unit_cost": 61000}
    )
    cost_row = InventoryModelCost.objects.select_for_update().get(pk=cost_row.pk)

    current_cost = int(cost_row.unit_cost or 61000)
    batch_cost = _model_unit_cost(block, model_key, current_cost)
    total_before = _total_stock_qty(brand, color, size)
    qty = abs(int(delta))

    if delta > 0:
        new_total = total_before + qty
        if new_total > 0:
            new_cost = round_money(
                (Decimal(total_before) * Decimal(current_cost) + Decimal(qty) * Decimal(batch_cost))
                / Decimal(new_total)
            )
            cost_row.unit_cost = max(0, new_cost)
            cost_row.save(update_fields=["unit_cost", "updated_at"])
        stock.qty = int(stock.qty or 0) + qty
        stock.save(update_fields=["qty"])
        return

    if int(stock.qty or 0) < qty:
        raise ValueError(
            f"برای کاهش تحویل، موجودی {label} / {size_name} در {destination.title} کافی نیست. "
            "هیچ تغییری اعمال نشد."
        )
    remaining_total = total_before - qty
    if remaining_total < 0:
        raise ValueError(f"موجودی کل {label} / {size_name} از مقدار اصلاح کمتر است.")
    if remaining_total > 0:
        remaining_value = Decimal(total_before) * Decimal(current_cost) - Decimal(qty) * Decimal(batch_cost)
        new_cost = round_money(max(Decimal("0"), remaining_value) / Decimal(remaining_total))
        cost_row.unit_cost = max(0, new_cost)
        cost_row.save(update_fields=["unit_cost", "updated_at"])
    stock.qty = int(stock.qty or 0) - qty
    stock.save(update_fields=["qty"])


def desired_consumption(block, keys=None):
    desired = {}
    for key in (_active_model_keys(block) if keys is None else keys):
        values = (block.input_data or {}).get(key, {}) or {}

        fabric = max(q(values.get("weight")), Decimal("0"))
        if fabric:
            desired[(FABRIC, key, "")] = desired.get((FABRIC, key, ""), Decimal("0")) + fabric

        delivered16 = max(q(values.get("elastic16")), Decimal("0"))
        delivered25 = max(q(values.get("elastic25")), Decimal("0"))
        remain16_raw = values.get("remain16")
        remain25_raw = values.get("remain25")
        used16 = delivered16 - q(remain16_raw) if remain16_raw not in (None, "") else delivered16
        used25 = delivered25 - q(remain25_raw) if remain25_raw not in (None, "") else delivered25
        used16 = max(used16, Decimal("0"))
        used25 = max(used25, Decimal("0"))

        elastic16_key = (values.get("elastic16_key") or key or "").strip()
        elastic25_key = (values.get("elastic25_key") or key or "").strip()
        if used16:
            if not elastic16_key:
                raise ValueError(f"برای {_material_label(key)} رنگ/مدل کش 16 را انتخاب کن.")
            consume_key = (ELASTIC, elastic16_key, "16")
            desired[consume_key] = desired.get(consume_key, Decimal("0")) + used16
        if used25:
            if not elastic25_key:
                raise ValueError(f"برای {_material_label(key)} رنگ/مدل کش 25 را انتخاب کن.")
            consume_key = (ELASTIC, elastic25_key, "25")
            desired[consume_key] = desired.get(consume_key, Decimal("0")) + used25
    return desired


@transaction.atomic
def sync_report_consumption(block):
    desired = desired_consumption(block)
    existing = {
        (row.kind, row.material_key, row.variant): row
        for row in MaterialReportConsumption.objects.select_for_update().filter(block=block)
    }
    for key in set(desired) | set(existing):
        old = q(existing[key].quantity) if key in existing else Decimal("0")
        new = q(desired.get(key, 0))
        _consume_rows(key[0], key[1], key[2], new - old)
        if new == 0:
            if key in existing:
                existing[key].delete()
        elif key in existing:
            existing[key].quantity = new
            existing[key].save(update_fields=["quantity"])
        else:
            MaterialReportConsumption.objects.create(
                block=block,
                kind=key[0],
                material_key=key[1],
                variant=key[2],
                quantity=new,
            )


def _output_destination(brand, destination_key=None):
    """Choose one warehouse for NEW output only; older applied pieces do not move."""
    default, default_title = v20._destination_for_brand(brand)
    if not destination_key:
        # Compatibility for existing internal calls and legacy tests.
        return default, default_title
    key = str(destination_key).strip()
    allowed = {StockLocation.HOME, StockLocation.KHORSHID} if brand.name == "دارما" else {StockLocation.HOME}
    if key not in allowed:
        raise ValueError("انبار مقصد مجاز نیست؛ برای دارما «خانه» یا «خورشید» را انتخاب کن.")
    location = StockLocation.objects.filter(key=key).first()
    if location is None:
        raise ValueError("انبار مقصد در سیستم موجودی تعریف نشده است.")
    if brand.name == "دارما":
        return location, "خانه دارما" if key == StockLocation.HOME else "خورشید دارما"
    return location, default_title


def _output_location_rows(applied, brand):
    """Initialize historical allocations only in the old fixed destination.

    The existing MaterialReportOutputApplied.quantity remains the single
    authoritative per-model/size applied total. Allocation rows are a breakdown
    of that same total, NEVER additional inventory.
    """
    existing = list(
        MaterialReportOutputLocation.objects.select_for_update()
        .filter(applied=applied).select_related("location").order_by("location_id")
    )
    done = int(applied.quantity or 0)
    if not existing and done > 0:
        legacy_destination, _ = v20._destination_for_brand(brand)
        existing = [
            MaterialReportOutputLocation.objects.create(
                applied=applied, location=legacy_destination, quantity=done
            )
        ]
    if sum(int(row.quantity or 0) for row in existing) != done:
        raise ValueError(
            "ریز انبارهای این تحویل با تعداد اعمال‌شده سازگار نیست. "
            "برای جلوگیری از جابه‌جایی یا ثبت دوباره، همگام‌سازی متوقف شد."
        )
    return existing


def _sync_output(block, destination_key=None):
    if block.brand.name not in {"دارما", "Novani"}:
        raise ValueError("برند صورت مواد معتبر نیست.")

    selected_destination, selected_label = _output_destination(block.brand, destination_key)
    _validate_output_editable(block)
    keys = _active_model_keys(block)
    operations = []
    applied_total_before = 0
    target_total = 0

    for model_key in keys:
        for size_key, _size_label in _output_sizes_for_block(block):
            target = _target_qty(block, model_key, size_key)
            applied, _ = MaterialReportOutputApplied.objects.select_for_update().get_or_create(
                block=block,
                model_key=model_key,
                size_key=size_key,
                defaults={"quantity": 0},
            )
            done = int(applied.quantity or 0)
            location_rows = _output_location_rows(applied, block.brand)
            delta = target - done
            applied_total_before += done
            target_total += target
            if delta == 0:
                continue

            brand, color, size, _legacy_location, _old_label, label, size_name = _production_objects(
                block, model_key, size_key
            )
            moves = []
            if delta > 0:
                # Exactly one destination for every NEW color/size in this click.
                moves.append((selected_destination, delta))
            else:
                # Reverse only quantities attributable to their ACTUAL stock
                # locations. Prefer the selected destination when it holds any
                # of this sheet's already-applied pieces; never move old stock.
                remaining = abs(delta)
                ordered = sorted(
                    location_rows,
                    key=lambda row: (row.location_id != selected_destination.id, row.location_id),
                )
                for row in ordered:
                    removable = min(remaining, int(row.quantity or 0))
                    if removable:
                        moves.append((row.location, -removable))
                        remaining -= removable
                    if not remaining:
                        break
                if remaining:
                    raise ValueError("مقدار اصلاح از تحویل‌های قبلاً اعمال‌شده بیشتر است.")

            # Validate reduction availability before applying any of the batch.
            for location, change in moves:
                if change < 0:
                    available = int(
                        StockBalance.objects.select_for_update().filter(
                            brand=brand, color=color, size=size, location=location
                        ).values_list("qty", flat=True).first() or 0
                    )
                    if available < abs(change):
                        raise ValueError(
                            f"برای کاهش {abs(change)} عدد از {label}/{size_name} "
                            f"موجودی {location.title} کافی نیست (موجودی: {available}). "
                            "هیچ تغییری اعمال نشد."
                        )
            operations.append((applied, target, brand, color, size, label, size_name, model_key, size_key, moves))

    wage_ledger = v22._lock_or_initialize_wage_ledger(block, applied_total_before)
    rate = int(v20._dozen_wage())
    wage_before = int(v20._wage_for_pieces(applied_total_before, rate))
    wage_after = int(v20._wage_for_pieces(target_total, rate))
    wage_change = wage_after - wage_before
    details = []

    for applied, target, brand, color, size, label, size_name, model_key, size_key, moves in operations:
        for location, change in moves:
            if brand.name == "Novani":
                v20._apply_novani_stock(brand, color, size, location, change)
            elif brand.name == "دارما":
                _sync_darma_stock_costed(block, model_key, size_key, change, destination=location)
            else:
                raise ValueError("برند صورت مواد معتبر نیست.")

            InventoryMovement.objects.create(
                movement_type=InventoryMovement.PRODUCTION,
                brand=brand,
                color=color,
                size=size,
                location=location,
                delta=change,
                reference=f"material-report:{block.id}:output-sync-v112",
            )
            allocated, _ = MaterialReportOutputLocation.objects.select_for_update().get_or_create(
                applied=applied,
                location=location,
                defaults={"quantity": 0},
            )
            allocated.quantity = int(allocated.quantity or 0) + change
            if allocated.quantity < 0:
                raise ValueError("ریز تحویل انبار نمی‌تواند منفی شود.")
            if allocated.quantity == 0:
                allocated.delete()
            else:
                allocated.save(update_fields=["quantity"])
            details.append(f"{label}/{size_name} / {location.title}: {change:+d}")

        applied.quantity = target
        applied.save(update_fields=["quantity", "updated_at"])

    if wage_change:
        v20._adjust_tailor_balance(-wage_change)

    wage_ledger.value = str(target_total)
    wage_ledger.save(update_fields=["value"])
    block.delivery_wage = wage_after
    block.save(update_fields=["delivery_wage", "updated_at"])

    return {
        "brand": block.brand.name,
        "destination": selected_label,
        "before_total": applied_total_before,
        "after_total": target_total,
        "piece_delta": target_total - applied_total_before,
        "wage_before": wage_before,
        "wage_after": wage_after,
        "wage_change": wage_change,
        "details": details,
    }


@login_required
def material_report(request):
    _reset_request_caches()
    brands = v20._material_brands()
    if request.method == "POST":
        try:
            brand = _selected_brand(request)
            block = MaterialReportBlock.objects.create(
                date=parse_jalali_date(request.POST.get("date") or v20._today_jalali()),
                title=(request.POST.get("title") or "").strip(),
                brand=brand,
                input_data=_blank_input_data(),
                output_data=_blank_output_data_for_brand(brand),
            )
            messages.success(request, f"صورت جدید برای {brand.name} ساخته شد؛ هنوز هیچ اثری روی موجودی ندارد.")
            return redirect(f"/material-report/#block-{block.id}")
        except Exception as exc:
            messages.error(request, str(exc))
            return redirect("material_report")

    blocks = [
        _view_block(obj)
        for obj in MaterialReportBlock.objects.select_related("brand").prefetch_related(
            "output_applications", "stock_consumptions"
        ).all()[:40]
    ]
    return render(
        request,
        "core/material_report_v36.html",
        {
            "blocks": blocks,
            "brands": brands,
            "today_j": v20._today_jalali(),
            "sewing_wage_rate": v20._dozen_wage(),
        },
    )


@login_required
@require_POST
def material_block_add_model(request, block_id):
    _reset_request_caches()
    try:
        with transaction.atomic():
            block = MaterialReportBlock.objects.select_for_update().select_related("brand").get(id=block_id)
            key = (request.POST.get("add_material_key") or "").strip()
            allowed = {k for k, _label in _material_candidates(_active_model_keys(block))}
            if not key or key not in allowed:
                raise ValueError("مدل/رنگ انتخاب‌شده معتبر نیست.")
            _save_block_data(block, request, extra_key=key)
            _validate_output_editable(block)
        messages.success(request, f"{_material_label(key)} به این صورت اضافه شد.")
    except MaterialReportBlock.DoesNotExist:
        messages.error(request, "صورت پیدا نشد.")
    except Exception as exc:
        messages.error(request, f"افزودن مدل انجام نشد: {exc}")
    return redirect(f"/material-report/#block-{block_id}")


@login_required
@require_POST
def material_block_save(request, block_id):
    _reset_request_caches()
    try:
        with transaction.atomic():
            block = MaterialReportBlock.objects.select_for_update().select_related("brand").get(id=block_id)
            _save_block_data(block, request)
            _validate_output_editable(block)
        messages.success(request, "صورت ذخیره شد؛ قیمت تمام‌شده با فی فعلی مواد نزد خیاط دوباره محاسبه شد.")
    except MaterialReportBlock.DoesNotExist:
        messages.error(request, "صورت پیدا نشد.")
    except Exception as exc:
        messages.error(request, f"ذخیره انجام نشد: {exc}")
    return redirect(f"/material-report/#block-{block_id}")


@login_required
@require_POST
def material_block_apply_materials(request, block_id):
    _reset_request_caches()
    try:
        with transaction.atomic():
            block = MaterialReportBlock.objects.select_for_update().select_related("brand").get(id=block_id)
            _save_block_data(block, request)
            _validate_output_editable(block)
            before = block.stock_consumptions.aggregate(v=Sum("quantity"))["v"] or 0
            from .material_color_apply_v123 import sync_all_colors
            sync_all_colors(block)
            after = block.stock_consumptions.aggregate(v=Sum("quantity"))["v"] or 0
        messages.success(
            request,
            f"مصرف مواد همگام شد. پارچه و کش دقیقاً از منابع انتخاب‌شده نزد خیاط کم/اصلاح شدند. "
            f"مصرف ثبت‌شده: {after} (قبل: {before}).",
        )
    except MaterialReportBlock.DoesNotExist:
        messages.error(request, "صورت پیدا نشد.")
    except Exception as exc:
        messages.error(request, f"اعمال مواد انجام نشد و کل عملیات برگشت: {exc}")
    return redirect(f"/material-report/#block-{block_id}")


@login_required
@require_POST
def material_block_apply_color(request, block_id):
    """Apply ONLY selected color's fabric and elastic from tailor stock."""
    from .material_color_apply_v123 import sync_one_color
    _reset_request_caches()
    try:
        with transaction.atomic():
            block = MaterialReportBlock.objects.select_for_update().select_related("brand").get(pk=block_id)
            model_key = str(request.POST.get("material_color_key") or "").strip()
            if model_key not in _active_model_keys(block):
                raise ValueError("رنگ انتخاب‌شده در این صورت وجود ندارد.")
            # Preserve the existing form-save mechanics and inventory-output floor.
            _save_block_data(block, request)
            _validate_output_editable(block)
            sync_one_color(block, model_key)
        messages.success(request, f"مواد اولیه و کش فقط رنگ «{_material_label(model_key)}» اعمال/همگام شد؛ سایر رنگ‌ها تغییری نکردند.")
    except Exception as exc:
        messages.error(request, f"اعمال تک‌رنگ انجام نشد؛ همه تغییرات برگشت: {exc}")
    return redirect(f"/material-report/#block-{block_id}")


@login_required
@require_POST
def material_block_apply_output(request, block_id):
    _reset_request_caches()
    try:
        with transaction.atomic():
            block = MaterialReportBlock.objects.select_for_update().select_related("brand").get(id=block_id)
            _save_block_data(block, request)
            selected_key = (request.POST.get("delivery_destination") or "").strip()
            if block.brand.name == "دارما" and selected_key not in {StockLocation.HOME, StockLocation.KHORSHID}:
                raise ValueError("برای همگام‌سازی تحویل دارما ابتدا انبار خانه یا خورشید را انتخاب کن.")
            if block.brand.name == "Novani" and selected_key != StockLocation.HOME:
                raise ValueError("تحویل Novani فقط به موجودی خودش در انبار خانه افزوده می‌شود.")
            result = _sync_output(block, destination_key=selected_key)
        messages.success(
            request,
            f"تحویل {result['brand']} همگام شد: {result['piece_delta']:+d} عدد؛ "
            f"مزد: {result['wage_change']:+d} تومان. مقصد: {result['destination']}.",
        )
    except MaterialReportBlock.DoesNotExist:
        messages.error(request, "صورت پیدا نشد.")
    except Exception as exc:
        messages.error(request, f"همگام‌سازی تحویل انجام نشد و کل عملیات برگشت: {exc}")
    return redirect(f"/material-report/#block-{block_id}")
