from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .dateutils import format_jalali, parse_jalali_date
from .excel_views import (
    OUTPUT_MODELS,
    OUTPUT_SIZES,
    RAW_COLORS,
    RAW_FIELDS,
    _blank_input_data,
    _blank_output_data,
    _material_block_view,
    _today_jalali,
)
from .material_cost_v13 import apply_costs_to_input_data
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
    obj, _ = AppSetting.objects.get_or_create(
        key="pedram_dozen_wage",
        defaults={"value": str(DEFAULT_DOZEN_WAGE), "label": "مزد هر جین پدرام"},
    )
    return max(0, _int(obj.value) or DEFAULT_DOZEN_WAGE)


def _wage_for_pieces(pieces, dozen_wage):
    pieces = max(0, _int(pieces))
    return int(
        (Decimal(pieces) * Decimal(dozen_wage) / Decimal(12)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def _output_total(output_data):
    total = 0
    for model_key, _ in OUTPUT_MODELS:
        values = (output_data or {}).get(model_key, {}) or {}
        for size_key, _ in OUTPUT_SIZES:
            total += max(0, _int(values.get(size_key)))
    return total


def _color_output_total(output_data, color_key):
    values = (output_data or {}).get(color_key, {}) or {}
    return sum(max(0, _int(values.get(size_key))) for size_key, _ in OUTPUT_SIZES)


def _find_color(label):
    target = _norm(label)
    for color in Color.objects.filter(active=True):
        if _norm(color.name) == target:
            return color
    return Color.objects.create(name=label, active=True)


def _sync_finished_stock(old_output, new_output):
    """Finished production goes to Darma warehouse (Khorshid), never Home."""
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
            # cost and wage are server-calculated; ignore forged browser values.
            if field_key in {"cost", "wage"}:
                continue
            data[color_key][field_key] = (request.POST.get(f"in_{color_key}_{field_key}") or "").strip()
        cut = max(0, _int(data[color_key].get("cut")))
        data[color_key]["wage"] = str(_wage_for_pieces(cut, dozen_wage)) if cut else ""
        data[color_key]["cost"] = ""
    data, _ = apply_costs_to_input_data(data)
    return data


def _parse_output(request):
    data = {}
    for model_key, _ in OUTPUT_MODELS:
        data[model_key] = {}
        for size_key, _ in OUTPUT_SIZES:
            data[model_key][size_key] = (request.POST.get(f"out_{model_key}_{size_key}") or "").strip()
        data[model_key]["delivery_date"] = (request.POST.get(f"delivery_{model_key}") or "").strip()
    return data


def _validate_ready_to_apply(block):
    if _output_total(block.output_data) <= 0:
        raise ValueError("برای اعمال موجودی خیاط، ابتدا تعداد کالای تحویلی را در سایزها ثبت کن.")
    missing = []
    labels = dict(RAW_COLORS)
    for color_key, _ in RAW_COLORS:
        cut = max(0, _int((block.input_data or {}).get(color_key, {}).get("cut")))
        if cut > 0 and _color_output_total(block.output_data, color_key) <= 0:
            missing.append(labels[color_key])
    if missing:
        raise ValueError(
            "برای این رنگ‌ها برش ثبت شده ولی هنوز محصول تحویلی ثبت نشده: " + "، ".join(missing)
        )


def _save_from_request(block, request):
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
    return block


def _view_block(obj):
    row = _material_block_view(obj)
    row["materials_applied"] = obj.stock_consumptions.exists()
    row["consumption_count"] = obj.stock_consumptions.count()
    return row


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

    blocks = [_view_block(obj) for obj in MaterialReportBlock.objects.all()[:40]]
    return render(
        request,
        "core/material_report.html",
        {
            "blocks": blocks,
            "raw_colors": RAW_COLORS,
            "output_sizes": OUTPUT_SIZES,
            "today_j": _today_jalali(),
            "sewing_wage_rate": _dozen_wage(),
        },
    )


@login_required
@require_POST
def material_block_save(request, block_id):
    block = get_object_or_404(MaterialReportBlock, id=block_id)
    try:
        with transaction.atomic():
            _save_from_request(block, request)
        if block.stock_consumptions.exists():
            messages.success(
                request,
                "صورت ذخیره شد؛ موجودی خیاط تغییر نکرد. این صورت قبلاً اعمال شده است؛ برای اعمال اصلاحات دوباره دکمه «اعمال بر موجودی خیاط» را بزن.",
            )
        else:
            messages.success(
                request,
                "صورت ذخیره شد؛ هیچ پارچه یا کشی از موجودی نزد خیاط کم نشد.",
            )
    except Exception as exc:
        messages.error(request, f"ذخیره انجام نشد: {exc}")
    return redirect(f"/material-report/#block-{block.id}")


@login_required
@require_POST
def material_block_apply(request, block_id):
    block = get_object_or_404(MaterialReportBlock, id=block_id)
    try:
        with transaction.atomic():
            _save_from_request(block, request)
            _validate_ready_to_apply(block)
            sync_report_consumption(block)
        messages.success(
            request,
            "صورت ذخیره و بر موجودی خیاط اعمال شد؛ فقط اختلاف نسبت به اعمال قبلی کم/برگشت داده شد.",
        )
    except Exception as exc:
        messages.error(request, f"اعمال موجودی انجام نشد و همه تغییرات این عملیات برگشت: {exc}")
    return redirect(f"/material-report/#block-{block.id}")


@login_required
@require_POST
def material_block_unapply(request, block_id):
    block = get_object_or_404(MaterialReportBlock, id=block_id)
    try:
        with transaction.atomic():
            reverse_report_consumption(block)
        messages.success(request, "اثر این صورت از موجودی خیاط برگشت؛ اطلاعات خود صورت باقی ماند.")
    except Exception as exc:
        messages.error(request, f"برگرداندن اثر موجودی انجام نشد: {exc}")
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
        messages.success(request, "صورت حذف شد؛ اثر موجودی کالای تحویلی و هر مصرف اعمال‌شده نیز برگشت.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("material_report")
