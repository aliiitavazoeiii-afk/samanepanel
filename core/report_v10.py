from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .capital_history_v87 import capital_as_of, current_capital_breakdown
from .dateutils import format_jalali
from .dia_gallery_v45 import dia_gallery_period_metrics
from .excel_views import DISPLAY_SIZES, _add_metrics, _empty_metrics, _finish_metrics, _int, _period_range
from .finance import sale_line_metrics
from .finance_overview_v104 import finance_kpis
from .finance_excel_v9 import digikala_ledger_total
from .models import ExcelManualRow, ExcelManualSetting, SaleLine
from .report_v5 import _raw_material_context, manual_report_action as legacy_manual_report_action
from .self_spend_v62 import is_self_tracking_row


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
        brands_view.append({
            "name": brand_name,
            "total": brand_totals[brand_name],
            "sizes": [(size, brand_sizes[brand_name][size]) for size in sizes],
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

    # Account/person management moved to /finance/accounts/ in V102.
    # Comprehensive Report keeps only asset rows plus read-only capital summaries.
    asset_rows = list(
        ExcelManualRow.objects.filter(active=True, section=ExcelManualRow.ASSETS)
        .order_by("sort_order", "id")
    )
    settings = {obj.key: obj for obj in ExcelManualSetting.objects.all()}
    digikala_base = int(settings.get("digikala_receivable").value or 0) if settings.get("digikala_receivable") else 0
    digikala_ledger = digikala_ledger_total()

    # V102: the current-capital number has exactly one canonical calculator.
    # This does not change the economic formula; it removes a duplicate copy from
    # report_v10 so Finance/report/history cannot silently drift apart later.
    current_capital = current_capital_breakdown()
    accounts_total = int(current_capital["accounts_total"])
    assets_total = int(current_capital["assets_total"])
    finished_inventory_total = int(current_capital["finished_inventory_total"])
    inventory_total = int(current_capital["inventory_total"])
    current_capital_total = int(current_capital["capital_total"])
    takvin_debt = int(current_capital["takvin_debt"])
    digikala_receivable = int(current_capital["digikala_receivable"])
    dia_gallery_receivable = int(current_capital["dia_gallery_receivable"])

    raw = _raw_material_context()
    historical_capital = capital_as_of(end)
    capital_total = int(historical_capital["capital_total"])

    context = {
        "period": period,
        "start": format_jalali(start),
        "end": format_jalali(end),
        "overall": overall,
        "brands": brands_view,
        "display_sizes": DISPLAY_SIZES,
        "product_rows": product_rows,
        "color_rows": color_rows,
        "asset_rows": asset_rows,
        "account_management_moved": True,
        "accounts_total": accounts_total,
        "assets_total": assets_total,
        "finished_inventory_total": finished_inventory_total,
        "inventory_total": inventory_total,
        "capital_total": capital_total,
        "current_capital_total": current_capital_total,
        "capital_is_historical": bool(historical_capital.get("is_historical")),
        "capital_history_source": historical_capital.get("source"),
        "capital_history_warnings": historical_capital.get("warnings") or [],
        "capital_post_period_delta": int(historical_capital.get("post_period_delta") or 0),
        "takvin_debt": takvin_debt,
        "digikala_receivable": digikala_receivable,
        "digikala_base_receivable": digikala_base,
        "digikala_ledger_total": digikala_ledger,
        "dia_gallery_receivable": dia_gallery_receivable,
        "dia_gallery": dia_gallery,
    }
    context.update(raw)
    context.update(finance_kpis())
    return render(request, "core/report_excel_v97.html", context)


@login_required
@require_POST
def manual_report_action(request):
    if request.POST.get("action") == "setting" and request.POST.get("key") == "digikala_receivable":
        try:
            desired_total = _int(request.POST.get("value"))
            ledger = digikala_ledger_total()
            base_value = desired_total - ledger
            obj, _ = ExcelManualSetting.objects.get_or_create(
                key="digikala_receivable",
                defaults={"label": "طلب پایه دیجی‌کالا", "value": 0},
            )
            obj.value = base_value
            obj.label = "طلب پایه دیجی‌کالا"
            obj.save(update_fields=["value", "label", "updated_at"])
            messages.success(request, "طلب دیجی‌کالا اصلاح شد؛ گردش خودکار فروش/دریافت حفظ شد.")
        except Exception as exc:
            messages.error(request, str(exc))
        return redirect("report")

    # The «خودم» tracking account is system-maintained from payment create/edit/delete.
    # Do not allow the generic manual-row controls to desynchronize it.
    if request.POST.get("action") in {"save_row", "delete_row"}:
        row = ExcelManualRow.objects.filter(id=request.POST.get("id")).first()
        if is_self_tracking_row(row):
            messages.error(
                request,
                "حساب «خودم» از پرداختی‌ها به‌صورت خودکار مدیریت می‌شود و از اینجا قابل ویرایش/حذف نیست.",
            )
            return redirect("report")

    return legacy_manual_report_action(request)
