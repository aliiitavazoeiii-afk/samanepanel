from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .dateutils import format_jalali, parse_jalali_date
from .excel_views import OUTPUT_MODELS, OUTPUT_SIZES, RAW_COLORS, RAW_FIELDS, _blank_input_data, _blank_output_data, _material_block_view, _today_jalali
from .material_receipt_sync import reverse_report_consumption, sync_report_consumption
from .models import AppSetting, Brand, Color, InventoryModelCost, MaterialReportBlock, Size, StockBalance, StockLocation

DEFAULT_DOZEN_WAGE = 110000


def _norm(value):
    return (value or "").replace("ي", "ی").replace("ك", "ک").replace("‌", "").replace(" ", "").strip().lower()


def _int(value):
    try:
        return int(float(str(value or 0).replace("٬", "").replace(",", "").strip()))
    except Exception:
        return 0


def _dozen_wage():
    obj, _ = AppSetting.objects.get_or_create(key="pedram_dozen_wage", defaults={"value": str(DEFAULT_DOZEN_WAGE), "label": "مزد هر جین پدرام"})
    return max(0, _int(obj.value) or DEFAULT_DOZEN_WAGE)


def _wage_for_pieces(pieces, dozen_wage):
    pieces = max(0, _int(pieces))
    return int((Decimal(pieces) * Decimal(dozen_wage) / Decimal(12)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _output_total(output_data):
    total = 0
    for model_key, _ in OUTPUT_MODELS:
        values = (output_data or {}).get(model_key, {}) or {}
        for size_key, _ in OUTPUT_SIZES:
            total += max(0, _int(values.get(size_key)))
    return total


def _find_color(label):
    target = _norm(label)
    for color in Color.objects.filter(active=True):
        if _norm(color.name) == target:
            return color
    return Color.objects.create(name=label, active=True)


def _sync_finished_stock(old_output, new_output):
    """Sync finished production into the Darma warehouse (Khorshid), never Home."""
    brand = Brand.objects.get(name="دارما")
    warehouse = StockLocation.objects.get(key=StockLocation.KHORSHID)
    for model_key, label in OUTPUT_MODELS:
        color = _find_color(label)
        old_values = (old_output or {}).get(model_key, {}) or {}
        new_values = (new_output or {}).get(model_key, {}) or {}
        for size_key, size_name in OUTPUT_SIZES:
            old_qty = max(0, _int(old_values.get(size_key)))
            new_qty = max(0, _int(new_values.get(size_key)))
            delta = new_qty - old_qty
            if not delta:
                continue
            size = Size.objects.get(name=size_name)
            stock, _ = StockBalance.objects.get_or_create(
                brand=brand, color=color, size=size, location=warehouse, defaults={"qty": 0}
            )
            stock.qty = int(stock.qty or 0) + delta
            stock.save(update_fields=["qty"])
            InventoryModelCost.objects.get_or_create(
                brand=brand, color=color, size=size, defaults={"unit_cost": 61000}
            )


def _parse_input(request, dozen_wage):
    data = {}
    for color_key, _ in RAW_COLORS:
        data[color_key] = {}
        for field_key, _, _ in RAW_FIELDS:
            data[color_key][field_key] = (request.POST.get(f"in_{color_key}_{field_key}") or "").strip()
        cut = max(0, _int(data[color_key].get("cut")))
        data[color_key]["wage"] = str(_wage_for_pieces(cut, dozen_wage)) if cut else ""
    return data


def _parse_output(request):
    data = {}
    for model_key, _ in OUTPUT_MODELS:
        data[model_key] = {}
        for size_key, _ in OUTPUT_SIZES:
            data[model_key][size_key] = (request.POST.get(f"out_{model_key}_{size_key}") or "").strip()
        data[model_key]["delivery_date"] = (request.POST.get(f"delivery_{model_key}") or "").strip()
    return data


@login_required
def material_report(request):
    if request.method == "POST":
        try:
            block = MaterialReportBlock.objects.create(
                date=parse_jalali_date(request.POST.get("date") or _today_jalali()),
                title=(request.POST.get("title") or "").strip(), input_data=_blank_input_data(), output_data=_blank_output_data(),
            )
            messages.success(request, "صورت جدید مواد اولیه ساخته شد.")
            return redirect(f"/material-report/#block-{block.id}")
        except Exception as exc:
            messages.error(request, str(exc)); return redirect("material_report")
    blocks = [_material_block_view(obj) for obj in MaterialReportBlock.objects.all()[:40]]
    return render(request, "core/material_report.html", {
        "blocks": blocks, "raw_colors": RAW_COLORS, "output_sizes": OUTPUT_SIZES,
        "today_j": _today_jalali(), "sewing_wage_rate": _dozen_wage(),
    })


@login_required
@require_POST
def material_block_save(request, block_id):
    block = get_object_or_404(MaterialReportBlock, id=block_id)
    try:
        with transaction.atomic():
            old_output = deepcopy(block.output_data or {})
            dozen_wage = _dozen_wage()
            block.date = parse_jalali_date(request.POST.get("date") or format_jalali(block.date))
            block.title = (request.POST.get("title") or "").strip()
            block.note = (request.POST.get("note") or "").strip()
            block.input_data = _parse_input(request, dozen_wage)
            block.output_data = _parse_output(request)
            block.delivery_wage = _wage_for_pieces(_output_total(block.output_data), dozen_wage)
            _sync_finished_stock(old_output, block.output_data)
            block.save()
            sync_report_consumption(block)
        messages.success(
            request,
            "گزارش ذخیره شد؛ مزد جینی محاسبه و کالای تحویلی به موجودی انبار دارما اضافه شد.",
        )
    except Exception as exc:
        messages.error(request, f"ذخیره انجام نشد: {exc}")
    return redirect(f"/material-report/#block-{block.id}")


@login_required
@require_POST
def material_block_delete(request, block_id):
    block = get_object_or_404(MaterialReportBlock, id=block_id)
    try:
        with transaction.atomic():
            _sync_finished_stock(block.output_data or {}, {})
            reverse_report_consumption(block)
            block.delete()
        messages.success(request, "صورت حذف شد؛ موجودی کالای تحویلی و مصرف مواد هم معکوس شد.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("material_report")
