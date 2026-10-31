from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from . import material_report_v20 as v20
from .dateutils import parse_jalali_date
from .models import AppSetting, InventoryMovement, MaterialReportBlock, MaterialReportOutputApplied, StockBalance

CUT_SOURCE = {
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
    # Reverse models do not inherit the base-color cut. They have no raw cut row,
    # so their cut comparator must stay zero unless a dedicated cut source is added later.
    "reverse_black": "reverse_black",
    "reverse_white": "reverse_white",
    "reverse_navy": "reverse_navy",
}
NOVANI_WAGE_LEDGER_PREFIX = "novani_output_wage_pieces_v35_"
DARMA_WAGE_LEDGER_PREFIX = "darma_output_wage_pieces_v35_"
V34_REPAIR_PREFIX = "novani_wage_repair_v34_block_"


def _validate_output_editable(block):
    """Both Darma and Novani may edit cumulative delivered quantities in either direction."""
    allowed = {key for key, _label in v20._output_sizes_for_block(block)}
    for applied in block.output_applications.all():
        if int(applied.quantity or 0) <= 0:
            continue
        if applied.size_key not in allowed:
            raise ValueError(
                f"این صورت یک تحویل قدیمی در سایز {applied.size_key} دارد که با سایزبندی فعلی "
                f"{block.brand.name} سازگار نیست؛ برای حفظ موجودی تغییر خودکار انجام نشد."
            )


def _cut_for_model(block, model_key):
    source = CUT_SOURCE.get(model_key, model_key)
    values = (block.input_data or {}).get(source, {}) or {}
    return max(0, v20._int(values.get("cut")))


def _view_block_v35(obj):
    row = v20._view_block(obj)
    reduction_total = 0
    sync_abs_total = 0
    for (model_key, _label), output_row in zip(v20.OUTPUT_MODELS, row["output_rows"]):
        cut_source = CUT_SOURCE.get(model_key, model_key)
        cut_total = _cut_for_model(obj, model_key)
        delivered = int(output_row.get("total") or 0)
        applied = int(output_row.get("applied_total") or 0)
        cut_diff = delivered - cut_total
        sync_delta = delivered - applied
        output_row["model_key"] = model_key
        output_row["cut_source"] = cut_source
        output_row["cut_total"] = cut_total
        output_row["cut_diff"] = cut_diff
        output_row["cut_diff_abs"] = abs(cut_diff)
        output_row["sync_delta"] = sync_delta
        output_row["reduction_total"] = max(0, -sync_delta)
        output_row["pending_total"] = max(0, sync_delta)
        reduction_total += max(0, -sync_delta)
        sync_abs_total += abs(sync_delta)
    row["output_reduction"] = reduction_total
    row["output_sync_abs"] = sync_abs_total
    return row


@login_required
def material_report(request):
    brands = v20._material_brands()
    if request.method == "POST":
        try:
            brand = v20._selected_brand(request)
            block = MaterialReportBlock.objects.create(
                date=parse_jalali_date(request.POST.get("date") or v20._today_jalali()),
                title=(request.POST.get("title") or "").strip(),
                brand=brand,
                input_data=v20._blank_input_data(),
                output_data=v20._blank_output_data_for_brand(brand),
            )
            messages.success(request, f"صورت جدید برای {brand.name} ساخته شد؛ هنوز هیچ اثری روی موجودی ندارد.")
            return redirect(f"/material-report/#block-{block.id}")
        except Exception as exc:
            messages.error(request, str(exc))
            return redirect("material_report")

    blocks = [
        _view_block_v35(obj)
        for obj in MaterialReportBlock.objects.select_related("brand").prefetch_related(
            "output_applications", "stock_consumptions"
        ).all()[:40]
    ]
    return render(
        request,
        "core/material_report_v35.html",
        {
            "blocks": blocks,
            "brands": brands,
            "raw_colors": v20.RAW_COLORS,
            "today_j": v20._today_jalali(),
            "sewing_wage_rate": v20._dozen_wage(),
        },
    )


@login_required
@require_POST
def material_block_save(request, block_id):
    try:
        with transaction.atomic():
            block = MaterialReportBlock.objects.select_for_update().select_related("brand").get(id=block_id)
            v20._save_block_data(block, request)
            _validate_output_editable(block)
        messages.success(
            request,
            "صورت ذخیره شد. اگر عدد تحویلیِ اعمال‌شده را کم یا پاک کرده‌ای، برای اصلاح موجودی و مزد "
            "«همگام‌سازی تحویل و موجودی» را بزن.",
        )
    except MaterialReportBlock.DoesNotExist:
        messages.error(request, "صورت پیدا نشد.")
    except Exception as exc:
        messages.error(request, f"ذخیره انجام نشد: {exc}")
    return redirect(f"/material-report/#block-{block_id}")


@login_required
@require_POST
def material_block_apply_materials(request, block_id):
    try:
        with transaction.atomic():
            block = MaterialReportBlock.objects.select_for_update().select_related("brand").get(id=block_id)
            v20._save_block_data(block, request)
            _validate_output_editable(block)
            before = block.stock_consumptions.aggregate(v=Sum("quantity"))["v"] or 0
            v20.sync_report_consumption(block)
            after = block.stock_consumptions.aggregate(v=Sum("quantity"))["v"] or 0
        messages.success(
            request,
            f"مواد اولیه صورت {block.brand.name} اعمال/همگام شد. این عملیات هیچ شورت آماده‌ای تغییر نداد. "
            f"مصرف ثبت‌شده: {after} (قبل: {before}).",
        )
    except MaterialReportBlock.DoesNotExist:
        messages.error(request, "صورت پیدا نشد.")
    except Exception as exc:
        messages.error(request, f"اعمال مواد انجام نشد و کل عملیات برگشت: {exc}")
    return redirect(f"/material-report/#block-{block_id}")


def _wage_ledger_key(block):
    if block.brand.name == "Novani":
        return f"{NOVANI_WAGE_LEDGER_PREFIX}{block.id}"
    if block.brand.name == "دارما":
        return f"{DARMA_WAGE_LEDGER_PREFIX}{block.id}"
    raise ValueError("برند صورت مواد معتبر نیست.")


def _lock_or_initialize_wage_ledger(block, applied_total_before):
    """
    Track the cumulative delivered-piece basis used for wage delta calculations.

    Darma historically deducted wage on Apply Output, so an existing Darma block can seed
    its ledger from the already-applied quantity. Novani had the v33 missing-wage bug, so
    a legacy positive Novani block may seed only when its V34 repair marker exists.
    """
    key = _wage_ledger_key(block)
    ledger = AppSetting.objects.select_for_update().filter(key=key).first()
    if ledger:
        ledger_pieces = max(0, v20._int(ledger.value))
        if ledger_pieces != applied_total_before:
            raise ValueError(
                f"دفتر مزد {block.brand.name} با تحویل اعمال‌شده همخوان نیست: "
                f"مزد={ledger_pieces} عدد، تحویل={applied_total_before} عدد. عملیات متوقف شد."
            )
        return ledger

    if block.brand.name == "Novani" and applied_total_before > 0:
        repaired = AppSetting.objects.filter(key=f"{V34_REPAIR_PREFIX}{block.id}", value="1").exists()
        if not repaired:
            raise ValueError(
                "این صورت Novani قبل از سیستم مزد دوطرفه تحویل داشته ولی تأیید تعمیر مزد V34 برای آن پیدا نشد. "
                "برای جلوگیری از اصلاح اشتباه، موجودی و مزد تغییر نکرد."
            )

    ledger, _ = AppSetting.objects.update_or_create(
        key=key,
        defaults={
            "value": str(applied_total_before),
            "label": f"{block.brand.name} cumulative wage pieces for material block {block.id}",
        },
    )
    return ledger


def _sync_output(block):
    """Synchronize cumulative delivered quantities, stock/value and wage for Darma or Novani."""
    if block.brand.name not in {"دارما", "Novani"}:
        raise ValueError("برند صورت مواد معتبر نیست.")

    _validate_output_editable(block)
    operations = []
    applied_total_before = 0
    target_total = 0

    # Lock and prevalidate every affected stock row before any inventory/wage write.
    for model_key, _label in v20.OUTPUT_MODELS:
        for size_key, _size_label in v20._output_sizes_for_block(block):
            target = v20._target_qty(block, model_key, size_key)
            applied, _ = MaterialReportOutputApplied.objects.select_for_update().get_or_create(
                block=block,
                model_key=model_key,
                size_key=size_key,
                defaults={"quantity": 0},
            )
            done = int(applied.quantity or 0)
            delta = target - done
            applied_total_before += done
            target_total += target
            if delta == 0:
                continue

            brand, color, size, destination, destination_label, label, size_name = v20._production_objects(
                block, model_key, size_key
            )
            stock = StockBalance.objects.select_for_update().filter(
                brand=brand, color=color, size=size, location=destination
            ).first()
            available = int(stock.qty or 0) if stock else 0
            if delta < 0 and available < abs(delta):
                raise ValueError(
                    f"برای حذف {abs(delta)} عدد از {label} / {size_name} موجودی {destination_label} کافی نیست؛ "
                    f"موجودی فعلی {available} عدد است. هیچ تغییری اعمال نشد."
                )
            operations.append(
                (applied, target, delta, brand, color, size, destination, destination_label, label, size_name,
                 model_key, size_key)
            )

    wage_ledger = _lock_or_initialize_wage_ledger(block, applied_total_before)
    rate = int(v20._dozen_wage())
    wage_before = int(v20._wage_for_pieces(applied_total_before, rate))
    wage_after = int(v20._wage_for_pieces(target_total, rate))
    wage_change = wage_after - wage_before
    details = []

    for (
        applied, target, delta, brand, color, size, destination, _destination_label, label, size_name,
        model_key, size_key,
    ) in operations:
        if brand.name == "Novani":
            v20._apply_novani_stock(brand, color, size, destination, delta)
        elif brand.name == "دارما":
            v20._sync_finished_stock_costed(
                v20._sparse_output(model_key, size_key, abs(delta)),
                block.input_data or {},
                1 if delta > 0 else -1,
            )
        else:
            raise ValueError("برند صورت مواد معتبر نیست.")

        InventoryMovement.objects.create(
            movement_type=InventoryMovement.PRODUCTION,
            brand=brand,
            color=color,
            size=size,
            location=destination,
            delta=delta,
            reference=f"material-report:{block.id}:output-sync-v35",
        )
        applied.quantity = target
        applied.save(update_fields=["quantity", "updated_at"])
        details.append(f"{label}/{size_name}: {delta:+d}")

    if wage_change:
        # Positive wage_change = more delivered pieces -> more wage deducted.
        # Negative wage_change = corrected/removed pieces -> wage returned.
        v20._adjust_tailor_balance(-wage_change)

    wage_ledger.value = str(target_total)
    wage_ledger.save(update_fields=["value"])
    block.delivery_wage = wage_after
    block.save(update_fields=["delivery_wage", "updated_at"])

    return {
        "brand": block.brand.name,
        "destination": v20._destination_for_brand(block.brand)[1],
        "before_total": applied_total_before,
        "after_total": target_total,
        "piece_delta": target_total - applied_total_before,
        "wage_before": wage_before,
        "wage_after": wage_after,
        "wage_change": wage_change,
        "details": details,
    }


# Compatibility for the earlier v35 Novani-only regression/deploy image.
def _sync_novani_output(block):
    if block.brand.name != "Novani":
        raise ValueError("این alias فقط برای Novani است.")
    return _sync_output(block)


@login_required
@require_POST
def material_block_apply_output(request, block_id):
    try:
        with transaction.atomic():
            block = MaterialReportBlock.objects.select_for_update().select_related("brand").get(id=block_id)
            v20._save_block_data(block, request)
            result = _sync_output(block)

        delta = int(result["piece_delta"])
        wage_change = int(result["wage_change"])
        brand_name = result["brand"]
        destination = result["destination"]
        details = " | ".join(result["details"])

        if not result["details"]:
            messages.info(request, f"تحویل {brand_name} از قبل با موجودی و مزد همگام است؛ چیزی تغییر نکرد.")
        elif delta > 0:
            messages.success(
                request,
                f"تحویل {brand_name} همگام شد: خالص {delta} عدد به {destination} اضافه شد و "
                f"{max(0, wage_change):,} تومان مزد جدید اعمال شد. {details}",
            )
        elif delta < 0:
            messages.success(
                request,
                f"اصلاح تحویل {brand_name} انجام شد: خالص {abs(delta)} عدد از {destination} کم شد و "
                f"{abs(min(0, wage_change)):,} تومان مزد به حساب خیاط برگشت. {details}",
            )
        else:
            messages.success(
                request,
                f"ردیف‌های تحویل {brand_name} همگام شدند؛ جمع کل ثابت ماند و مزد خالص تغییری نکرد. {details}",
            )
    except MaterialReportBlock.DoesNotExist:
        messages.error(request, "صورت پیدا نشد.")
    except Exception as exc:
        messages.error(request, f"همگام‌سازی تحویل انجام نشد و کل عملیات برگشت: {exc}")
    return redirect(f"/material-report/#block-{block_id}")
