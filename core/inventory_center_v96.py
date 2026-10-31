from decimal import Decimal

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


def _material_key_by_title():
    return {norm(label): key for key, label in darma_material_choices() if norm(label)}


def _canonical_material_key(row, key_by_title=None):
    """Resolve old/new material keys to one visible color identity.

    Storage rows are intentionally NOT merged: warehouse fabric remains lot-based so
    purchase value / reversal provenance is preserved. Display grouping is keyed by
    normalized color title first, so legacy blank keys, old color:* keys and current
    legacy keys such as ``white`` still render as one visible «سفید» row.
    """
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
                "row_count": 0,
            },
        )
        cell["quantity"] += Decimal(row.quantity or 0)
        cell["total_value"] += int(row.total_value or 0)
        cell["rows"].append(row)
        cell["row_count"] += 1

    result = []
    for cell in grouped.values():
        qty = Decimal(cell["quantity"] or 0)
        cell["unit_price"] = int(Decimal(cell["total_value"]) / qty) if qty > 0 else 0
        cell["rows"].sort(key=lambda row: row.id)
        result.append(cell)
    return sorted(result, key=lambda item: (norm(item["title"]), item["key"]))


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
    raw["fabric_locations_v96"] = [
        {
            "key": RawMaterialStock.WAREHOUSE,
            "title": "انبار",
            "total": raw["fabric_warehouse_total"],
            "groups": _fabric_location_groups(raw["fabric_warehouse"]),
            "can_transfer": True,
            "delete_warning": "این ردیف پارچه حذف شود؟",
        },
        {
            "key": RawMaterialStock.TAILOR,
            "title": "نزد خیاط",
            "total": raw["fabric_tailor_total"],
            "groups": _fabric_location_groups(raw["fabric_tailor"]),
            "can_transfer": False,
            "delete_warning": "این ردیف نزد خیاط حذف شود؟ موجودی آن به انبار برمی‌گردد.",
        },
        {
            "key": RawMaterialStock.DEPOT,
            "title": "دپو",
            "total": raw["fabric_depot_total"],
            "groups": _fabric_location_groups(raw["fabric_depot"]),
            "can_transfer": False,
            "delete_warning": "این ردیف دپو حذف شود؟",
        },
    ]
    raw["elastic_locations_v96"] = [
        {
            "key": RawMaterialStock.WAREHOUSE,
            "title": "کش انبار",
            "total": raw["elastic_warehouse_total"],
            "groups": raw["elastic_warehouse"],
            "delete_warning": "این رنگ کش از انبار حذف شود؟",
        },
        {
            "key": RawMaterialStock.TAILOR,
            "title": "کش نزد خیاط",
            "total": raw["elastic_tailor_total"],
            "groups": raw["elastic_tailor"],
            "delete_warning": "این موجودی نزد خیاط حذف شود؟ مقدار آن به انبار برمی‌گردد.",
        },
    ]
    return render(request, "core/raw_material_inventory_v96.html", raw)


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
            location = request.POST.get("location") or RawMaterialStock.WAREHOUSE
            add_warehouse_stock(
                kind=RawMaterialStock.FABRIC,
                material_key=key,
                title=title_for_material_key(key),
                quantity=request.POST.get("quantity"),
                unit_price=_int(request.POST.get("unit_price")),
                unit="کیلو",
                note=(request.POST.get("note") or "").strip(),
                location=location,
            )
            messages.success(request, "پارچه اضافه شد؛ در جدول با موجودی قبلی همان رنگ تجمیعی نمایش داده می‌شود.")

        elif action == "fabric_transfer":
            transfer_fabric_to_tailor(request.POST.get("source_id"), request.POST.get("quantity"))
            messages.success(request, "پارچه به موجودی نزد خیاط منتقل شد.")

        elif action == "fabric_update":
            update_fabric_stock(
                request.POST.get("id"),
                quantity=request.POST.get("quantity"),
                unit_price=_int(request.POST.get("unit_price")),
                note=(request.POST.get("note") or "").strip(),
            )
            messages.success(request, "ردیف پارچه اصلاح شد.")

        elif action == "fabric_delete":
            delete_fabric_stock(request.POST.get("id"))
            messages.success(request, "ردیف پارچه حذف شد.")

        elif action == "elastic_add":
            key = request.POST.get("material_key") or ""
            if not key:
                raise ValueError("رنگ کش را انتخاب کن.")
            title = title_for_material_key(key)
            q16 = _decimal(request.POST.get("qty16"))
            q25 = _decimal(request.POST.get("qty25"))
            if q16 > 0:
                add_warehouse_stock(
                    kind=RawMaterialStock.ELASTIC,
                    material_key=key,
                    title=title,
                    quantity=q16,
                    unit_price=_int(request.POST.get("price16")),
                    variant="16",
                    unit="کیلو",
                )
            if q25 > 0:
                add_warehouse_stock(
                    kind=RawMaterialStock.ELASTIC,
                    material_key=key,
                    title=title,
                    quantity=q25,
                    unit_price=_int(request.POST.get("price25")),
                    variant="25",
                    unit="کیلو",
                )
            if q16 <= 0 and q25 <= 0:
                raise ValueError("مقدار کش 16 یا 25 را وارد کن.")
            messages.success(request, "کش به موجودی انبار اضافه شد.")

        elif action == "elastic_transfer":
            key = request.POST.get("material_key") or ""
            if not key:
                raise ValueError("رنگ کش را انتخاب کن.")
            transfer_elastic_to_tailor(
                key,
                title_for_material_key(key),
                request.POST.get("qty16"),
                request.POST.get("qty25"),
            )
            messages.success(request, "کش به موجودی نزد خیاط منتقل شد.")

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
            delete_elastic_group(
                location=request.POST.get("location"),
                material_key=key,
                title=title_for_material_key(key),
            )
            messages.success(request, "ردیف کش حذف شد.")

        else:
            raise ValueError("عملیات مواد اولیه نامعتبر است.")
    except Exception as exc:
        transaction.set_rollback(True)
        messages.error(request, str(exc))

    return redirect("inventory_materials")
