from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import jdatetime
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Max, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .dateutils import format_jalali, parse_jalali_date
from .finance import sale_line_metrics
from .models import (
    Brand,
    ExcelManualRow,
    ExcelManualSetting,
    MaterialReportBlock,
    SaleDay,
    SaleLine,
)


RAW_COLORS = [
    ("black", "مشکی"),
    ("white", "سفید"),
    ("navy", "سرمه‌ای"),
    ("pink", "صورتی"),
    ("cream", "کرم"),
    ("red", "قرمز"),
    ("yellow", "زرد"),
    ("gray", "طوسی"),
    ("stripe", "راه راه"),
]

RAW_FIELDS = [
    ("fabric_code", "کد پارچه", "text"),
    ("weight", "وزن پارچه", "decimal"),
    ("elastic16", "کش تحویلی 16", "decimal"),
    ("elastic25", "کش تحویلی 25", "decimal"),
    ("cut", "برش پارچه", "number"),
    ("wage", "مزد دوخت", "money"),
    ("remain16", "کش مانده 16", "decimal"),
    ("remain25", "کش مانده 25", "decimal"),
    ("cost", "قیمت تمام شده", "money"),
]

OUTPUT_MODELS = [
    ("black", "مشکی"),
    ("white", "سفید"),
    ("navy", "سرمه‌ای"),
    ("pink", "صورتی"),
    ("cream", "کرم"),
    ("red", "قرمز"),
    ("yellow", "زرد"),
    ("gray", "طوسی"),
    ("stripe", "راه راه"),
    ("gray_stripe", "راه راه طوسی"),
    ("reverse_black", "برعکس مشکی"),
    ("reverse_white", "برعکس سفید"),
    ("reverse_navy", "برعکس سرمه‌ای"),
]

OUTPUT_SIZES = [
    ("m", "M"),
    ("l", "L"),
    ("xl", "XL"),
    ("xxl", "XXL"),
    ("3xl", "3XL"),
    ("4xl", "4XL"),
]

DISPLAY_SIZES = ["M", "L", "XL", "XXL", "3XL", "4XL"]


def _int(value, default=0):
    try:
        if value in (None, ""):
            return default
        return int(str(value).replace(" ", "").replace(",", "").replace("٬", "").strip())
    except (TypeError, ValueError):
        return default


def _decimal(value, default=Decimal("0")):
    try:
        if value in (None, ""):
            return default
        return Decimal(str(value).replace("٬", "").replace(",", ".").strip())
    except (InvalidOperation, TypeError, ValueError):
        return default


def _today_jalali():
    return format_jalali(date.today())


def _period_range(request):
    period = request.GET.get("period", "month")
    today = date.today()
    tj = jdatetime.date.fromgregorian(date=today)

    if period == "today":
        return period, today, today
    if period == "last_month":
        if tj.month == 1:
            y, m = tj.year - 1, 12
        else:
            y, m = tj.year, tj.month - 1
        start = jdatetime.date(y, m, 1).togregorian()
        end = jdatetime.date(tj.year, tj.month, 1).togregorian() - timedelta(days=1)
        return period, start, end
    if period == "custom":
        try:
            start = parse_jalali_date(request.GET.get("start", ""))
            end = parse_jalali_date(request.GET.get("end", ""))
            return period, min(start, end), max(start, end)
        except ValueError:
            period = "month"

    start = jdatetime.date(tj.year, tj.month, 1).togregorian()
    return period, start, today


def _empty_metrics():
    return {
        "gross": 0,
        "profit": 0,
        "shorts": 0,
        "digikala_fee": 0,
        "packs": 0,
        "cogs": 0,
        "margin": 0,
    }


def _add_metrics(target, source):
    for key in ["gross", "profit", "shorts", "digikala_fee", "packs", "cogs"]:
        target[key] += source[key]


def _finish_metrics(values):
    values["margin"] = values["profit"] * 100 / values["gross"] if values["gross"] else 0
    return values


@login_required
def dashboard(request):
    today = date.today()
    day = SaleDay.objects.filter(date=today).first()
    today_metrics = _empty_metrics()
    if day:
        for line in day.lines.filter(quantity__gt=0).select_related("product_size__product", "product_size__size"):
            _add_metrics(today_metrics, sale_line_metrics(line))
    _finish_metrics(today_metrics)

    tj = jdatetime.date.fromgregorian(date=today)
    month_start = jdatetime.date(tj.year, tj.month, 1).togregorian()
    month_metrics = _empty_metrics()
    for line in SaleLine.objects.filter(day__date__gte=month_start, day__date__lte=today, quantity__gt=0).select_related(
        "product_size__product", "product_size__size"
    ):
        _add_metrics(month_metrics, sale_line_metrics(line))
    _finish_metrics(month_metrics)

    return render(
        request,
        "core/dashboard_excel.html",
        {
            "today_metrics": today_metrics,
            "month_metrics": month_metrics,
            "today_j": _today_jalali(),
            "material_blocks": MaterialReportBlock.objects.count(),
        },
    )


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
        if brand_name == "تکوین":
            sizes = ["M", "L", "XL", "XXL"]
        else:
            sizes = DISPLAY_SIZES
        brands_view.append(
            {
                "name": brand_name,
                "total": brand_totals[brand_name],
                "sizes": [(size, brand_sizes[brand_name][size]) for size in sizes],
            }
        )

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

    rows = ExcelManualRow.objects.filter(active=True)
    sections = {
        key: list(rows.filter(section=key).order_by("sort_order", "id"))
        for key in [
            ExcelManualRow.ACCOUNTS,
            ExcelManualRow.PERSONS,
            ExcelManualRow.INVENTORY,
            ExcelManualRow.MATERIALS,
            ExcelManualRow.ASSETS,
        ]
    }
    settings = {obj.key: obj for obj in ExcelManualSetting.objects.all()}
    takvin_debt = settings.get("takvin_debt").value if settings.get("takvin_debt") else 0
    digikala_receivable = settings.get("digikala_receivable").value if settings.get("digikala_receivable") else 0

    accounts_total = sum(row.amount for row in sections[ExcelManualRow.ACCOUNTS]) + sum(
        row.amount for row in sections[ExcelManualRow.PERSONS]
    )
    materials_total = sum(row.amount for row in sections[ExcelManualRow.MATERIALS])
    inventory_finished_total = sum(row.amount for row in sections[ExcelManualRow.INVENTORY])
    inventory_total = inventory_finished_total + materials_total
    assets_total = sum(row.amount for row in sections[ExcelManualRow.ASSETS])
    capital_total = accounts_total + inventory_total + digikala_receivable - takvin_debt

    return render(
        request,
        "core/report_excel.html",
        {
            "period": period,
            "start": format_jalali(start),
            "end": format_jalali(end),
            "overall": overall,
            "brands": brands_view,
            "display_sizes": DISPLAY_SIZES,
            "product_rows": product_rows,
            "color_rows": color_rows,
            "sections": sections,
            "accounts_rows": sections[ExcelManualRow.ACCOUNTS],
            "person_rows": sections[ExcelManualRow.PERSONS],
            "inventory_rows": sections[ExcelManualRow.INVENTORY],
            "material_rows": sections[ExcelManualRow.MATERIALS],
            "asset_rows": sections[ExcelManualRow.ASSETS],
            "accounts_total": accounts_total,
            "materials_total": materials_total,
            "inventory_finished_total": inventory_finished_total,
            "inventory_total": inventory_total,
            "assets_total": assets_total,
            "takvin_debt": takvin_debt,
            "digikala_receivable": digikala_receivable,
            "capital_total": capital_total,
        },
    )


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
        elif action == "save_row":
            row = get_object_or_404(ExcelManualRow, id=request.POST.get("id"))
            row.title = (request.POST.get("title") or row.title).strip()
            row.amount = _int(request.POST.get("amount"))
            row.unit_price = _int(request.POST.get("unit_price"))
            row.quantity = _decimal(request.POST.get("quantity"))
            row.note = (request.POST.get("note") or "").strip()
            row.save()
        elif action == "add_row":
            section = request.POST.get("section")
            allowed = {choice[0] for choice in ExcelManualRow.SECTION_CHOICES}
            if section not in allowed:
                raise ValueError("بخش ناشناخته است.")
            title = (request.POST.get("title") or "ردیف جدید").strip()
            order = ExcelManualRow.objects.filter(section=section).aggregate(v=Max("sort_order"))["v"] or 0
            ExcelManualRow.objects.create(section=section, title=title, sort_order=order + 1)
        elif action == "delete_row":
            ExcelManualRow.objects.filter(id=request.POST.get("id")).delete()
        else:
            raise ValueError("عملیات نامعتبر است.")
        messages.success(request, "ذخیره شد.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("report")


def _blank_input_data():
    return {color_key: {field_key: "" for field_key, _, _ in RAW_FIELDS} for color_key, _ in RAW_COLORS}


def _blank_output_data():
    return {
        model_key: {**{size_key: "" for size_key, _ in OUTPUT_SIZES}, "delivery_date": ""}
        for model_key, _ in OUTPUT_MODELS
    }


def _safe_output_total(values):
    total = Decimal("0")
    for size_key, _ in OUTPUT_SIZES:
        total += _decimal(values.get(size_key, ""))
    return total


def _material_block_view(block):
    input_data = block.input_data or {}
    output_data = block.output_data or {}
    input_rows = []
    for field_key, label, input_type in RAW_FIELDS:
        cells = []
        for color_key, _ in RAW_COLORS:
            cells.append(
                {
                    "name": f"in_{color_key}_{field_key}",
                    "value": input_data.get(color_key, {}).get(field_key, ""),
                    "type": input_type,
                }
            )
        input_rows.append({"label": label, "cells": cells})

    output_rows = []
    for model_key, label in OUTPUT_MODELS:
        values = output_data.get(model_key, {})
        cells = [
            {"name": f"out_{model_key}_{size_key}", "value": values.get(size_key, "")}
            for size_key, _ in OUTPUT_SIZES
        ]
        output_rows.append(
            {
                "label": label,
                "cells": cells,
                "total": _safe_output_total(values),
                "delivery_name": f"delivery_{model_key}",
                "delivery_date": values.get("delivery_date", ""),
            }
        )
    return {
        "obj": block,
        "jalali_date": format_jalali(block.date),
        "input_rows": input_rows,
        "output_rows": output_rows,
    }


@login_required
def material_report(request):
    if request.method == "POST":
        try:
            block = MaterialReportBlock.objects.create(
                date=parse_jalali_date(request.POST.get("date") or _today_jalali()),
                title=(request.POST.get("title") or "").strip(),
                input_data=_blank_input_data(),
                output_data=_blank_output_data(),
            )
            messages.success(request, "صورت جدید مواد اولیه ساخته شد.")
            return redirect(f"/material-report/#block-{block.id}")
        except Exception as exc:
            messages.error(request, str(exc))
            return redirect("material_report")

    blocks = [_material_block_view(obj) for obj in MaterialReportBlock.objects.all()[:40]]
    return render(
        request,
        "core/material_report.html",
        {
            "blocks": blocks,
            "raw_colors": RAW_COLORS,
            "output_sizes": OUTPUT_SIZES,
            "today_j": _today_jalali(),
        },
    )


@login_required
@require_POST
def material_block_save(request, block_id):
    block = get_object_or_404(MaterialReportBlock, id=block_id)
    try:
        block.date = parse_jalali_date(request.POST.get("date") or format_jalali(block.date))
        block.title = (request.POST.get("title") or "").strip()
        block.delivery_wage = _int(request.POST.get("delivery_wage"))
        block.note = (request.POST.get("note") or "").strip()

        input_data = {}
        for color_key, _ in RAW_COLORS:
            input_data[color_key] = {}
            for field_key, _, _ in RAW_FIELDS:
                input_data[color_key][field_key] = (request.POST.get(f"in_{color_key}_{field_key}") or "").strip()

        output_data = {}
        for model_key, _ in OUTPUT_MODELS:
            output_data[model_key] = {}
            for size_key, _ in OUTPUT_SIZES:
                output_data[model_key][size_key] = (request.POST.get(f"out_{model_key}_{size_key}") or "").strip()
            output_data[model_key]["delivery_date"] = (request.POST.get(f"delivery_{model_key}") or "").strip()

        block.input_data = input_data
        block.output_data = output_data
        block.save()
        messages.success(request, "گزارش مواد اولیه ذخیره شد.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect(f"/material-report/#block-{block.id}")


@login_required
@require_POST
def material_block_delete(request, block_id):
    block = get_object_or_404(MaterialReportBlock, id=block_id)
    block.delete()
    messages.success(request, "صورت مواد اولیه حذف شد.")
    return redirect("material_report")
