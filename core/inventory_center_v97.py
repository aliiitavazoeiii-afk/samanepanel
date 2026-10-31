from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .brand_colors import darma_material_choices, norm, title_for_material_key
from .excel_views import _decimal, _int
from .inventory_valuation_v17 import finished_inventory_value_v17
from .material_flow import (
    add_warehouse_stock,
    delete_elastic_group,
    delete_fabric_stock,
    transfer_elastic_to_tailor,
    transfer_fabric_to_tailor,
    update_elastic_group,
    update_fabric_stock,
)
from .models import RawMaterialStock
from .report_v5 import _raw_material_context


FABRIC = RawMaterialStock.FABRIC
ELASTIC = RawMaterialStock.ELASTIC
WAREHOUSE = RawMaterialStock.WAREHOUSE
TAILOR = RawMaterialStock.TAILOR
DEPOT = RawMaterialStock.DEPOT


def _material_key_by_title():
    return {norm(label): key for key, label in darma_material_choices() if norm(label)}


def _canonical_material_key(row, key_by_title=None):
    key_by_title = key_by_title or _material_key_by_title()
    title_key = norm(row.title)
    if title_key in key_by_title:
        return key_by_title[title_key]
    if row.material_key:
        return row.material_key
    return f"title:{title_key or row.id}"


def _fabric_location_groups(rows):
    key_by_title = _material_key_by_title()
    grouped = {}
    for row in rows:
        key = _canonical_material_key(row, key_by_title)
        display_title = title_for_material_key(key) if not key.startswith("title:") else row.title
        cell = grouped.setdefault(
            key,
            {
                "key": key,
                "material_key": key if not key.startswith("title:") else (row.material_key or ""),
                "title": display_title or row.title,
                "quantity": Decimal("0"),
                "total_value": 0,
                "unit_price": 0,
                "unit": row.unit or "کیلو",
                "rows": [],
                "row_ids": [],
                "row_count": 0,
            },
        )
        cell["quantity"] += Decimal(row.quantity or 0)
        cell["total_value"] += int(row.total_value or 0)
        cell["rows"].append(row)
        cell["row_ids"].append(row.id)
        cell["row_count"] += 1

    result = []
    for cell in grouped.values():
        qty = Decimal(cell["quantity"] or 0)
        cell["unit_price"] = int(Decimal(cell["total_value"]) / qty) if qty > 0 else 0
        cell["rows"].sort(key=lambda row: row.id)
        cell["row_ids_csv"] = ",".join(str(value) for value in cell["row_ids"])
        result.append(cell)
    return sorted(result, key=lambda item: (norm(item["title"]), item["key"]))


def _fabric_rows_for_group(location, group_key, *, for_update=False):
    qs = RawMaterialStock.objects.filter(
        active=True,
        kind=FABRIC,
        location=location,
    ).order_by("id")
    if for_update:
        qs = qs.select_for_update()
    return [row for row in qs if _canonical_material_key(row) == group_key]


def _transfer_fabric_group_to_tailor(group_key, quantity):
    amount = _decimal(quantity)
    if amount <= 0:
        raise ValueError("وزن انتقال باید بیشتر از صفر باشد.")
    rows = _fabric_rows_for_group(WAREHOUSE, group_key, for_update=True)
    available = sum((max(Decimal(row.quantity or 0), Decimal("0")) for row in rows), Decimal("0"))
    if available < amount:
        title = rows[0].title if rows else title_for_material_key(group_key)
        raise ValueError(f"موجودی پارچه {title} در انبار کافی نیست؛ موجود {available} کیلو.")
    remaining = amount
    for row in rows:
        can_move = min(max(Decimal(row.quantity or 0), Decimal("0")), remaining)
        if can_move <= 0:
            continue
        transfer_fabric_to_tailor(row.id, can_move)
        remaining -= can_move
        if remaining <= 0:
            break


def _material_redirect(request):
    kind = (request.POST.get("return_kind") or "").strip()
    location = (request.POST.get("return_location") or "").strip()
    params = {}
    if kind in {FABRIC, ELASTIC}:
        params["kind"] = kind
    allowed_locations = {WAREHOUSE, TAILOR, DEPOT} if kind == FABRIC else {WAREHOUSE, TAILOR}
    if location in allowed_locations:
        params["location"] = location
    url = "/inventory/materials/"
    if params:
        url += "?" + urlencode(params)
    return redirect(url)


@login_required
def inventory_home(request):
    raw = _raw_material_context()
    return render(
        request,
        "core/inventory_center_v96.html",
        {
            "finished_inventory_total": int(finished_inventory_value_v17()),
            "materials_total": int(raw["materials_total"]),
        },
    )


@login_required
def raw_materials(request):
    raw = _raw_material_context()
    kind = (request.GET.get("kind") or "").strip().lower()
    if kind not in {FABRIC, ELASTIC}:
        kind = ""
    location = (request.GET.get("location") or "").strip().lower()
    allowed_locations = {WAREHOUSE, TAILOR, DEPOT} if kind == FABRIC else {WAREHOUSE, TAILOR}
    if location not in allowed_locations:
        location = ""

    fabric_locations = [
        {"key": WAREHOUSE, "title": "انبار", "total": raw["fabric_warehouse_total"], "groups": _fabric_location_groups(raw["fabric_warehouse"])},
        {"key": TAILOR, "title": "نزد خیاط", "total": raw["fabric_tailor_total"], "groups": _fabric_location_groups(raw["fabric_tailor"])},
        {"key": DEPOT, "title": "دپو", "total": raw["fabric_depot_total"], "groups": _fabric_location_groups(raw["fabric_depot"])},
    ]
    elastic_locations = [
        {"key": WAREHOUSE, "title": "انبار", "total": raw["elastic_warehouse_total"], "groups": raw["elastic_warehouse"]},
        {"key": TAILOR, "title": "نزد خیاط", "total": raw["elastic_tailor_total"], "groups": raw["elastic_tailor"]},
    ]

    selected_location = None
    source = fabric_locations if kind == FABRIC else elastic_locations if kind == ELASTIC else []
    for item in source:
        if item["key"] == location:
            selected_location = item
            break

    raw.update({
        "selected_kind": kind,
        "selected_location_key": location,
        "selected_location": selected_location,
        "fabric_locations_v97": fabric_locations,
        "elastic_locations_v97": elastic_locations,
        "fabric_warehouse_groups_v97": fabric_locations[0]["groups"],
    })
    return render(request, "core/raw_material_inventory_v97.html", raw)


@login_required
@require_POST
@transaction.atomic
def raw_material_action(request):
    action = request.POST.get("action") or ""
    try:
        if action == "fabric_add":
            key = request.POST.get("material_key") or ""
            if not key:
                raise ValueError("رنگ پارچه را انتخاب کن.")
            location = request.POST.get("location") or WAREHOUSE
            add_warehouse_stock(
                kind=FABRIC,
                material_key=key,
                title=title_for_material_key(key),
                quantity=request.POST.get("quantity"),
                unit_price=_int(request.POST.get("unit_price")),
                unit="کیلو",
                note=(request.POST.get("note") or "").strip(),
                location=location,
            )
            messages.success(request, "پارچه اضافه شد و با موجودی همان رنگ به‌صورت تجمیعی نمایش داده می‌شود.")

        elif action == "fabric_transfer_group":
            key = request.POST.get("group_key") or ""
            if not key:
                raise ValueError("رنگ پارچه را انتخاب کن.")
            _transfer_fabric_group_to_tailor(key, request.POST.get("quantity"))
            messages.success(request, "پارچه از انبار به موجودی نزد خیاط منتقل شد.")

        elif action == "fabric_update":
            update_fabric_stock(
                request.POST.get("id"),
                quantity=request.POST.get("quantity"),
                unit_price=_int(request.POST.get("unit_price")),
                note=(request.POST.get("note") or "").strip(),
            )
            messages.success(request, "ثبت پارچه اصلاح شد.")

        elif action == "fabric_delete":
            delete_fabric_stock(request.POST.get("id"))
            messages.success(request, "ثبت پارچه حذف شد.")

        elif action == "fabric_group_delete":
            location = request.POST.get("location") or ""
            key = request.POST.get("group_key") or ""
            rows = _fabric_rows_for_group(location, key, for_update=True)
            if not rows:
                raise ValueError("موجودی این رنگ پیدا نشد.")
            for row in list(rows):
                delete_fabric_stock(row.id)
            messages.success(request, "موجودی این رنگ از این محل حذف شد.")

        elif action == "elastic_add":
            key = request.POST.get("material_key") or ""
            if not key:
                raise ValueError("رنگ کش را انتخاب کن.")
            title = title_for_material_key(key)
            q16 = _decimal(request.POST.get("qty16"))
            q25 = _decimal(request.POST.get("qty25"))
            if q16 > 0:
                add_warehouse_stock(kind=ELASTIC, material_key=key, title=title, quantity=q16, unit_price=_int(request.POST.get("price16")), variant="16", unit="کیلو")
            if q25 > 0:
                add_warehouse_stock(kind=ELASTIC, material_key=key, title=title, quantity=q25, unit_price=_int(request.POST.get("price25")), variant="25", unit="کیلو")
            if q16 <= 0 and q25 <= 0:
                raise ValueError("مقدار کش 16 یا 25 را وارد کن.")
            messages.success(request, "کش به موجودی انبار اضافه شد.")

        elif action == "elastic_transfer":
            key = request.POST.get("material_key") or ""
            if not key:
                raise ValueError("رنگ کش را انتخاب کن.")
            transfer_elastic_to_tailor(key, title_for_material_key(key), request.POST.get("qty16"), request.POST.get("qty25"))
            messages.success(request, "کش از انبار به موجودی نزد خیاط منتقل شد.")

        elif action == "elastic_update":
            key = request.POST.get("material_key") or ""
            if not key:
                raise ValueError("رنگ کش مشخص نیست.")
            update_elastic_group(
                location=request.POST.get("location"),
                material_key=key,
                title=title_for_material_key(key),
                qty16=request.POST.get("qty16"),
                price16=_int(request.POST.get("price16")),
                qty25=request.POST.get("qty25"),
                price25=_int(request.POST.get("price25")),
            )
            messages.success(request, "موجودی کش اصلاح شد.")

        elif action == "elastic_delete":
            key = request.POST.get("material_key") or ""
            if not key:
                raise ValueError("رنگ کش مشخص نیست.")
            delete_elastic_group(location=request.POST.get("location"), material_key=key, title=title_for_material_key(key))
            messages.success(request, "موجودی کش این رنگ حذف شد.")

        else:
            raise ValueError("عملیات مواد اولیه نامعتبر است.")
    except Exception as exc:
        transaction.set_rollback(True)
        messages.error(request, str(exc))

    return _material_redirect(request)
