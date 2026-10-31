from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .darma_cost_v55 import darma_cost_for
from .final_services import _record_stock, _stock, _transfer_for_need
from .models import (
    Account,
    AccountEntry,
    Brand,
    Color,
    DiaGallerySale,
    InventoryMovement,
    ProductComposition,
    SaleDay,
    Size,
    StockBalance,
    StockLocation,
)


DIA_GALLERY_UNIT_PRICE = 71_000
DIA_GALLERY_ACCOUNT_TITLE = "فروش Dia Gallery"
DARMA_SIZE_NAMES = ("M", "L", "XL", "XXL", "3XL", "4XL")


def _int(value, default=0):
    try:
        if value in (None, ""):
            return default
        return int(str(value).replace(" ", "").replace(",", "").replace("٬", "").strip())
    except (TypeError, ValueError):
        return default


def _dia_account(*, create=False):
    qs = Account.objects.filter(key=Account.DIA_GALLERY)
    account = qs.first()
    if account is not None or not create:
        return account
    account, _ = Account.objects.get_or_create(
        key=Account.DIA_GALLERY,
        defaults={"title": DIA_GALLERY_ACCOUNT_TITLE, "opening_balance": 0},
    )
    if account.title != DIA_GALLERY_ACCOUNT_TITLE:
        account.title = DIA_GALLERY_ACCOUNT_TITLE
        account.save(update_fields=["title"])
    return account


def dia_gallery_receivable_total():
    account = _dia_account(create=False)
    if account is None:
        return 0
    entries = account.entries.aggregate(v=Sum("delta"))["v"] or 0
    return int(account.opening_balance or 0) + int(entries)


def _sync_receivable(line):
    account = _dia_account(create=True)
    reference = f"dia-gallery:{line.id}:receivable"
    AccountEntry.objects.filter(account=account, reference=reference).delete()
    amount = int(line.quantity or 0) * DIA_GALLERY_UNIT_PRICE
    if amount:
        AccountEntry.objects.create(
            date=line.day.date,
            account=account,
            delta=amount,
            title=f"فروش Dia Gallery · {line.color.name} / {line.size.name}",
            reference=reference,
            entry_type="dia_gallery_sale",
            note=f"ثبت خودکار با فی ثابت {DIA_GALLERY_UNIT_PRICE} تومان",
        )
    return amount


@transaction.atomic
def sync_dia_gallery_sale(line):
    line = DiaGallerySale.objects.select_for_update().select_related(
        "day", "size", "color"
    ).get(pk=line.pk)
    darma = Brand.objects.get(name="دارما")
    home = StockLocation.objects.get(key=StockLocation.HOME)

    target = max(0, int(line.quantity or 0))
    applied = max(0, int(line.inventory_applied_quantity or 0))
    delta = target - applied
    reference = f"dia-gallery:{line.id}"

    if target > 0 and int(line.unit_cost or 0) <= 0:
        # Freeze the canonical Darma cost effective on this sale date. Existing
        # nonzero Dia costs remain historical snapshots and are never rewritten by
        # later rule changes.
        line.unit_cost = int(darma_cost_for(line.day.date))

    if delta > 0:
        balance = _transfer_for_need(
            brand=darma,
            size=line.size,
            color=line.color,
            needed=delta,
            reference=f"{reference}:auto-transfer",
        )
        balance.qty -= delta
        balance.save(update_fields=["qty"])
        _record_stock(
            movement_type=InventoryMovement.SALE,
            brand=darma,
            size=line.size,
            color=line.color,
            location=home,
            delta=-delta,
            reference=reference,
        )
    elif delta < 0:
        give_back = -delta
        balance = _stock(
            brand=darma,
            size=line.size,
            color=line.color,
            location=home,
        )
        balance.qty += give_back
        balance.save(update_fields=["qty"])
        _record_stock(
            movement_type=InventoryMovement.ADJUST,
            brand=darma,
            size=line.size,
            color=line.color,
            location=home,
            delta=give_back,
            reference=f"{reference}:recalc",
        )

    line.inventory_applied_quantity = target
    line.unit_price = DIA_GALLERY_UNIT_PRICE
    line.save(update_fields=[
        "inventory_applied_quantity",
        "unit_price",
        "unit_cost",
        "updated_at",
    ])
    receivable = _sync_receivable(line)
    return {
        "delta": delta,
        "receivable": receivable,
        "unit_cost": int(line.unit_cost or 0),
    }


def _darma_sizes():
    sizes = list(Size.objects.filter(name__in=DARMA_SIZE_NAMES).order_by("sort_order", "id"))
    order = {name: index for index, name in enumerate(DARMA_SIZE_NAMES)}
    sizes.sort(key=lambda s: (order.get(s.name, 99), s.id))
    return sizes


def _darma_colors():
    darma = Brand.objects.get(name="دارما")
    stock_color_ids = StockBalance.objects.filter(brand=darma).values_list("color_id", flat=True)
    composition_color_ids = ProductComposition.objects.filter(
        product__brand=darma,
        product__active=True,
    ).values_list("color_id", flat=True)
    return list(
        Color.objects.filter(active=True)
        .filter(Q(id__in=stock_color_ids) | Q(id__in=composition_color_ids))
        .distinct()
        .order_by("name", "id")
    )


def _line_metrics(line):
    qty = int(line.quantity or 0)
    gross = qty * int(line.unit_price or DIA_GALLERY_UNIT_PRICE)
    cogs = qty * int(line.unit_cost or 0)
    profit = gross - cogs
    return {
        "gross": gross,
        "digikala_fee": 0,
        "cogs": cogs,
        "profit": profit,
        "shorts": qty,
        "packs": qty,
        "margin": (profit / gross * 100) if gross else 0,
    }


def dia_gallery_period_metrics(start, end):
    lines = list(
        DiaGallerySale.objects.filter(
            day__date__gte=start,
            day__date__lte=end,
            quantity__gt=0,
        ).select_related("day", "size", "color")
        .order_by("day__date", "size__sort_order", "color__name", "id")
    )
    total = {
        "gross": 0,
        "digikala_fee": 0,
        "cogs": 0,
        "profit": 0,
        "shorts": 0,
        "packs": 0,
        "margin": 0,
    }
    by_size = defaultdict(lambda: {
        "gross": 0,
        "digikala_fee": 0,
        "cogs": 0,
        "profit": 0,
        "shorts": 0,
        "packs": 0,
        "margin": 0,
    })
    color_sizes = defaultdict(lambda: defaultdict(int))
    rows = []

    for line in lines:
        metrics = _line_metrics(line)
        for key in ("gross", "digikala_fee", "cogs", "profit", "shorts", "packs"):
            total[key] += metrics[key]
            by_size[line.size.name][key] += metrics[key]
        color_sizes[line.color.name][line.size.name] += int(line.quantity or 0)
        rows.append({
            "line": line,
            "date": line.day.date,
            "size": line.size.name,
            "color": line.color.name,
            "quantity": int(line.quantity or 0),
            **metrics,
        })

    total["margin"] = (total["profit"] / total["gross"] * 100) if total["gross"] else 0
    for values in by_size.values():
        values["margin"] = (values["profit"] / values["gross"] * 100) if values["gross"] else 0

    return {
        "total": total,
        "by_size": dict(by_size),
        "color_sizes": {color: dict(values) for color, values in color_sizes.items()},
        "rows": rows,
        "line_count": len(rows),
    }


def dia_gallery_day_metrics(day):
    return dia_gallery_period_metrics(day.date, day.date)


@login_required
@require_http_methods(["GET", "POST"])
def dia_gallery_sales(request, day_id):
    day = get_object_or_404(SaleDay, id=day_id)
    sizes = _darma_sizes()
    colors = _darma_colors()

    if request.method == "POST":
        with transaction.atomic():
            existing = {
                (line.color_id, line.size_id): line
                for line in DiaGallerySale.objects.select_for_update().filter(day=day)
            }
            for color in colors:
                for size in sizes:
                    field = f"q_{color.id}_{size.id}"
                    qty = max(0, _int(request.POST.get(field)))
                    line = existing.get((color.id, size.id))
                    if line is None and qty <= 0:
                        continue
                    if line is None:
                        line = DiaGallerySale.objects.create(
                            day=day,
                            color=color,
                            size=size,
                            quantity=0,
                            unit_price=DIA_GALLERY_UNIT_PRICE,
                        )
                    line.quantity = qty
                    line.unit_price = DIA_GALLERY_UNIT_PRICE
                    line.save(update_fields=["quantity", "unit_price", "updated_at"])
                    sync_dia_gallery_sale(line)
        messages.success(request, "فروش Dia Gallery ثبت شد؛ طلب و موجودی دارما همزمان بروزرسانی شدند.")
        return redirect("dia_gallery_sales", day_id=day.id)

    existing = {
        (line.color_id, line.size_id): line
        for line in DiaGallerySale.objects.filter(day=day).select_related("color", "size")
    }
    matrix = []
    for color in colors:
        cells = []
        for size in sizes:
            line = existing.get((color.id, size.id))
            cells.append({
                "size": size,
                "field": f"q_{color.id}_{size.id}",
                "quantity": int(line.quantity or 0) if line else 0,
            })
        matrix.append({"color": color, "cells": cells})

    day_metrics = dia_gallery_day_metrics(day)
    return render(request, "core/dia_gallery_sale_v45.html", {
        "day": day,
        "sizes": sizes,
        "matrix": matrix,
        "unit_price": DIA_GALLERY_UNIT_PRICE,
        "day_metrics": day_metrics,
        "receivable": dia_gallery_receivable_total(),
    })
