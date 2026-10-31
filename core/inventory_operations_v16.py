from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from . import inventory_operations_v15 as v15
from .brand_colors import colors_for_brand
from .dateutils import format_jalali
from .models import (
    Brand,
    Color,
    InventoryAdjustment,
    InventoryMovement,
    Size,
    StockBalance,
    StockLocation,
    StockTransfer,
)


INVENTORY_BRANDS = v15.INVENTORY_BRANDS


@transaction.atomic
def _update_transfer_qty(*, transfer_id, target_qty):
    """Correct one applied KHORSHID -> HOME transfer without touching total stock.

    The original transfer and its exact two movement rows are rewritten to the
    corrected quantity. Current balances receive only the difference between the
    old and new quantity, so later sales/adjustments are preserved. HOME may be
    negative by business rule; KHORSHID is never allowed to go negative when a
    transfer is increased. A target of zero fully removes the mistaken transfer.
    """
    try:
        transfer = (
            StockTransfer.objects.select_for_update()
            .select_related("brand", "size", "color", "from_location", "to_location")
            .get(pk=transfer_id)
        )
    except StockTransfer.DoesNotExist as exc:
        raise ValueError("این انتقال دیگر وجود ندارد.") from exc

    if not transfer.applied:
        raise ValueError("این انتقال هنوز اعمال نشده و از این بخش قابل ویرایش نیست.")
    if transfer.brand.name != "دارما":
        raise ValueError("ویرایش انتقال این بخش فقط برای دارما فعال است.")
    if (
        (transfer.from_location.key, transfer.to_location.key)
        not in {
            (StockLocation.KHORSHID, StockLocation.HOME),
            (StockLocation.HOME, StockLocation.KHORSHID),
        }
    ):
        raise ValueError("فقط انتقال بین انبار و خانه از این بخش قابل ویرایش است.")

    try:
        target_qty = int(target_qty)
    except (TypeError, ValueError) as exc:
        raise ValueError("تعداد جدید معتبر نیست.") from exc
    if target_qty < 0:
        raise ValueError("تعداد جدید نمی‌تواند منفی باشد.")

    old_qty = int(transfer.qty or 0)
    reference = f"manual-transfer:{transfer.id}"
    movements = list(
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
    if len(movements) != 2:
        raise ValueError("گردش دقیق این انتقال پیدا نشد؛ برای حفظ موجودی ویرایش انجام نشد.")

    source_movement = next(
        (
            movement
            for movement in movements
            if movement.location_id == transfer.from_location_id
            and int(movement.delta) == -old_qty
        ),
        None,
    )
    destination_movement = next(
        (
            movement
            for movement in movements
            if movement.location_id == transfer.to_location_id
            and int(movement.delta) == old_qty
        ),
        None,
    )
    if not source_movement or not destination_movement:
        raise ValueError("مقدار گردش انتقال با رکورد اصلی همخوان نیست؛ ویرایش امن متوقف شد.")

    source_balance, _ = StockBalance.objects.get_or_create(
        brand=transfer.brand,
        size=transfer.size,
        color=transfer.color,
        location=transfer.from_location,
        defaults={"qty": 0},
    )
    destination_balance, _ = StockBalance.objects.get_or_create(
        brand=transfer.brand,
        size=transfer.size,
        color=transfer.color,
        location=transfer.to_location,
        defaults={"qty": 0},
    )
    source_balance = StockBalance.objects.select_for_update().get(pk=source_balance.pk)
    destination_balance = StockBalance.objects.select_for_update().get(pk=destination_balance.pk)

    difference = target_qty - old_qty
    if difference > 0 and int(source_balance.qty or 0) < difference:
        raise ValueError(
            f"برای افزایش این انتقال، موجودی خورشید کافی نیست. "
            f"برای اصلاح {difference} عدد دیگر لازم است ولی موجودی فعلی خورشید "
            f"{int(source_balance.qty or 0)} عدد است."
        )

    # V123: reducing a HOUSE -> WAREHOUSE transfer must not create
    # negative physical warehouse inventory if those goods have since moved.
    if (difference < 0 and transfer.to_location.key == StockLocation.KHORSHID
            and int(destination_balance.qty or 0) < -difference):
        raise ValueError("امکان کاهش این انتقال نیست؛ موجودی فعلی انبار برای برگشت کافی نیست.")

    if difference:
        source_balance.qty = int(source_balance.qty or 0) - difference
        destination_balance.qty = int(destination_balance.qty or 0) + difference
        source_balance.save(update_fields=["qty"])
        destination_balance.save(update_fields=["qty"])

    if target_qty == 0:
        source_movement.delete()
        destination_movement.delete()
        transfer.delete()
        return {
            "deleted": True,
            "old_qty": old_qty,
            "new_qty": 0,
            "difference": -old_qty,
        }

    transfer.qty = target_qty
    transfer.save(update_fields=["qty"])
    source_movement.delta = -target_qty
    destination_movement.delta = target_qty
    source_movement.save(update_fields=["delta"])
    destination_movement.save(update_fields=["delta"])
    return {
        "deleted": False,
        "old_qty": old_qty,
        "new_qty": target_qty,
        "difference": difference,
    }


@login_required
@require_POST
def inventory_transfer_update(request, transfer_id):
    try:
        raw_qty = request.POST.get("qty")
        result = _update_transfer_qty(transfer_id=transfer_id, target_qty=raw_qty)
        if result["deleted"]:
            messages.success(
                request,
                f"انتقال اشتباه {result['old_qty']} عددی حذف شد و موجودی به حالت صحیح برگشت.",
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


@login_required
def inventory_operations(request):
    brands = Brand.objects.filter(active=True, name__in=INVENTORY_BRANDS).order_by("id")
    transfer_brands = brands.filter(name="دارما")
    sizes = Size.objects.all()
    locations = StockLocation.objects.all()
    darma = transfer_brands.first()
    transfer_colors = colors_for_brand(darma) if darma else Color.objects.none()
    adjustment_groups = [
        {"brand": brand, "colors": list(colors_for_brand(brand))}
        for brand in brands
    ]

    if request.method == "POST":
        try:
            action = request.POST.get("action")
            brand = Brand.objects.filter(
                id=request.POST.get("brand"),
                active=True,
                name__in=INVENTORY_BRANDS,
            ).first()
            if not brand:
                raise ValueError("برند موجودی معتبر نیست.")

            size = Size.objects.filter(id=request.POST.get("size")).first()
            if not size:
                raise ValueError("سایز معتبر نیست.")

            if action == "transfer":
                if brand.name != "دارما":
                    raise ValueError("انتقال خانه/خورشید فقط برای دارما فعال است.")
                brand_colors = list(colors_for_brand(brand))
                color_quantities = [
                    (color, max(0, v15._int(request.POST.get(f"qty_{color.id}"))))
                    for color in brand_colors
                ]
                result = v15._bulk_transfer_khorshid_to_home(
                    transfer_date=v15._date(request.POST.get("date")),
                    brand=brand,
                    size=size,
                    color_quantities=color_quantities,
                )
                messages.success(
                    request,
                    f"انتقال خورشید به خانه ثبت شد؛ {result['total_qty']} عدد در "
                    f"{len(result['transfers'])} رنگ منتقل شد.",
                )

            elif action == "adjust":
                location_id = request.POST.get("location")
                if brand.name == "Novani":
                    location = StockLocation.objects.get(key=StockLocation.HOME)
                else:
                    location = StockLocation.objects.filter(id=location_id).first()
                    if not location:
                        raise ValueError("محل موجودی معتبر نیست.")

                brand_colors = list(colors_for_brand(brand))
                color_targets = []
                for color in brand_colors:
                    raw_target = request.POST.get(f"target_{brand.id}_{color.id}")
                    if raw_target in (None, ""):
                        continue
                    target_qty = v15._int(raw_target, -1)
                    if target_qty < 0:
                        raise ValueError(f"{color.name}: موجودی اصلی نمی‌تواند منفی باشد.")
                    color_targets.append((color, target_qty))

                result = v15._bulk_set_inventory_targets(
                    adjustment_date=v15._date(request.POST.get("date")),
                    brand=brand,
                    size=size,
                    location=location,
                    color_targets=color_targets,
                )
                changed_count = len(result["changed"])
                unchanged_count = len(result["unchanged"])
                if changed_count:
                    messages.success(
                        request,
                        f"اصلاح موجودی ثبت شد؛ {changed_count} رنگ بروزرسانی شد"
                        + (f" و {unchanged_count} رنگ از قبل همان مقدار بود." if unchanged_count else "."),
                    )
                else:
                    messages.info(request, "همه موجودی‌های واردشده از قبل همین مقدار بودند؛ تغییری ثبت نشد.")
            else:
                raise ValueError("نوع عملیات موجودی معتبر نیست.")

        except Exception as exc:
            messages.error(request, str(exc))
        return redirect("inventory_operations")

    recent = list(
        InventoryMovement.objects.select_related(
            "brand", "size", "color", "location"
        ).order_by("-id")[:50]
    )
    candidate_ids = {
        adjustment_id
        for movement in recent
        if (adjustment_id := v15._adjustment_id_from_reference(movement.reference)) is not None
    }
    adjustments = {
        row.id: row
        for row in InventoryAdjustment.objects.filter(id__in=candidate_ids, applied=True, note="")
    }
    for movement in recent:
        movement.adjustment_delete_id = None
        adjustment_id = v15._adjustment_id_from_reference(movement.reference)
        adjustment = adjustments.get(adjustment_id)
        if not adjustment:
            continue
        if (
            movement.movement_type == InventoryMovement.ADJUST
            and movement.brand_id == adjustment.brand_id
            and movement.size_id == adjustment.size_id
            and movement.color_id == adjustment.color_id
            and movement.location_id == adjustment.location_id
            and int(movement.delta) == int(adjustment.delta)
        ):
            movement.adjustment_delete_id = adjustment.id

    recent_transfers = list(
        StockTransfer.objects.filter(
            applied=True,
            brand__name="دارما",
            from_location__key__in=[StockLocation.KHORSHID, StockLocation.HOME],
            to_location__key__in=[StockLocation.KHORSHID, StockLocation.HOME],
        )
        .select_related("brand", "size", "color", "from_location", "to_location")
        .order_by("-id")[:50]
    )
    stock_snapshot = v15._stock_snapshot_for_operations(brands)

    return render(
        request,
        "core/inventory_operations.html",
        {
            "brands": brands,
            "transfer_brands": transfer_brands,
            "transfer_colors": transfer_colors,
            "adjustment_groups": adjustment_groups,
            "sizes": sizes,
            "locations": locations,
            "recent": recent,
            "recent_transfers": recent_transfers,
            "today_j": format_jalali(date.today()),
            "stock_snapshot": stock_snapshot,
        },
    )
