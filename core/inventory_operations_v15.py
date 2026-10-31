from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .brand_colors import colors_for_brand
from .dateutils import format_jalali, parse_jalali_date
from .final_services import sync_inventory_adjustment, sync_stock_transfer
from .models import (
    Brand, Color, InventoryAdjustment, InventoryMovement, Size,
    StockBalance, StockLocation, StockTransfer,
)


INVENTORY_BRANDS = ("دارما", "تکوین", "Novani")


def _int(value, default=0):
    try:
        if value in (None, ""):
            return default
        return int(str(value).replace(" ", "").replace(",", "").replace("٬", ""))
    except Exception:
        return default


def _date(value=None):
    return parse_jalali_date(value) if value else date.today()


def _adjustment_id_from_reference(reference):
    raw = str(reference or "")
    if not raw.startswith("adjust:"):
        return None
    value = raw.split(":", 1)[1]
    if not value.isdigit():
        return None
    adjustment_id = int(value)
    return adjustment_id if raw == f"adjust:{adjustment_id}" else None


def _stock_snapshot_for_operations(brands):
    """Read-only stock snapshot for the operations UI.

    The snapshot mirrors the inventory page definition of total stock:
    HOME + KHORSHID. It is presentation data only and never writes balances.
    """
    brand_ids = list(brands.values_list("id", flat=True))
    snapshot = {}
    balances = (
        StockBalance.objects.filter(brand_id__in=brand_ids)
        .select_related("location")
        .only("brand_id", "size_id", "color_id", "qty", "location__key")
    )
    for balance in balances:
        if balance.location.key not in {StockLocation.HOME, StockLocation.KHORSHID}:
            continue
        key = f"{balance.brand_id}:{balance.size_id}:{balance.color_id}"
        row = snapshot.setdefault(key, {"home": 0, "khorshid": 0, "total": 0})
        if balance.location.key == StockLocation.HOME:
            row["home"] += int(balance.qty or 0)
        elif balance.location.key == StockLocation.KHORSHID:
            row["khorshid"] += int(balance.qty or 0)

    for row in snapshot.values():
        row["total"] = int(row["home"]) + int(row["khorshid"])
    return snapshot


@transaction.atomic
def _set_inventory_target(*, adjustment_date, brand, size, color, location, target_qty, note=""):
    """Set one stock cell to an absolute counted quantity using the existing adjustment ledger.

    InventoryAdjustment remains delta-based for audit/history. The UI/business input is
    absolute: delta is calculated as target_qty - current_qty under a row lock.
    """
    balance, _ = StockBalance.objects.get_or_create(
        brand=brand,
        size=size,
        color=color,
        location=location,
        defaults={"qty": 0},
    )
    balance = StockBalance.objects.select_for_update().get(pk=balance.pk)
    current_qty = int(balance.qty or 0)
    delta = int(target_qty) - current_qty
    if delta == 0:
        return {
            "adjustment": None,
            "before": current_qty,
            "after": current_qty,
            "delta": 0,
        }

    obj = InventoryAdjustment.objects.create(
        date=adjustment_date,
        brand=brand,
        size=size,
        color=color,
        location=location,
        delta=delta,
        note=note or "",
    )
    sync_inventory_adjustment(obj)
    return {
        "adjustment": obj,
        "before": current_qty,
        "after": int(target_qty),
        "delta": delta,
    }


@transaction.atomic
def _bulk_set_inventory_targets(*, adjustment_date, brand, size, location, color_targets):
    """Set multiple color cells to absolute physical counts in one atomic submit.

    Blank fields are filtered by the caller. An explicit zero means the counted
    stock for that color is zero. Existing InventoryAdjustment/Movement semantics
    remain unchanged because every target is converted to a delta under lock.
    """
    prepared = []
    for color, target_qty in color_targets:
        target_qty = int(target_qty)
        if target_qty < 0:
            raise ValueError(f"{color.name}: موجودی اصلی نمی‌تواند منفی باشد.")
        prepared.append((color, target_qty))

    if not prepared:
        raise ValueError("حداقل موجودی اصلی یک رنگ را وارد کن.")

    changed = []
    unchanged = []
    for color, target_qty in prepared:
        result = _set_inventory_target(
            adjustment_date=adjustment_date,
            brand=brand,
            size=size,
            color=color,
            location=location,
            target_qty=target_qty,
            note="",
        )
        row = {"color": color, **result}
        if result["delta"]:
            changed.append(row)
        else:
            unchanged.append(row)

    return {
        "changed": changed,
        "unchanged": unchanged,
        "entered_count": len(prepared),
        "net_delta": sum(int(row["delta"]) for row in changed),
    }


@transaction.atomic
def _bulk_transfer_khorshid_to_home(*, transfer_date, brand, size, color_quantities):
    """Apply one form submission as multiple explicit KHORSHID -> HOME transfers.

    The existing StockTransfer model/service remains authoritative. Every non-zero
    color becomes its own StockTransfer row, while the full batch is atomic.
    """
    if brand.name != "دارما":
        raise ValueError("انتقال خانه/خورشید فقط برای دارما فعال است.")

    home = StockLocation.objects.get(key=StockLocation.HOME)
    khorshid = StockLocation.objects.get(key=StockLocation.KHORSHID)
    prepared = []

    for color, qty in color_quantities:
        qty = int(qty or 0)
        if qty <= 0:
            continue
        src, _ = StockBalance.objects.get_or_create(
            brand=brand,
            size=size,
            color=color,
            location=khorshid,
            defaults={"qty": 0},
        )
        src = StockBalance.objects.select_for_update().get(pk=src.pk)
        available = int(src.qty or 0)
        if available < qty:
            raise ValueError(
                f"{color.name}: موجودی خورشید کافی نیست. موجودی فعلی {available} عدد است، "
                f"ولی {qty} عدد برای انتقال وارد شده."
            )
        prepared.append((color, qty))

    if not prepared:
        raise ValueError("حداقل برای یک رنگ تعداد انتقال را وارد کن.")

    created = []
    total_qty = 0
    for color, qty in prepared:
        obj = StockTransfer.objects.create(
            date=transfer_date,
            brand=brand,
            size=size,
            color=color,
            qty=qty,
            from_location=khorshid,
            to_location=home,
            note="",
        )
        sync_stock_transfer(obj)
        created.append(obj)
        total_qty += qty

    return {"transfers": created, "total_qty": total_qty}


@transaction.atomic
def _delete_inventory_adjustment(adjustment_id):
    """Reverse and delete one manual inventory-operations correction safely.

    The V50 correction form stores an empty note. Other workflows such as standalone
    returns use InventoryAdjustment too, with their own note markers, and must never
    become deletable from this table.

    Deletion is also refused if a newer movement exists on the same stock cell,
    because then "return to the previous stock" would cross newer history.
    """
    try:
        adjustment = (
            InventoryAdjustment.objects.select_for_update()
            .select_related("brand", "size", "color", "location")
            .get(pk=adjustment_id)
        )
    except InventoryAdjustment.DoesNotExist as exc:
        raise ValueError("این اصلاح موجودی دیگر وجود ندارد.") from exc

    if not adjustment.applied:
        raise ValueError("این اصلاح موجودی اعمال نشده و قابل حذف از گردش اعمال‌شده نیست.")
    if str(adjustment.note or "").strip():
        raise ValueError("این گردش مربوط به اصلاح دستی موجودی نیست و از این بخش قابل حذف نیست.")

    reference = f"adjust:{adjustment.id}"
    movements = list(
        InventoryMovement.objects.select_for_update().filter(
            movement_type=InventoryMovement.ADJUST,
            reference=reference,
        )
    )
    if len(movements) != 1:
        raise ValueError("گردش دقیق این اصلاح پیدا نشد؛ برای حفظ موجودی حذف انجام نشد.")

    movement = movements[0]
    if (
        movement.brand_id != adjustment.brand_id
        or movement.size_id != adjustment.size_id
        or movement.color_id != adjustment.color_id
        or movement.location_id != adjustment.location_id
        or int(movement.delta) != int(adjustment.delta)
    ):
        raise ValueError("اطلاعات اصلاح با گردش موجودی آن همخوان نیست؛ حذف امن متوقف شد.")

    balance, _ = StockBalance.objects.get_or_create(
        brand=adjustment.brand,
        size=adjustment.size,
        color=adjustment.color,
        location=adjustment.location,
        defaults={"qty": 0},
    )
    balance = StockBalance.objects.select_for_update().get(pk=balance.pk)

    if InventoryMovement.objects.filter(
        brand_id=adjustment.brand_id,
        size_id=adjustment.size_id,
        color_id=adjustment.color_id,
        location_id=adjustment.location_id,
        id__gt=movement.id,
    ).exists():
        raise ValueError(
            "بعد از این اصلاح روی همین موجودی گردش جدید ثبت شده است؛ "
            "برای جلوگیری از خراب‌شدن فروش/انتقال/شمارش جدیدتر، این رکورد قدیمی حذف نمی‌شود. "
            "یک اصلاح موجودی جدید با مقدار فیزیکی درست ثبت کن."
        )

    before = int(balance.qty or 0)
    balance.qty = before - int(adjustment.delta)
    balance.save(update_fields=["qty"])
    after = int(balance.qty or 0)
    reversed_delta = -int(adjustment.delta)

    movement.delete()
    adjustment.delete()
    return {
        "before": before,
        "after": after,
        "delta_reversed": reversed_delta,
    }


@login_required
@require_POST
def inventory_adjustment_delete(request, adjustment_id):
    try:
        result = _delete_inventory_adjustment(adjustment_id)
        messages.success(
            request,
            f"اصلاح موجودی حذف شد و موجودی از {result['before']} به {result['after']} برگشت.",
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
                    (color, max(0, _int(request.POST.get(f"qty_{color.id}"))))
                    for color in brand_colors
                ]
                result = _bulk_transfer_khorshid_to_home(
                    transfer_date=_date(request.POST.get("date")),
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
                    target_qty = _int(raw_target, -1)
                    if target_qty < 0:
                        raise ValueError(f"{color.name}: موجودی اصلی نمی‌تواند منفی باشد.")
                    color_targets.append((color, target_qty))

                result = _bulk_set_inventory_targets(
                    adjustment_date=_date(request.POST.get("date")),
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
        if (adjustment_id := _adjustment_id_from_reference(movement.reference)) is not None
    }
    adjustments = {
        row.id: row
        for row in InventoryAdjustment.objects.filter(id__in=candidate_ids, applied=True, note="")
    }
    for movement in recent:
        movement.adjustment_delete_id = None
        adjustment_id = _adjustment_id_from_reference(movement.reference)
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

    stock_snapshot = _stock_snapshot_for_operations(brands)

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
            "today_j": format_jalali(date.today()),
            "stock_snapshot": stock_snapshot,
        },
    )
