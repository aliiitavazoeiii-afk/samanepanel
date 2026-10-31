from collections import defaultdict
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .brand_colors import darma_material_choices, title_for_material_key
from .dateutils import format_jalali
from .excel_views import DISPLAY_SIZES, _add_metrics, _decimal, _empty_metrics, _finish_metrics, _int, _period_range
from .finance import sale_line_metrics
from .material_flow import (
    add_warehouse_stock, delete_elastic_group, delete_fabric_stock,
    transfer_elastic_to_tailor, transfer_fabric_to_tailor,
    update_elastic_group, update_fabric_stock,
)
from .models import ExcelManualRow, ExcelManualSetting, InventoryModelCost, RawMaterialStock, SaleLine, StockBalance


def _finished_inventory_value():
    cost_map = {(r.brand_id, r.color_id, r.size_id): int(r.unit_cost or 0) for r in InventoryModelCost.objects.all()}
    total = 0
    for row in StockBalance.objects.values("brand_id", "color_id", "size_id").annotate(qty=Sum("qty")):
        total += int(row["qty"] or 0) * cost_map.get((row["brand_id"], row["color_id"], row["size_id"]), 0)
    return total


def _fabric_tailor_groups(rows):
    """Presentation-only grouping: one visible tailor row per material_key.

    Raw rows stay untouched because they preserve the warehouse source lot used for
    purchase reversal. The UI receives one stable color/model row whose quantity and
    value are the sum of those internal rows.
    """
    grouped = {}
    for row in rows:
        key = row.material_key or f"legacy-{row.id}"
        cell = grouped.setdefault(
            key,
            {
                "key": key,
                "material_key": row.material_key,
                "title": title_for_material_key(row.material_key) or row.title,
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
        result.append(cell)
    return sorted(result, key=lambda x: (x["title"], x["key"]))


def _elastic_group(rows):
    grouped = {}
    for row in rows:
        key = row.material_key or f"legacy-{row.id}"
        if key not in grouped:
            grouped[key] = {
                "key": key, "title": row.title,
                "q16": Decimal("0"), "q25": Decimal("0"),
                "p16": 0, "p25": 0, "v16": 0, "v25": 0,
            }
        cell = grouped[key]
        variant = row.variant or ("16" if "16" in (row.title or "") else "25" if "25" in (row.title or "") else "")
        if variant == "16":
            cell["q16"] += Decimal(row.quantity or 0)
            cell["p16"] = int(row.unit_price or cell["p16"] or 0)
            cell["v16"] += row.total_value
        elif variant == "25":
            cell["q25"] += Decimal(row.quantity or 0)
            cell["p25"] = int(row.unit_price or cell["p25"] or 0)
            cell["v25"] += row.total_value
    result = []
    for cell in grouped.values():
        cell["total"] = cell["v16"] + cell["v25"]
        result.append(cell)
    return sorted(result, key=lambda x: x["title"])


def _raw_material_context():
    rows = list(RawMaterialStock.objects.filter(active=True).order_by("kind", "location", "id"))
    fw = [r for r in rows if r.kind == RawMaterialStock.FABRIC and r.location == RawMaterialStock.WAREHOUSE]
    ft = [r for r in rows if r.kind == RawMaterialStock.FABRIC and r.location == RawMaterialStock.TAILOR]
    ft_groups = _fabric_tailor_groups(ft)
    fd = [r for r in rows if r.kind == RawMaterialStock.FABRIC and r.location == RawMaterialStock.DEPOT]
    ew_raw = [r for r in rows if r.kind == RawMaterialStock.ELASTIC and r.location == RawMaterialStock.WAREHOUSE]
    et_raw = [r for r in rows if r.kind == RawMaterialStock.ELASTIC and r.location == RawMaterialStock.TAILOR]
    fw_total = sum(r.total_value for r in fw)
    ft_total = sum(r.total_value for r in ft)
    fd_total = sum(r.total_value for r in fd)
    ew_total = sum(r.total_value for r in ew_raw)
    et_total = sum(r.total_value for r in et_raw)
    fabric_total = fw_total + ft_total + fd_total
    elastic_total = ew_total + et_total
    return {
        "fabric_warehouse": fw, "fabric_tailor": ft, "fabric_tailor_groups": ft_groups, "fabric_depot": fd,
        "elastic_warehouse": _elastic_group(ew_raw), "elastic_tailor": _elastic_group(et_raw),
        "fabric_warehouse_total": fw_total, "fabric_tailor_total": ft_total, "fabric_depot_total": fd_total,
        "elastic_warehouse_total": ew_total, "elastic_tailor_total": et_total,
        "fabric_total": fabric_total, "elastic_total": elastic_total,
        "materials_total": fabric_total + elastic_total,
        "material_colors": darma_material_choices(),
    }


@login_required
def report(request):
    period, start, end = _period_range(request)
    lines = list(
        SaleLine.objects.filter(day__date__gte=start, day__date__lte=end, quantity__gt=0)
        .select_related("day", "product_size__product__brand", "product_size__product", "product_size__size")
        .prefetch_related("product_size__product__composition__color")
    )
    brand_totals = defaultdict(_empty_metrics)
    brand_sizes = defaultdict(lambda: defaultdict(_empty_metrics))
    product_profit = defaultdict(lambda: defaultdict(int))
    color_sales = defaultdict(lambda: defaultdict(int))
    overall = _empty_metrics()
    for line in lines:
        metrics = sale_line_metrics(line)
        brand = line.product_size.product.brand.name
        size = line.product_size.size.name
        _add_metrics(brand_totals[brand], metrics)
        _add_metrics(brand_sizes[brand][size], metrics)
        _add_metrics(overall, metrics)
        if brand == "دارما":
            product_profit[line.product_size.product.code][size] += metrics["profit"]
            for comp in line.product_size.product.composition.all():
                color_sales[comp.color.name][size] += int(line.quantity) * int(comp.qty)
    for values in brand_totals.values():
        _finish_metrics(values)
    for size_map in brand_sizes.values():
        for values in size_map.values():
            _finish_metrics(values)
    _finish_metrics(overall)

    brands_view = []
    for brand_name in ["تکوین", "دارما"]:
        sizes = ["M", "L", "XL", "XXL"] if brand_name == "تکوین" else DISPLAY_SIZES
        brands_view.append({"name": brand_name, "total": brand_totals[brand_name], "sizes": [(s, brand_sizes[brand_name][s]) for s in sizes]})

    product_rows = []
    for code, values in sorted(product_profit.items()):
        cells = [values.get(size, 0) for size in DISPLAY_SIZES]
        product_rows.append({"code": code, "cells": cells, "total": sum(cells)})
    product_rows.sort(key=lambda row: row["total"], reverse=True)
    color_rows = []
    for color, values in color_sales.items():
        cells = [values.get(size, 0) for size in DISPLAY_SIZES]
        color_rows.append({"color": color, "cells": cells, "total": sum(cells)})
    color_rows.sort(key=lambda row: row["total"], reverse=True)

    manual_rows = ExcelManualRow.objects.filter(active=True)
    accounts_rows = list(manual_rows.filter(section=ExcelManualRow.ACCOUNTS).order_by("sort_order", "id"))
    person_rows = list(manual_rows.filter(section=ExcelManualRow.PERSONS).order_by("sort_order", "id"))
    asset_rows = list(manual_rows.filter(section=ExcelManualRow.ASSETS).order_by("sort_order", "id"))
    settings = {obj.key: obj for obj in ExcelManualSetting.objects.all()}
    takvin_debt = settings.get("takvin_debt").value if settings.get("takvin_debt") else 0
    digikala_receivable = settings.get("digikala_receivable").value if settings.get("digikala_receivable") else 0
    accounts_total = sum(row.amount for row in accounts_rows) + sum(row.amount for row in person_rows)
    assets_total = sum(row.amount for row in asset_rows)
    finished_inventory_total = _finished_inventory_value()
    raw = _raw_material_context()
    inventory_total = finished_inventory_total + raw["materials_total"]
    capital_total = accounts_total + inventory_total + digikala_receivable - takvin_debt + assets_total

    context = {
        "period": period, "start": format_jalali(start), "end": format_jalali(end),
        "overall": overall, "brands": brands_view, "display_sizes": DISPLAY_SIZES,
        "product_rows": product_rows, "color_rows": color_rows,
        "accounts_rows": accounts_rows, "person_rows": person_rows, "asset_rows": asset_rows,
        "accounts_total": accounts_total, "assets_total": assets_total,
        "finished_inventory_total": finished_inventory_total, "inventory_total": inventory_total,
        "capital_total": capital_total, "takvin_debt": takvin_debt, "digikala_receivable": digikala_receivable,
    }
    context.update(raw)
    return render(request, "core/report_excel_v2.html", context)


@login_required
@require_POST
def manual_report_action(request):
    action = request.POST.get("action")
    try:
        if action == "setting":
            key = request.POST.get("key")
            labels = {"takvin_debt": "بدهی تکوین", "digikala_receivable": "طلب دیجی‌کالا"}
            if key not in labels:
                raise ValueError("فیلد ناشناخته است.")
            obj, _ = ExcelManualSetting.objects.get_or_create(key=key, defaults={"label": labels[key]})
            obj.value = _int(request.POST.get("value"))
            obj.label = labels[key]
            obj.save(update_fields=["value", "label", "updated_at"])

        elif action in {"save_row", "add_row", "delete_row"}:
            allowed = {ExcelManualRow.ACCOUNTS, ExcelManualRow.PERSONS, ExcelManualRow.ASSETS}
            if action == "save_row":
                row = get_object_or_404(ExcelManualRow, id=request.POST.get("id"), section__in=allowed)
                row.title = (request.POST.get("title") or row.title).strip()
                row.amount = _int(request.POST.get("amount"))
                row.note = (request.POST.get("note") or "").strip()
                row.save()
            elif action == "add_row":
                section = request.POST.get("section")
                if section not in allowed:
                    raise ValueError("این بخش ورود دستی ندارد.")
                order = ExcelManualRow.objects.filter(section=section).aggregate(v=Sum("sort_order"))["v"] or 0
                ExcelManualRow.objects.create(section=section, title=(request.POST.get("title") or "ردیف جدید").strip(), sort_order=order + 1)
            else:
                ExcelManualRow.objects.filter(id=request.POST.get("id"), section__in=allowed).delete()

        elif action == "fabric_add":
            key = request.POST.get("material_key") or ""
            title = title_for_material_key(key)
            location = request.POST.get("location") or RawMaterialStock.WAREHOUSE
            add_warehouse_stock(
                kind=RawMaterialStock.FABRIC, material_key=key, title=title,
                quantity=request.POST.get("quantity"), unit_price=_int(request.POST.get("unit_price")),
                unit="کیلو", note=(request.POST.get("note") or "").strip(), location=location,
            )
        elif action == "fabric_transfer":
            transfer_fabric_to_tailor(request.POST.get("source_id"), request.POST.get("quantity"))
        elif action == "fabric_update":
            update_fabric_stock(
                request.POST.get("id"), quantity=request.POST.get("quantity"),
                unit_price=_int(request.POST.get("unit_price")), note=(request.POST.get("note") or "").strip(),
            )
        elif action == "fabric_delete":
            delete_fabric_stock(request.POST.get("id"))

        elif action == "elastic_add":
            key = request.POST.get("material_key") or ""
            title = title_for_material_key(key)
            if not key:
                raise ValueError("رنگ کش را انتخاب کن.")
            q16 = _decimal(request.POST.get("qty16")); q25 = _decimal(request.POST.get("qty25"))
            if q16 > 0:
                add_warehouse_stock(kind=RawMaterialStock.ELASTIC, material_key=key, title=title, quantity=q16, unit_price=_int(request.POST.get("price16")), variant="16", unit="کیلو")
            if q25 > 0:
                add_warehouse_stock(kind=RawMaterialStock.ELASTIC, material_key=key, title=title, quantity=q25, unit_price=_int(request.POST.get("price25")), variant="25", unit="کیلو")
            if q16 <= 0 and q25 <= 0:
                raise ValueError("مقدار کش 16 یا 25 را وارد کن.")
        elif action == "elastic_transfer":
            key = request.POST.get("material_key") or ""
            if not key:
                raise ValueError("رنگ کش را انتخاب کن.")
            transfer_elastic_to_tailor(key, title_for_material_key(key), request.POST.get("qty16"), request.POST.get("qty25"))
        elif action == "elastic_update":
            key = request.POST.get("material_key") or ""
            update_elastic_group(
                location=request.POST.get("location"), material_key=key, title=title_for_material_key(key),
                qty16=request.POST.get("qty16"), price16=_int(request.POST.get("price16")),
                qty25=request.POST.get("qty25"), price25=_int(request.POST.get("price25")),
            )
        elif action == "elastic_delete":
            key = request.POST.get("material_key") or ""
            delete_elastic_group(location=request.POST.get("location"), material_key=key, title=title_for_material_key(key))
        else:
            raise ValueError("عملیات نامعتبر است.")
        messages.success(request, "ذخیره شد.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("report")
