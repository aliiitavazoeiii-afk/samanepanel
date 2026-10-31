from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .models import (
    Brand, Color, InventoryModelCost, ProductComposition, Size,
    StockBalance, StockLocation,
)


def _sizes_for_brand(brand):
    qs = Size.objects.all().order_by("sort_order", "id")
    if brand and brand.name == "تکوین":
        qs = qs.exclude(name__in=["3XL", "4XL"])
    return list(qs)


def _int(value, default=0):
    try:
        if value in (None, ""):
            return default
        return int(str(value).replace(" ", "").replace(",", "").replace("٬", ""))
    except (TypeError, ValueError):
        return default


@login_required
def inventory(request):
    brands = Brand.objects.filter(active=True)
    brand = brands.filter(id=request.GET.get("brand")).first() if request.GET.get("brand") else brands.filter(name="دارما").first() or brands.first()
    sizes = _sizes_for_brand(brand)
    rows = []
    size_summaries = [{"size": size, "qty": 0, "value": 0} for size in sizes]
    grand_qty = 0
    grand_value = 0

    if brand:
        color_ids = set(StockBalance.objects.filter(brand=brand).values_list("color_id", flat=True))
        color_ids.update(ProductComposition.objects.filter(product__brand=brand).values_list("color_id", flat=True))
        colors = Color.objects.filter(active=True, id__in=color_ids).order_by("id")

        cost_map = {
            (obj.color_id, obj.size_id): int(obj.unit_cost or 0)
            for obj in InventoryModelCost.objects.filter(brand=brand, color_id__in=color_ids)
        }

        for color in colors:
            cells = []
            row_total = 0
            row_value = 0
            for index, size in enumerate(sizes):
                qs = StockBalance.objects.filter(brand=brand, size=size, color=color)
                home = qs.filter(location__key=StockLocation.HOME).aggregate(v=Sum("qty"))["v"] or 0
                kh = qs.filter(location__key=StockLocation.KHORSHID).aggregate(v=Sum("qty"))["v"] or 0
                total = home + kh
                unit_cost = cost_map.get((color.id, size.id), 0)
                capital = total * unit_cost
                cells.append({
                    "size": size,
                    "home": home,
                    "kh": kh,
                    "total": total,
                    "unit_cost": unit_cost,
                    "capital": capital,
                })
                row_total += total
                row_value += capital
                size_summaries[index]["qty"] += total
                size_summaries[index]["value"] += capital

            grand_qty += row_total
            grand_value += row_value
            rows.append({
                "color": color,
                "cells": cells,
                "row_total": row_total,
                "row_value": row_value,
            })

    return render(request, "core/inventory_final.html", {
        "brands": brands,
        "brand": brand,
        "sizes": sizes,
        "rows": rows,
        "size_summaries": size_summaries,
        "grand_qty": grand_qty,
        "grand_value": grand_value,
    })


@login_required
@require_POST
def add_color_model(request):
    name = (request.POST.get("name") or "").strip()
    code = (request.POST.get("code") or "").strip()
    unit_cost = _int(request.POST.get("unit_cost"))
    brand_id = (request.POST.get("brand") or "").strip()
    brand = Brand.objects.filter(id=brand_id).first()

    if not name:
        messages.error(request, "نام رنگ / مدل را وارد کن.")
    elif not brand:
        messages.error(request, "برند معتبر نیست.")
    elif unit_cost <= 0:
        messages.error(request, "قیمت تمام‌شده هر عدد را وارد کن.")
    else:
        color, created = Color.objects.get_or_create(name=name, defaults={"code": code, "active": True})
        changed = False
        if code and color.code != code:
            color.code = code
            changed = True
        if not color.active:
            color.active = True
            changed = True
        if changed:
            color.save(update_fields=["code", "active"])

        home = StockLocation.objects.get(key=StockLocation.HOME)
        khorshid = StockLocation.objects.get(key=StockLocation.KHORSHID)
        for size in _sizes_for_brand(brand):
            StockBalance.objects.get_or_create(
                brand=brand, size=size, color=color, location=home,
                defaults={"qty": 0},
            )
            if brand.name == "دارما":
                StockBalance.objects.get_or_create(
                    brand=brand, size=size, color=color, location=khorshid,
                    defaults={"qty": 0},
                )
            InventoryModelCost.objects.update_or_create(
                brand=brand, color=color, size=size,
                defaults={"unit_cost": unit_cost},
            )

        if created:
            messages.success(request, f"«{name}» با بهای تمام‌شده ثبت شد و به موجودی {brand.name} اضافه شد.")
        else:
            messages.info(request, f"«{name}» به موجودی {brand.name} متصل شد و قیمت تمام‌شده‌اش به‌روزرسانی شد.")

    url = reverse("inventory")
    if brand_id:
        url += f"?brand={brand_id}"
    return redirect(url)
