import jdatetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from .cost_accounting_v14 import snapshot_sale_line
from .dia_gallery_v45 import sync_dia_gallery_sale
from .finance import digikala_fee_for_unit
from .finance_excel_v9 import sync_sale_receivable
from .models import DiaGallerySale, SaleDay, SaleLine
from .sale_inventory_v19 import sync_sale_inventory_v19
from .variant_sale_v12 import VARIANT_PRODUCT_CODE, sync_variant_inventory


class SaleDayDeleteError(RuntimeError):
    pass


def _money(value):
    try:
        return int(str(value or "0").replace("٬", "").replace(",", "").replace(" ", ""))
    except (TypeError, ValueError):
        return 0


def _report_redirect(line):
    return redirect("daily_report", day_id=line.day_id)


def _is_variant_s3(line):
    product = line.product_size.product
    return product.brand.name == "دارما" and product.code == VARIANT_PRODUCT_CODE


def _validate_day_sale_line_reversal(line):
    """Block destructive day deletion when exact physical reversal is not provable.

    SaleAllocation is the authoritative record of what stock was actually deducted.
    If a line says inventory was applied but has no allocations, guessing from the
    current composition could restore the wrong colors for historical/replacement
    sales, so the whole day deletion must roll back instead.
    """
    applied = max(0, int(line.inventory_applied_quantity or 0))
    if applied > 0 and not line.allocations.exists():
        product = line.product_size.product
        size = line.product_size.size
        raise SaleDayDeleteError(
            f"حذف صورت متوقف شد: فروش {product.code} / {size.name} اثر موجودی دارد "
            "ولی Allocation واقعی برای برگشت دقیق آن پیدا نشد. هیچ تغییری ذخیره نشد."
        )


def _reverse_and_delete_sale_line_for_day(line):
    _validate_day_sale_line_reversal(line)

    line.quantity = 0
    line.save(update_fields=["quantity"])

    # Variable-color s3 has no fixed ProductComposition; its allocations encode
    # the exact colors selected in the Digikala file and need the variant engine.
    if _is_variant_s3(line):
        sync_variant_inventory(line, {})
    else:
        sync_sale_inventory_v19(line)

    sync_sale_receivable(line)
    line.delete()


def _reverse_and_delete_dia_line(line):
    # DiaGallerySale stores the exact color/size and applied quantity itself, so
    # setting the target to zero deterministically returns the applied stock to HOME
    # and removes the matching Dia receivable entry before deleting the row.
    line.quantity = 0
    line.save(update_fields=["quantity", "updated_at"])
    sync_dia_gallery_sale(line)
    line.delete()


@transaction.atomic
def delete_sale_day(day_id):
    """Atomically reverse every sale-owned effect of one SaleDay, then delete it.

    Scope is deliberately limited to objects owned by the sales day: SaleLine and
    DiaGallerySale. Expenses, payments, production, materials and manual stock
    corrections merely sharing the same calendar date are not part of this action.
    """
    day = SaleDay.objects.select_for_update().get(pk=day_id)
    day_date = day.date

    lines = list(
        SaleLine.objects.select_for_update()
        .filter(day=day)
        .select_related("day", "product_size__product__brand", "product_size__size")
        .prefetch_related("allocations")
        .order_by("id")
    )
    dia_lines = list(
        DiaGallerySale.objects.select_for_update()
        .filter(day=day)
        .select_related("day", "size", "color")
        .order_by("id")
    )

    # Validate all normal sale rows first so one unsafe historical row cannot leave
    # earlier rows reversed before the error is discovered. transaction.atomic is
    # still the final guard and rolls back every write on any exception.
    for line in lines:
        _validate_day_sale_line_reversal(line)

    normal_count = len(lines)
    dia_count = len(dia_lines)
    for line in lines:
        _reverse_and_delete_sale_line_for_day(line)
    for line in dia_lines:
        _reverse_and_delete_dia_line(line)

    if SaleLine.objects.filter(day=day).exists() or DiaGallerySale.objects.filter(day=day).exists():
        raise SaleDayDeleteError("حذف صورت کامل نشد؛ هیچ تغییری ذخیره نشد.")

    day.delete()
    return {
        "date": day_date,
        "sale_lines": normal_count,
        "dia_lines": dia_count,
    }


@login_required
@require_POST
@transaction.atomic
def sale_price_update(request, line_id):
    line = get_object_or_404(
        SaleLine.objects.select_for_update().select_related(
            "day", "product_size__product__brand", "product_size__size"
        ),
        id=line_id,
    )
    price = _money(request.POST.get("sale_price"))
    if price <= 0:
        messages.error(request, "قیمت فروش باید بیشتر از صفر باشد.")
        return _report_redirect(line)

    old_price = int(line.sale_price or 0)
    if old_price == price:
        messages.info(request, "قیمت تغییری نکرد.")
        return _report_redirect(line)

    line.sale_price = price
    line.save(update_fields=["sale_price"])

    # Editing a selling price must NOT rewrite historical COGS. Preserve the
    # frozen snapshot cost/pack quantity and only refresh the fee component.
    try:
        snap = line.snapshot
    except Exception:
        snap = None
    if snap is None:
        snapshot_sale_line(line, line.product_size, price)
    else:
        snap.digikala_fee_unit = digikala_fee_for_unit(price)
        snap.save(update_fields=["digikala_fee_unit", "updated_at"])

    sync_sale_receivable(line)
    messages.success(
        request,
        f"قیمت {line.product_size.product.code} / {line.product_size.size.name} از {old_price:,} به {price:,} اصلاح شد.",
    )
    return _report_redirect(line)


@login_required
@require_POST
@transaction.atomic
def sale_line_delete(request, line_id):
    line = get_object_or_404(
        SaleLine.objects.select_for_update().select_related(
            "day", "product_size__product__brand", "product_size__size"
        ),
        id=line_id,
    )
    day_id = line.day_id
    label = f"{line.product_size.product.code} / {line.product_size.size.name}"

    # Quantity zero is the supported inventory-reversal path. It restores all
    # allocations first; only after finance is cleared is the SaleLine deleted.
    line.quantity = 0
    line.save(update_fields=["quantity"])
    sync_sale_inventory_v19(line)
    sync_sale_receivable(line)
    line.delete()

    messages.success(request, f"فروش {label} حذف شد و اثر موجودی و طلب دیجی آن برگشت.")
    return redirect("daily_report", day_id=day_id)


@login_required
@require_POST
def sale_day_delete(request, day_id):
    # Fetch first only to preserve the normal 404 behavior and report redirect if a
    # guarded reversal refuses to proceed. The actual row is locked inside
    # delete_sale_day().
    day = get_object_or_404(SaleDay, id=day_id)
    try:
        result = delete_sale_day(day.id)
    except SaleDayDeleteError as exc:
        messages.error(request, str(exc))
        return redirect("daily_report", day_id=day.id)
    except SaleDay.DoesNotExist:
        messages.info(request, "این صورت قبلاً حذف شده است.")
        return redirect("sale_start")

    jalali = jdatetime.date.fromgregorian(date=result["date"])
    messages.success(
        request,
        "صورت روز حذف شد؛ فروش، طلب دیجی/Dia و تمام اثر موجودی فروش‌های همان روز برگشت. "
        f"{result['sale_lines']} ردیف فروش و {result['dia_lines']} ردیف Dia حذف شد.",
    )
    return redirect(f"{reverse('sale_start')}?jy={jalali.year}&jm={jalali.month}")
