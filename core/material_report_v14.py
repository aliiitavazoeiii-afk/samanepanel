from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum
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
from .models import (
    AppSetting,
    Brand,
    Color,
    ExcelManualRow,
    InventoryModelCost,
    MaterialReportBlock,
    Size,
    StockBalance,
    StockLocation,
)

DEFAULT_DOZEN_WAGE = 110000
APPLIED_MARKER_PREFIX = "material_v14_applied_"

# Output colors that share the raw-material cost of another input column.
COST_SOURCE = {
    "black": "black",
    "white": "white",
    "navy": "navy",
    "pink": "pink",
    "cream": "cream",
    "red": "red",
    "yellow": "yellow",
    "gray": "gray",
    "stripe": "stripe",
    "gray_stripe": "stripe",
    "reverse_black": "black",
    "reverse_white": "white",
    "reverse_navy": "navy",
}


def _norm(value):
    return (value or "").replace("ي", "ی").replace("ك", "ک").replace("‌", "").replace(" ", "").strip().lower()


def _int(value):
    try:
        return int(float(str(value or 0).replace("٬", "").replace(",", "").strip()))
    except Exception:
        return 0


def _round_money(value):
    return int(Decimal(value or 0).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _dozen_wage():
    obj, _ = AppSetting.objects.get_or_create(
        key="pedram_dozen_wage",
        defaults={"value": str(DEFAULT_DOZEN_WAGE), "label": "مزد هر جین پدرام"},
    )
    return max(0, _int(obj.value) or DEFAULT_DOZEN_WAGE)


def _wage_for_pieces(pieces, dozen_wage):
    pieces = max(0, _int(pieces))
    return _round_money(Decimal(pieces) * Decimal(dozen_wage) / Decimal(12))


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


def _parse_input(request, dozen_wage):
    data = {}
    for color_key, _ in RAW_COLORS:
        data[color_key] = {}
        for field_key, _, _ in RAW_FIELDS:
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


def _save_data_only(block, request):
    dozen_wage = _dozen_wage()
    block.date = parse_jalali_date(request.POST.get("date") or format_jalali(block.date))
    block.title = (request.POST.get("title") or "").strip()
    block.note = (request.POST.get("note") or "").strip()
    block.input_data = _parse_input(request, dozen_wage)
    block.output_data = _parse_output(request)
    block.delivery_wage = _wage_for_pieces(_output_total(block.output_data), dozen_wage)
    block.save()
    return block


def _validate_ready_to_apply(block):
    if _output_total(block.output_data) <= 0:
        raise ValueError("برای اعمال تولید، ابتدا تعداد کالای تحویلی را در سایزها ثبت کن.")
    missing = []
    labels = dict(RAW_COLORS)
    for color_key, _ in RAW_COLORS:
        cut = max(0, _int((block.input_data or {}).get(color_key, {}).get("cut")))
        if cut > 0 and _color_output_total(block.output_data, color_key) <= 0:
            missing.append(labels[color_key])
    if missing:
        raise ValueError("برای این رنگ‌ها برش ثبت شده ولی محصول تحویلی ثبت نشده: " + "، ".join(missing))


def _tailor_row(create=True):
    rows = ExcelManualRow.objects.filter(section=ExcelManualRow.PERSONS, active=True).order_by("sort_order", "id")
    for row in rows:
        if "خیاط" in (row.title or "").replace(" ", ""):
            return row
    if not create:
        return None
    return ExcelManualRow.objects.create(section=ExcelManualRow.PERSONS, title="خیاط", amount=0, sort_order=999)


def _adjust_tailor_balance(delta):
    row = _tailor_row(create=True)
    row.amount = int(row.amount or 0) + int(delta or 0)
    row.save(update_fields=["amount", "updated_at"])


def _marker_key(block_id):
    return f"{APPLIED_MARKER_PREFIX}{block_id}"


def _is_v14_applied(block):
    return AppSetting.objects.filter(key=_marker_key(block.id), value="1").exists()


def _set_v14_applied(block, enabled):
    key = _marker_key(block.id)
    if enabled:
        AppSetting.objects.update_or_create(key=key, defaults={"value": "1", "label": "Material v14 applied marker"})
    else:
        AppSetting.objects.filter(key=key).delete()


def _batch_unit_cost(input_data, model_key, current_cost):
    source = COST_SOURCE.get(model_key, model_key)
    value = _int(((input_data or {}).get(source, {}) or {}).get("cost"))
    return value if value > 0 else int(current_cost or 61000)


def _total_stock_qty(brand, color, size):
    return int(
        StockBalance.objects.filter(brand=brand, color=color, size=size).aggregate(v=Sum("qty"))["v"] or 0
    )


def _sync_finished_stock_costed(output_data, input_data, direction):
    """
    direction=+1 applies production into Khorshid and blends its actual calculated unit cost.
    direction=-1 reverses a v14 production batch. Reversal is allowed only while the produced
    quantity still exists in Khorshid, preventing removal of already-sold/transferred goods.
    """
    if direction not in {1, -1}:
        raise ValueError("جهت تغییر موجودی تولید معتبر نیست.")
    brand = Brand.objects.get(name="دارما")
    warehouse = StockLocation.objects.get(key=StockLocation.KHORSHID)

    for model_key, label in OUTPUT_MODELS:
        color = _find_color(label)
        values = (output_data or {}).get(model_key, {}) or {}
        for size_key, size_name in OUTPUT_SIZES:
            qty = max(0, _int(values.get(size_key)))
            if qty <= 0:
                continue
            size = Size.objects.get(name=size_name)
            stock, _ = StockBalance.objects.get_or_create(
                brand=brand, color=color, size=size, location=warehouse, defaults={"qty": 0}
            )
            stock = StockBalance.objects.select_for_update().get(pk=stock.pk)
            cost_row, _ = InventoryModelCost.objects.get_or_create(
                brand=brand, color=color, size=size, defaults={"unit_cost": 61000}
            )
            cost_row = InventoryModelCost.objects.select_for_update().get(pk=cost_row.pk)
            current_cost = int(cost_row.unit_cost or 61000)
            batch_cost = _batch_unit_cost(input_data, model_key, current_cost)
            total_before = _total_stock_qty(brand, color, size)

            if direction > 0:
                new_total = total_before + qty
                if new_total > 0:
                    new_cost = _round_money(
                        (Decimal(total_before) * Decimal(current_cost) + Decimal(qty) * Decimal(batch_cost))
                        / Decimal(new_total)
                    )
                    cost_row.unit_cost = max(0, new_cost)
                    cost_row.save(update_fields=["unit_cost", "updated_at"])
                stock.qty = int(stock.qty or 0) + qty
                stock.save(update_fields=["qty"])
            else:
                if int(stock.qty or 0) < qty:
                    raise ValueError(
                        f"برای برگرداندن تولید، موجودی {label} / {size_name} در خورشید کافی نیست. "
                        "اگر کالا را به خانه منتقل کرده‌ای اول همان تعداد را به خورشید برگردان."
                    )
                remaining_total = total_before - qty
                if remaining_total < 0:
                    raise ValueError(f"موجودی کل {label} / {size_name} از مقدار این صورت کمتر است.")
                if remaining_total > 0:
                    remaining_value = Decimal(total_before) * Decimal(current_cost) - Decimal(qty) * Decimal(batch_cost)
                    new_cost = _round_money(max(Decimal("0"), remaining_value) / Decimal(remaining_total))
                    cost_row.unit_cost = max(0, new_cost)
                    cost_row.save(update_fields=["unit_cost", "updated_at"])
                stock.qty = int(stock.qty or 0) - qty
                stock.save(update_fields=["qty"])


def _sync_finished_stock_legacy_remove(output_data):
    """Reverse only quantity for a pre-v14 block; legacy code never blended cost."""
    brand = Brand.objects.get(name="دارما")
    warehouse = StockLocation.objects.get(key=StockLocation.KHORSHID)
    for model_key, label in OUTPUT_MODELS:
        color = _find_color(label)
        values = (output_data or {}).get(model_key, {}) or {}
        for size_key, size_name in OUTPUT_SIZES:
            qty = max(0, _int(values.get(size_key)))
            if qty <= 0:
                continue
            size = Size.objects.get(name=size_name)
            stock, _ = StockBalance.objects.get_or_create(
                brand=brand, color=color, size=size, location=warehouse, defaults={"qty": 0}
            )
            stock = StockBalance.objects.select_for_update().get(pk=stock.pk)
            if int(stock.qty or 0) < qty:
                raise ValueError(
                    f"موجودی خورشید برای برگرداندن صورت قدیمی {label} / {size_name} کافی نیست."
                )
            stock.qty = int(stock.qty or 0) - qty
            stock.save(update_fields=["qty"])


def _view_block(obj):
    row = _material_block_view(obj)
    row["materials_applied"] = obj.stock_consumptions.exists()
    row["v14_applied"] = _is_v14_applied(obj)
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
        "core/material_report_v13.html",
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
        if block.stock_consumptions.exists():
            raise ValueError("این صورت روی موجودی اعمال شده است. برای ویرایش ابتدا «برگرداندن اثر موجودی خیاط» را بزن.")
        with transaction.atomic():
            _save_data_only(block, request)
        messages.success(request, "صورت ذخیره شد؛ هیچ موجودی و هیچ بخش سرمایه تغییر نکرد.")
    except Exception as exc:
        messages.error(request, f"ذخیره انجام نشد: {exc}")
    return redirect(f"/material-report/#block-{block.id}")


@login_required
@require_POST
def material_block_apply(request, block_id):
    block = get_object_or_404(MaterialReportBlock, id=block_id)
    try:
        if block.stock_consumptions.exists():
            raise ValueError("این صورت قبلاً اعمال شده است؛ برای تغییر ابتدا اثر آن را برگردان.")
        with transaction.atomic():
            _save_data_only(block, request)
            _validate_ready_to_apply(block)
            # Internal conversion is atomic: consume raw materials, add finished goods,
            # and consume the tailor advance/labor balance in one transaction.
            sync_report_consumption(block)
            _sync_finished_stock_costed(block.output_data or {}, block.input_data or {}, +1)
            _adjust_tailor_balance(-int(block.delivery_wage or 0))
            _set_v14_applied(block, True)
        messages.success(
            request,
            "صورت اعمال شد: مواد نزد خیاط کم، کالای آماده به خورشید اضافه و مزد از حساب خیاط تسویه شد.",
        )
    except Exception as exc:
        messages.error(request, f"اعمال انجام نشد و کل عملیات برگشت: {exc}")
    return redirect(f"/material-report/#block-{block.id}")


@login_required
@require_POST
def material_block_unapply(request, block_id):
    block = get_object_or_404(MaterialReportBlock, id=block_id)
    try:
        if not block.stock_consumptions.exists():
            raise ValueError("این صورت روی موجودی خیاط اعمال نشده است.")
        with transaction.atomic():
            if _is_v14_applied(block):
                _sync_finished_stock_costed(block.output_data or {}, block.input_data or {}, -1)
                _adjust_tailor_balance(int(block.delivery_wage or 0))
            else:
                # Legacy v5/v13 applied blocks added finished stock but did not touch tailor balance/cost average.
                _sync_finished_stock_legacy_remove(block.output_data or {})
            reverse_report_consumption(block)
            _set_v14_applied(block, False)
        messages.success(
            request,
            "اثر صورت کامل برگشت: هم مواد اولیه و هم کالای آماده به وضعیت قبل برگشتند.",
        )
    except Exception as exc:
        messages.error(request, f"برگرداندن اثر انجام نشد: {exc}")
    return redirect(f"/material-report/#block-{block.id}")


@login_required
@require_POST
def material_block_delete(request, block_id):
    block = get_object_or_404(MaterialReportBlock, id=block_id)
    try:
        with transaction.atomic():
            if block.stock_consumptions.exists():
                if _is_v14_applied(block):
                    _sync_finished_stock_costed(block.output_data or {}, block.input_data or {}, -1)
                    _adjust_tailor_balance(int(block.delivery_wage or 0))
                else:
                    _sync_finished_stock_legacy_remove(block.output_data or {})
                reverse_report_consumption(block)
            _set_v14_applied(block, False)
            block.delete()
        messages.success(request, "صورت حذف شد و هر اثر اعمال‌شده آن نیز به‌صورت دوطرفه برگشت.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("material_report")
