from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from . import inventory_operations_v15 as v15
from . import inventory_operations_v16 as v16
from .models import InventoryAdjustment, InventoryMovement, StockTransfer


@transaction.atomic
def _update_transfer_qty(*, transfer_id, target_qty):
    """V80 guard: never rewrite an older transfer across a later manual absolute stock correction."""
    try:
        transfer = (
            StockTransfer.objects.select_for_update()
            .select_related("brand", "size", "color", "from_location", "to_location")
            .get(pk=transfer_id)
        )
    except StockTransfer.DoesNotExist as exc:
        raise ValueError("این انتقال دیگر وجود ندارد.") from exc

    reference = f"manual-transfer:{transfer.id}"
    transfer_movements = list(
        InventoryMovement.objects.select_for_update()
        .filter(
            movement_type=InventoryMovement.TRANSFER,
            reference=reference,
            brand=transfer.brand,
            size=transfer.size,
            color=transfer.color,
        )
        .order_by("id")
    )
    if len(transfer_movements) != 2:
        raise ValueError("گردش دقیق این انتقال پیدا نشد؛ برای حفظ موجودی ویرایش انجام نشد.")

    cutoff_id = max(row.id for row in transfer_movements)
    later_adjustments = list(
        InventoryMovement.objects.filter(
            movement_type=InventoryMovement.ADJUST,
            brand=transfer.brand,
            size=transfer.size,
            color=transfer.color,
            location_id__in=[transfer.from_location_id, transfer.to_location_id],
            id__gt=cutoff_id,
            reference__startswith="adjust:",
        ).only("id", "reference", "location_id")
    )
    adjustment_ids = {
        adjustment_id
        for row in later_adjustments
        if (adjustment_id := v15._adjustment_id_from_reference(row.reference)) is not None
    }
    if adjustment_ids and InventoryAdjustment.objects.filter(
        id__in=adjustment_ids,
        applied=True,
        note="",
    ).exists():
        raise ValueError(
            "بعد از این انتقال، روی همین رنگ/سایز «اصلاح موجودی» نهایی ثبت شده است. "
            "ویرایش انتقال قدیمی می‌تواند شمارش جدیدتر را خراب کند؛ بنابراین سیستم آن را تغییر نداد. "
            "اگر موجودی فعلی اشتباه است، از بخش اصلاح موجودی مقدار فیزیکی صحیح خانه/خورشید را ثبت کن."
        )

    return v16._update_transfer_qty(transfer_id=transfer_id, target_qty=target_qty)


@login_required
@require_POST
def inventory_transfer_update(request, transfer_id):
    try:
        result = _update_transfer_qty(
            transfer_id=transfer_id,
            target_qty=request.POST.get("qty"),
        )
        if result["deleted"]:
            messages.success(
                request,
                f"انتقال اشتباه {result['old_qty']} عددی حذف شد و اثر همان انتقال برگشت.",
            )
        elif result["old_qty"] == result["new_qty"]:
            messages.info(request, "تعداد انتقال تغییری نکرد.")
        else:
            messages.success(
                request,
                f"انتقال از {result['old_qty']} به {result['new_qty']} عدد اصلاح شد.",
            )
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("inventory_operations")
