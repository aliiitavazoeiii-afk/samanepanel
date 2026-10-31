from collections import defaultdict
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render

from .dateutils import format_jalali
from .excel_views import (
    DISPLAY_SIZES, RAW_COLORS, _add_metrics, _empty_metrics, _finish_metrics, _period_range,
)
from .finance import sale_line_metrics
from .models import (
    BusinessPayment, ExcelManualRow, ExcelManualSetting, InventoryModelCost,
    RawMaterialStock, SaleLine, StockBalance,
)


COLOR_LABELS = dict(RAW_COLORS)


def _finished_inventory_value():
    cost_map = {
        (row.brand_id, row.color_id, row.size_id): int(row.unit_cost or 0)
        for row in InventoryModelCost.objects.all()
    }
    total = 0
    grouped = StockBalance.objects.values("brand_id", "color_id", "size_id").annotate(qty=Sum("qty"))
    for row in grouped:
        total += int(row["qty"] or 0) * cost_map.get(
            (row["brand_id"], row["color_id"], row["size_id"]), 0
        )
    return total


def _infer_material_key(row):
    if row.material_key:
        return row.material_key
    title = (row.title or "").replace("ي", "ی").replace("ك", "ک").replace(" ", "")
    for key, label in RAW_COLORS:
        if label.replace(" ", "") in title or label.replace("‌", "").replace(" ", "") in title:
            return key
    return ""


def _elastic_group(rows):
    grouped = {}
    for row in rows:
        key = _infer_material_key(row) or f"legacy-{row.id}"
        if key not in grouped:
            grouped[key] = {
                "key": key,
                "title": COLOR_LABELS.get(key, row.title),
                "q16": Decimal("0"), "q25": Decimal("0"),
                "p16": 0, "p25": 0,
                "v16": 0, "v25": 0,
            }
        cell = grouped[key]
        variant = row.variant or (
            "16" if "16" in (row.title or "") else "25" if "25" in (row.title or "") else ""
        )
        if variant == "16":
            cell["q16"] += Decimal(row.quantity or 0)
            cell["p16"] = int(row.unit_price or cell["p16"] or 0)
            cell["v16"] += row.total_value
        elif variant == "25":
            cell["q25"] += Decimal(row.quantity or 0)
            cell["p25"] = int(row.unit_price or cell["p25"] or 0)
            cell["v25"] += row.total_value
        else:
            cell["q16"] += Decimal(row.quantity or 0)
            cell["p16"] = int(row.unit_price or cell["p16"] or 0)
            cell["v16"] += row.total_value
    result = []
    for cell in grouped.values():
        cell["total"] = cell["v16"] + cell["v25"]
        result.append(cell)
    return sorted(result, key=lambda x: x["title"])


def _raw_material_context():
    rows = list(RawMaterialStock.objects.filter(active=True).order_by("kind", "location", "id"))
    fabric_warehouse = [r for r in rows if r.kind == RawMaterialStock.FABRIC and r.location == RawMaterialStock.WAREHOUSE]
    fabric_tailor = [r for r in rows if r.kind == RawMaterialStock.FABRIC and r.location == RawMaterialStock.TAILOR]
    fabric_depot = [r for r in rows if r.kind == RawMaterialStock.FABRIC and r.location == RawMaterialStock.DEPOT]
    elastic_warehouse_raw = [r for r in rows if r.kind == RawMaterialStock.ELASTIC and r.location == RawMaterialStock.WAREHOUSE]
    elastic_tailor_raw = [r for r in rows if r.kind == RawMaterialStock.ELASTIC and r.location == RawMaterialStock.TAILOR]

    fabric_warehouse_total = sum(r.total_value for r in fabric_warehouse)
    fabric_tailor_total = sum(r.total_value for r in fabric_tailor)
    fabric_depot_total = sum(r.total_value for r in fabric_depot)
    elastic_warehouse_total = sum(r.total_value for r in elastic_warehouse_raw)
    elastic_tailor_total = sum(r.total_value for r in elastic_tailor_raw)
    fabric_total = fabric_warehouse_total + fabric_tailor_total + fabric_depot_total
    elastic_total = elastic_warehouse_total + elastic_tailor_total

    return {
        "fabric_warehouse": fabric_warehouse,
        "fabric_tailor": fabric_tailor,
        "fabric_depot": fabric_depot,
        "elastic_warehouse": _elastic_group(elastic_warehouse_raw),
        "elastic_tailor": _elastic_group(elastic_tailor_raw),
        "fabric_warehouse_total": fabric_warehouse_total,
        "fabric_tailor_total": fabric_tailor_total,
        "fabric_depot_total": fabric_depot_total,
        "elastic_warehouse_total": elastic_warehouse_total,
        "elastic_tailor_total": elastic_tailor_total,
        "fabric_total": fabric_total,
        "elastic_total": elastic_total,
        "materials_total": fabric_total + elastic_total,
        "material_colors": RAW_COLORS,
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
        brands_view.append({
            "name": brand_name,
            "total": brand_totals[brand_name],
            "sizes": [(s, brand_sizes[brand_name][s]) for s in sizes],
        })

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

    # A real payment to the tailor moves cash into our receivable from the tailor.
    # The baseline itself stays in the manual "حساب اشخاص" row; only later payments are added here.
    tailor_payments = BusinessPayment.objects.filter(payee=BusinessPayment.TAILOR).aggregate(v=Sum("amount"))["v"] or 0
    accounts_total = (
        sum(row.amount for row in accounts_rows)
        + sum(row.amount for row in person_rows)
        + int(tailor_payments)
    )
    assets_total = sum(row.amount for row in asset_rows)
    finished_inventory_total = _finished_inventory_value()
    raw = _raw_material_context()
    inventory_total = finished_inventory_total + raw["materials_total"]
    capital_total = accounts_total + inventory_total + int(digikala_receivable) - int(takvin_debt) + assets_total

    context = {
        "period": period,
        "start": format_jalali(start),
        "end": format_jalali(end),
        "overall": overall,
        "brands": brands_view,
        "display_sizes": DISPLAY_SIZES,
        "product_rows": product_rows,
        "color_rows": color_rows,
        "accounts_rows": accounts_rows,
        "person_rows": person_rows,
        "asset_rows": asset_rows,
        "accounts_total": accounts_total,
        "assets_total": assets_total,
        "finished_inventory_total": finished_inventory_total,
        "inventory_total": inventory_total,
        "capital_total": capital_total,
        "takvin_debt": takvin_debt,
        "digikala_receivable": digikala_receivable,
    }
    context.update(raw)
    return render(request, "core/report_excel_v2.html", context)
