from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import redirect, render

from .brand_colors import TAKVIN_COLORS
from .dateutils import format_jalali, parse_jalali_date
from .models import (
    Brand,
    Color,
    ExcelManualSetting,
    InventoryMovement,
    Size,
    StockBalance,
    StockLocation,
    TakvinPurchase,
)

PREFIX = "[excel-web]"
SIZE_DEFAULTS = [("M", 120000), ("L", 140000), ("XL", 155000), ("XXL", 170000)]


def _int(value, default=0):
    try:
        if value in (None, ""):
            return default
        return int(str(value).replace(" ", "").replace(",", "").replace("٬", "").strip())
    except (TypeError, ValueError):
        return default


def _decimal(value, default="10"):
    try:
        if value in (None, ""):
            return Decimal(default)
        return Decimal(str(value).replace("٫", ".").replace(",", ".").strip())
    except Exception:
        return Decimal(default)


def _debt_setting():
    obj, _ = ExcelManualSetting.objects.get_or_create(
        key="takvin_debt", defaults={"label": "بدهی تکوین", "value": 0}
    )
    return obj


def _masters():
    sizes = []
    for order, (name, default_price) in enumerate(SIZE_DEFAULTS):
        size, _ = Size.objects.get_or_create(name=name, defaults={"sort_order": order})
        sizes.append({"obj": size, "name": name, "default_price": default_price})
    colors = []
    for name in TAKVIN_COLORS:
        color, _ = Color.objects.get_or_create(name=name, defaults={"active": True})
        colors.append(color)
    return sizes, colors


def _clean_note(note):
    raw = note or ""
    return raw[len(PREFIX):].strip() if raw.startswith(PREFIX) else raw


def _purchase_reference(obj):
    return f"takvin-purchase:{obj.id}"


def _purchase_movement(obj, *, lock=False):
    qs = InventoryMovement.objects.filter(
        movement_type=InventoryMovement.PURCHASE,
        reference=_purchase_reference(obj),
    )
    if lock:
        qs = qs.select_for_update()
    movements = list(qs)
    if len(movements) > 1:
        raise ValueError(f"برای خرید تکوین #{obj.id} بیش از یک گردش موجودی پیدا شد.")
    if not movements:
        return None

    movement = movements[0]
    brand = Brand.objects.get(name="تکوین")
    home = StockLocation.objects.get(key=StockLocation.HOME)
    if (
        movement.brand_id != brand.id
        or movement.size_id != obj.size_id
        or movement.color_id != obj.color_id
        or movement.location_id != home.id
        or int(movement.delta or 0) != int(obj.qty or 0)
    ):
        raise ValueError(
            f"گردش موجودی خرید تکوین #{obj.id} با ردیف خرید همخوان نیست؛ عملیات متوقف شد."
        )
    return movement


def _apply_purchase_stock(obj, *, allow_legacy_applied_missing=False):
    """Apply only the physical Takvin stock effect.

    The active Excel-style Takvin page keeps supplier debt in ExcelManualSetting.
    Therefore this helper intentionally does NOT create Account.TAKVIN entries and
    does not alter debt. It only adds HOME stock + exact InventoryMovement.
    """
    movement = _purchase_movement(obj, lock=True)
    if movement:
        if not obj.applied:
            obj.applied = True
            obj.save(update_fields=["applied"])
        return 0

    if obj.applied and not allow_legacy_applied_missing:
        raise ValueError(
            f"خرید تکوین #{obj.id} applied است ولی گردش موجودی ندارد؛ ابتدا تعمیر V59 را اجرا کن."
        )

    brand = Brand.objects.get(name="تکوین")
    home = StockLocation.objects.get(key=StockLocation.HOME)
    balance, _ = StockBalance.objects.get_or_create(
        brand=brand,
        size=obj.size,
        color=obj.color,
        location=home,
        defaults={"qty": 0},
    )
    balance = StockBalance.objects.select_for_update().get(pk=balance.pk)
    balance.qty = int(balance.qty or 0) + int(obj.qty or 0)
    balance.save(update_fields=["qty"])
    InventoryMovement.objects.create(
        movement_type=InventoryMovement.PURCHASE,
        brand=brand,
        size=obj.size,
        color=obj.color,
        location=home,
        delta=int(obj.qty or 0),
        reference=_purchase_reference(obj),
    )
    if not obj.applied:
        obj.applied = True
        obj.save(update_fields=["applied"])
    return int(obj.qty or 0)


def _reverse_purchase_stock(obj):
    """Remove exactly this purchase event from current HOME stock."""
    movement = _purchase_movement(obj, lock=True)
    if movement is None:
        if obj.applied:
            raise ValueError(
                f"گردش موجودی خرید تکوین #{obj.id} پیدا نشد؛ حذف/ویرایش برای حفظ موجودی متوقف شد."
            )
        return 0

    balance, _ = StockBalance.objects.get_or_create(
        brand_id=movement.brand_id,
        size_id=obj.size_id,
        color_id=obj.color_id,
        location_id=movement.location_id,
        defaults={"qty": 0},
    )
    balance = StockBalance.objects.select_for_update().get(pk=balance.pk)
    balance.qty = int(balance.qty or 0) - int(obj.qty or 0)
    balance.save(update_fields=["qty"])
    movement.delete()
    if obj.applied:
        obj.applied = False
        obj.save(update_fields=["applied"])
    return int(obj.qty or 0)


@login_required
def takvin_excel(request):
    sizes, colors = _masters()
    selected_text = request.GET.get("date") or format_jalali(date.today())
    try:
        selected_date = parse_jalali_date(selected_text)
    except ValueError:
        selected_date = date.today()
        selected_text = format_jalali(selected_date)

    if request.method == "POST":
        action = request.POST.get("action", "save")
        try:
            post_date = parse_jalali_date(request.POST.get("date") or selected_text)

            if action == "delete_day":
                with transaction.atomic():
                    old_rows = list(
                        TakvinPurchase.objects.select_for_update().filter(
                            date=post_date, note__startswith=PREFIX
                        ).order_by("id")
                    )
                    old_total = sum(int(row.total_cost or 0) for row in old_rows)
                    for row in old_rows:
                        _reverse_purchase_stock(row)
                    if old_rows:
                        TakvinPurchase.objects.filter(id__in=[row.id for row in old_rows]).delete()
                    debt = _debt_setting()
                    debt.value = int(debt.value or 0) - old_total
                    debt.save(update_fields=["value", "updated_at"])
                messages.success(
                    request,
                    "خرید تکوین این روز حذف شد؛ موجودی همان خرید و بدهی تکوین هر دو برگشتند.",
                )
                return redirect("takvin")

            discount = _decimal(request.POST.get("discount_percent"), "10")
            if discount < 0 or discount > 100:
                raise ValueError("درصد تخفیف باید بین صفر تا ۱۰۰ باشد.")
            user_note = (request.POST.get("note") or "").strip()
            prices = {
                item["obj"].id: max(
                    0,
                    _int(
                        request.POST.get(f"price_{item['obj'].id}"),
                        item["default_price"],
                    ),
                )
                for item in sizes
            }
            pending = []
            new_total = 0
            for color in colors:
                for item in sizes:
                    size = item["obj"]
                    qty = max(0, _int(request.POST.get(f"qty_{color.id}_{size.id}")))
                    if not qty:
                        continue
                    list_price = prices[size.id]
                    net_price = int(
                        (
                            Decimal(list_price)
                            * (Decimal("1") - discount / Decimal("100"))
                        ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                    )
                    pending.append((color, size, qty, list_price, net_price))
                    new_total += qty * net_price
            if not pending:
                raise ValueError(
                    "حداقل یک تعداد خرید وارد کن؛ برای پاک‌کردن روز از دکمه حذف استفاده کن."
                )

            with transaction.atomic():
                old_rows = list(
                    TakvinPurchase.objects.select_for_update().filter(
                        date=post_date, note__startswith=PREFIX
                    ).order_by("id")
                )
                old_total = sum(int(row.total_cost or 0) for row in old_rows)
                for row in old_rows:
                    _reverse_purchase_stock(row)
                if old_rows:
                    TakvinPurchase.objects.filter(id__in=[row.id for row in old_rows]).delete()

                created = []
                for color, size, qty, list_price, net_price in pending:
                    obj = TakvinPurchase.objects.create(
                        date=post_date,
                        size=size,
                        color=color,
                        qty=qty,
                        list_unit_price=list_price,
                        discount_percent=discount,
                        net_unit_price=net_price,
                        total_cost=qty * net_price,
                        note=f"{PREFIX} {user_note}".strip(),
                        applied=False,
                    )
                    _apply_purchase_stock(obj)
                    created.append(obj)

                debt = _debt_setting()
                debt.value = int(debt.value or 0) + (new_total - old_total)
                debt.save(update_fields=["value", "updated_at"])

            messages.success(
                request,
                f"خرید تکوین ذخیره شد؛ {sum(int(row.qty or 0) for row in created):,} عدد به موجودی HOME تکوین اضافه شد و مبلغ خالص به بدهی تکوین اضافه شد.",
            )
            return redirect(f"/takvin/?date={format_jalali(post_date)}")
        except Exception as exc:
            messages.error(request, str(exc))
            selected_text = request.POST.get("date") or selected_text
            try:
                selected_date = parse_jalali_date(selected_text)
            except ValueError:
                selected_date = date.today()
                selected_text = format_jalali(selected_date)

    existing = list(
        TakvinPurchase.objects.filter(
            date=selected_date, note__startswith=PREFIX
        )
        .select_related("size", "color")
        .order_by("color__name", "size__sort_order")
    )
    qty_map = {(r.color_id, r.size_id): r.qty for r in existing}
    saved_prices = {}
    for row in existing:
        saved_prices.setdefault(row.size_id, row.list_unit_price)
    discount_value = existing[0].discount_percent if existing else Decimal("10")
    note_value = _clean_note(existing[0].note) if existing else ""
    grid_rows = [
        {
            "color": color,
            "cells": [
                {
                    "size": item["obj"],
                    "name": f"qty_{color.id}_{item['obj'].id}",
                    "value": qty_map.get((color.id, item["obj"].id), 0),
                }
                for item in sizes
            ],
        }
        for color in colors
    ]
    size_rows = []
    for item in sizes:
        size = item["obj"]
        qty_total = sum(r.qty for r in existing if r.size_id == size.id)
        list_price = saved_prices.get(size.id, item["default_price"])
        size_rows.append(
            {
                "obj": size,
                "name": item["name"],
                "price": list_price,
                "qty": qty_total,
                "before": qty_total * list_price,
                "net": sum(r.total_cost for r in existing if r.size_id == size.id),
            }
        )
    grouped = defaultdict(lambda: {"qty": 0, "before": 0, "net": 0})
    for row in TakvinPurchase.objects.filter(note__startswith=PREFIX).order_by("-date", "-id")[:600]:
        data = grouped[row.date]
        data["qty"] += row.qty
        data["before"] += row.qty * row.list_unit_price
        data["net"] += row.total_cost
    history_rows = [
        {"date": d, "jalali": format_jalali(d), **data}
        for d, data in sorted(grouped.items(), reverse=True)[:30]
    ]
    return render(
        request,
        "core/takvin_excel.html",
        {
            "selected_date": selected_text,
            "sizes": sizes,
            "grid_rows": grid_rows,
            "size_rows": size_rows,
            "discount_value": discount_value,
            "note_value": note_value,
            "day_total_qty": sum(r.qty for r in existing),
            "day_before": sum(r.qty * r.list_unit_price for r in existing),
            "day_net": sum(r.total_cost for r in existing),
            "history_rows": history_rows,
            "takvin_debt": int(_debt_setting().value or 0),
        },
    )
