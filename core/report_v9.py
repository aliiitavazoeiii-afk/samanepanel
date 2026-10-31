from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .dateutils import format_jalali
from .dia_gallery_v45 import dia_gallery_period_metrics, dia_gallery_receivable_total
from .excel_views import DISPLAY_SIZES, _add_metrics, _empty_metrics, _finish_metrics, _int, _period_range
from .finance import sale_line_metrics
from .finance_excel_v9 import digikala_ledger_total, digikala_receivable_total
from .inventory_valuation_v17 import finished_inventory_value_v17
from .models import ExcelManualRow, ExcelManualSetting, SaleLine
from .report_v5 import _raw_material_context, manual_report_action as legacy_manual_report_action


@login_required
def report(request):
    period, start, end = _period_range(request)
    lines = list(
        SaleLine.objects.filter(day__date__gte=start, day__date__lte=end, quantity__gt=0)
        .select_related("day", "product_size__product__brand", "product_size__product", "product_size__size")
        .prefetch_related("product_size__product__composition__color", "allocations__color")
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
            allocations = list(line.allocations.all())
            if allocations:
                for alloc in allocations:
                    color_sales[alloc.color.name][size] += int(alloc.qty)
            else:
                for comp in line.product_size.product.composition.all():
                    color_sales[comp.color.name][size] += int(line.quantity) * int(comp.qty)

    dia_gallery = dia_gallery_period_metrics(start, end)
    if int(dia_gallery["total"].get("shorts") or 0) > 0:
        _add_metrics(brand_totals["Dia Gallery"], dia_gallery["total"])
        _add_metrics(overall, dia_gallery["total"])
        for size_name, metrics in dia_gallery["by_size"].items():
            _add_metrics(brand_sizes["Dia Gallery"][size_name], metrics)
        for color_name, sizes in dia_gallery["color_sizes"].items():
            for size_name, qty in sizes.items():
                color_sales[color_name][size_name] += int(qty or 0)

    for values in brand_totals.values():
        _finish_metrics(values)
    for size_map in brand_sizes.values():
        for values in size_map.values():
            _finish_metrics(values)
    _finish_metrics(overall)

    brands_view = []
    for brand_name in ["تکوین", "دارما", "انبارش", "Dia Gallery"]:
        sizes = ["M", "L", "XL", "XXL"] if brand_name == "تکوین" else DISPLAY_SIZES
        brands_view.append({"name": brand_name, "total": brand_totals[brand_name], "sizes": [(size, brand_sizes[brand_name][size]) for size in sizes]})

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
    takvin_debt = int(settings.get("takvin_debt").value or 0) if settings.get("takvin_debt") else 0
    digikala_base = int(settings.get("digikala_receivable").value or 0) if settings.get("digikala_receivable") else 0
    digikala_ledger = digikala_ledger_total()
    digikala_receivable = digikala_receivable_total()
    dia_gallery_receivable = dia_gallery_receivable_total()

    accounts_total = sum(row.amount for row in accounts_rows) + sum(row.amount for row in person_rows) + dia_gallery_receivable
    assets_total = sum(row.amount for row in asset_rows)
    finished_inventory_total = finished_inventory_value_v17()
    raw = _raw_material_context()
    inventory_total = finished_inventory_total + raw["materials_total"]
    capital_total = accounts_total + inventory_total + digikala_receivable - takvin_debt + assets_total

    context = {
        "period": period, "start": format_jalali(start), "end": format_jalali(end), "overall": overall,
        "brands": brands_view, "display_sizes": DISPLAY_SIZES, "product_rows": product_rows, "color_rows": color_rows,
        "accounts_rows": accounts_rows, "person_rows": person_rows, "asset_rows": asset_rows,
        "accounts_total": accounts_total, "assets_total": assets_total, "finished_inventory_total": finished_inventory_total,
        "inventory_total": inventory_total, "capital_total": capital_total, "takvin_debt": takvin_debt,
        "digikala_receivable": digikala_receivable, "digikala_base_receivable": digikala_base,
        "digikala_ledger_total": digikala_ledger,
        "dia_gallery_receivable": dia_gallery_receivable,
        "dia_gallery": dia_gallery,
    }
    context.update(raw)
    return render(request, "core/report_excel_v45.html", context)


@login_required
@require_POST
def manual_report_action(request):
    if request.POST.get("action") == "setting" and request.POST.get("key") == "digikala_receivable":
        try:
            desired_total = _int(request.POST.get("value"))
            ledger = digikala_ledger_total()
            base_value = desired_total - ledger
            obj, _ = ExcelManualSetting.objects.get_or_create(key="digikala_receivable", defaults={"label": "طلب پایه دیجی‌کالا", "value": 0})
            obj.value = base_value
            obj.label = "طلب پایه دیجی‌کالا"
            obj.save(update_fields=["value", "label", "updated_at"])
            messages.success(request, "طلب دیجی‌کالا اصلاح شد؛ گردش خودکار فروش/دریافت حفظ شد.")
        except Exception as exc:
            messages.error(request, str(exc))
        return redirect("report")
    return legacy_manual_report_action(request)
