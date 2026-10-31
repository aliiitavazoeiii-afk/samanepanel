from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .dateutils import parse_jalali_date
from .excel_views import (
    OUTPUT_MODELS,
    OUTPUT_SIZES,
    RAW_COLORS,
    _blank_input_data,
    _blank_output_data,
    _material_block_view,
    _today_jalali,
)
from .material_receipt_sync import reverse_report_consumption, sync_report_consumption
from .material_report_v14 import (
    _adjust_tailor_balance,
    _dozen_wage,
    _find_color,
    _int,
    _save_data_only,
    _sync_finished_stock_costed,
    _wage_for_pieces,
)
from .models import (
    Brand,
    InventoryModelCost,
    InventoryMovement,
    MaterialReportBlock,
    MaterialReportOutputApplied,
    Size,
    StockBalance,
    StockLocation,
)


MATERIAL_BRANDS = ("دارما", "Novani")
NOVANI_UNIT_COST = 61000


def _material_brands():
    brands = list(Brand.objects.filter(active=True, name__in=MATERIAL_BRANDS))
    order = {"دارما": 0, "Novani": 1}
    brands.sort(key=lambda b: (order.get(b.name, 99), b.id))
    return brands


def _selected_brand(request):
    brand = Brand.objects.filter(id=request.POST.get("brand"), active=True, name__in=MATERIAL_BRANDS).first()
    if not brand:
        raise ValueError("برند صورت مواد را انتخاب کن.")
    return brand


def _set_block_brand(block, request):
    brand = _selected_brand(request)
    if block.brand_id and block.brand_id != brand.id and block.output_applications.filter(quantity__gt=0).exists():
        raise ValueError("این صورت قبلاً محصول تحویلی روی موجودی اعمال کرده؛ برند آن دیگر قابل تغییر نیست.")
    block.brand = brand
    return brand


def _save_block_data(block, request):
    _set_block_brand(block, request)
    return _save_data_only(block, request)


def _applied_map(block):
    return {
        (row.model_key, row.size_key): int(row.quantity or 0)
        for row in block.output_applications.all()
    }


def _target_qty(block, model_key, size_key):
    return max(0, _int(((block.output_data or {}).get(model_key, {}) or {}).get(size_key)))


def _validate_output_floor(block):
    labels = dict(OUTPUT_MODELS)
    size_labels = dict(OUTPUT_SIZES)
    for applied in block.output_applications.all():
        target = _target_qty(block, applied.model_key, applied.size_key)
        if target < int(applied.quantity or 0):
            raise ValueError(
                f"{labels.get(applied.model_key, applied.model_key)} / "
                f"{size_labels.get(applied.size_key, applied.size_key)} قبلاً "
                f"{int(applied.quantity or 0)} عدد روی موجودی اعمال شده؛ "
                f"عدد جدول نمی‌تواند به {target} کاهش پیدا کند. برای کاهش، از اصلاح موجودی استفاده کن."
            )


def _output_stats(block):
    applied = _applied_map(block)
    entered_total = 0
    applied_total = 0
    pending_total = 0
    row_stats = {}
    for model_key, _label in OUTPUT_MODELS:
        entered_row = 0
        applied_row = 0
        for size_key, _size in OUTPUT_SIZES:
            target = _target_qty(block, model_key, size_key)
            done = int(applied.get((model_key, size_key), 0))
            entered_total += target
            applied_total += done
            pending_total += max(0, target - done)
            entered_row += target
            applied_row += done
        row_stats[model_key] = {
            "entered": entered_row,
            "applied": applied_row,
            "pending": max(0, entered_row - applied_row),
        }
    return {
        "entered": entered_total,
        "applied": applied_total,
        "pending": pending_total,
        "rows": row_stats,
    }


def _destination_for_brand(brand):
    if brand.name == "دارما":
        return StockLocation.objects.get(key=StockLocation.KHORSHID), "خورشید دارما"
    if brand.name == "Novani":
        return StockLocation.objects.get(key=StockLocation.HOME), "موجودی Novani"
    raise ValueError("برند تولید معتبر نیست.")


def _view_block(obj):
    row = _material_block_view(obj)
    stats = _output_stats(obj)
    row["materials_applied"] = obj.stock_consumptions.exists()
    row["material_consumption_count"] = obj.stock_consumptions.count()
    row["output_entered"] = stats["entered"]
    row["output_applied"] = stats["applied"]
    row["output_pending"] = stats["pending"]
    row["destination_label"] = "خورشید دارما" if obj.brand.name == "دارما" else "موجودی Novani"
    for index, (model_key, _label) in enumerate(OUTPUT_MODELS):
        row["output_rows"][index]["applied_total"] = stats["rows"][model_key]["applied"]
        row["output_rows"][index]["pending_total"] = stats["rows"][model_key]["pending"]
    return row


def _sparse_output(model_key, size_key, qty):
    return {model_key: {size_key: str(int(qty))}}


def _production_objects(block, model_key, size_key):
    label = dict(OUTPUT_MODELS)[model_key]
    size_name = dict(OUTPUT_SIZES)[size_key]
    brand = block.brand
    color = _find_color(label)
    size = Size.objects.get(name=size_name)
    destination, destination_label = _destination_for_brand(brand)
    return brand, color, size, destination, destination_label, label, size_name


def _apply_novani_stock(brand, color, size, destination, delta):
    stock, _ = StockBalance.objects.get_or_create(
        brand=brand,
        color=color,
        size=size,
        location=destination,
        defaults={"qty": 0},
    )
    stock = StockBalance.objects.select_for_update().get(pk=stock.pk)
    stock.qty = int(stock.qty or 0) + int(delta)
    stock.save(update_fields=["qty"])

    cost_row, _ = InventoryModelCost.objects.get_or_create(
        brand=brand,
        color=color,
        size=size,
        defaults={"unit_cost": NOVANI_UNIT_COST},
    )
    if int(cost_row.unit_cost or 0) <= 0:
        cost_row.unit_cost = NOVANI_UNIT_COST
        cost_row.save(update_fields=["unit_cost", "updated_at"])


def _apply_output_delta(block):
    """Apply only positive quantity not previously posted for each output cell."""
    _validate_output_floor(block)
    total_delta = 0
    details = []

    for model_key, _label in OUTPUT_MODELS:
        for size_key, _size in OUTPUT_SIZES:
            target = _target_qty(block, model_key, size_key)
            applied, _ = MaterialReportOutputApplied.objects.select_for_update().get_or_create(
                block=block,
                model_key=model_key,
                size_key=size_key,
                defaults={"quantity": 0},
            )
            done = int(applied.quantity or 0)
            delta = target - done
            if delta <= 0:
                continue

            brand, color, size, destination, destination_label, label, size_name = _production_objects(
                block, model_key, size_key
            )
            if brand.name == "دارما":
                # Preserve the existing v16/v14 Darma cost-blending behavior.
                _sync_finished_stock_costed(
                    _sparse_output(model_key, size_key, delta),
                    block.input_data or {},
                    +1,
                )
            elif brand.name == "Novani":
                # Novani is valued at its explicit inventory cost (61k for now),
                # not by the Darma batch-cost blending routine.
                _apply_novani_stock(brand, color, size, destination, delta)
            else:
                raise ValueError("برند صورت مواد معتبر نیست.")

            InventoryMovement.objects.create(
                movement_type=InventoryMovement.PRODUCTION,
                brand=brand,
                color=color,
                size=size,
                location=destination,
                delta=delta,
                reference=f"material-report:{block.id}:output-v19",
            )
            applied.quantity = target
            applied.save(update_fields=["quantity", "updated_at"])
            total_delta += delta
            details.append(f"{label}/{size_name}: +{delta}")

    if total_delta:
        wage_delta = _wage_for_pieces(total_delta, _dozen_wage())
        _adjust_tailor_balance(-wage_delta)
    else:
        wage_delta = 0
    return total_delta, wage_delta, details


@login_required
def material_report(request):
    brands = _material_brands()
    if request.method == "POST":
        try:
            brand = _selected_brand(request)
            block = MaterialReportBlock.objects.create(
                date=parse_jalali_date(request.POST.get("date") or _today_jalali()),
                title=(request.POST.get("title") or "").strip(),
                brand=brand,
                input_data=_blank_input_data(),
                output_data=_blank_output_data(),
            )
            messages.success(request, f"صورت جدید برای {brand.name} ساخته شد؛ هنوز هیچ اثری روی موجودی ندارد.")
            return redirect(f"/material-report/#block-{block.id}")
        except Exception as exc:
            messages.error(request, str(exc))
            return redirect("material_report")

    blocks = [
        _view_block(obj)
        for obj in MaterialReportBlock.objects.select_related("brand").prefetch_related(
            "output_applications", "stock_consumptions"
        ).all()[:40]
    ]
    return render(
        request,
        "core/material_report_v19.html",
        {
            "blocks": blocks,
            "brands": brands,
            "raw_colors": RAW_COLORS,
            "output_sizes": OUTPUT_SIZES,
            "today_j": _today_jalali(),
            "sewing_wage_rate": _dozen_wage(),
        },
    )


@login_required
@require_POST
def material_block_save(request, block_id):
    try:
        with transaction.atomic():
            block = MaterialReportBlock.objects.select_for_update().select_related("brand").get(id=block_id)
            _save_block_data(block, request)
            _validate_output_floor(block)
        messages.success(request, "صورت ذخیره شد؛ هیچ موجودی تغییر نکرد.")
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
            _save_block_data(block, request)
            _validate_output_floor(block)
            before = block.stock_consumptions.aggregate(v=Sum("quantity"))["v"] or 0
            sync_report_consumption(block)
            after = block.stock_consumptions.aggregate(v=Sum("quantity"))["v"] or 0
        messages.success(
            request,
            f"مواد اولیه صورت {block.brand.name} اعمال/همگام شد. این عملیات هیچ شورت آماده‌ای اضافه نکرد. "
            f"مصرف ثبت‌شده: {after} (قبل: {before}).",
        )
    except MaterialReportBlock.DoesNotExist:
        messages.error(request, "صورت پیدا نشد.")
    except Exception as exc:
        messages.error(request, f"اعمال مواد انجام نشد و کل عملیات برگشت: {exc}")
    return redirect(f"/material-report/#block-{block_id}")


@login_required
@require_POST
def material_block_unapply_materials(request, block_id):
    try:
        with transaction.atomic():
            block = MaterialReportBlock.objects.select_for_update().get(id=block_id)
            if not block.stock_consumptions.exists():
                raise ValueError("برای این صورت هنوز مصرف مواد اعمال نشده است.")
            reverse_report_consumption(block)
        messages.success(request, "فقط اثر مواد اولیه برگشت؛ موجودی شورت‌های تحویلی دست نخورد.")
    except MaterialReportBlock.DoesNotExist:
        messages.error(request, "صورت پیدا نشد.")
    except Exception as exc:
        messages.error(request, f"برگرداندن مواد انجام نشد: {exc}")
    return redirect(f"/material-report/#block-{block_id}")


@login_required
@require_POST
def material_block_apply_output(request, block_id):
    try:
        with transaction.atomic():
            block = MaterialReportBlock.objects.select_for_update().select_related("brand").get(id=block_id)
            _save_block_data(block, request)
            _validate_output_floor(block)
            delta, wage, details = _apply_output_delta(block)
            destination_label = _destination_for_brand(block.brand)[1]
        if delta:
            messages.success(
                request,
                f"فقط تحویل جدید اعمال شد: {delta} شورت به {destination_label} اضافه شد و مزد همین {delta} عدد "
                f"({wage:,} تومان) اعمال شد. " + " | ".join(details),
            )
        else:
            messages.info(request, "هیچ تحویل جدیدی برای اعمال وجود نداشت؛ موجودی تغییر نکرد.")
    except MaterialReportBlock.DoesNotExist:
        messages.error(request, "صورت پیدا نشد.")
    except Exception as exc:
        messages.error(request, f"اعمال تحویل انجام نشد و کل عملیات برگشت: {exc}")
    return redirect(f"/material-report/#block-{block_id}")


@login_required
@require_POST
def material_block_delete(request, block_id):
    block = get_object_or_404(MaterialReportBlock, id=block_id)
    try:
        if block.stock_consumptions.exists():
            raise ValueError("ابتدا اثر مواد اولیه این صورت را برگردان، سپس حذف کن.")
        if block.output_applications.filter(quantity__gt=0).exists():
            raise ValueError(
                "این صورت قبلاً شورت به موجودی اضافه کرده و برای جلوگیری از حذف ناخواسته موجودی قابل حذف نیست. "
                "اگر نیاز به اصلاح داری از اصلاح موجودی استفاده کن."
            )
        block.delete()
        messages.success(request, "صورت حذف شد.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("material_report")
