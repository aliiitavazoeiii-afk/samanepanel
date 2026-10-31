from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render

from .brand_colors import colors_for_brand
from .models import Brand, Size, StockBalance, StockLocation, StockThreshold


def _int(value, default=0):
    try:
        return int(str(value if value not in (None, "") else default).replace("٬", "").replace(",", "").replace(" ", ""))
    except Exception:
        return default


def _sizes_for_brand(brand):
    qs = Size.objects.all().order_by("sort_order", "id")
    if brand and brand.name == "تکوین":
        qs = qs.exclude(name__in=["3XL", "4XL"])
    return list(qs)


@login_required
def settings_stock(request):
    brands = Brand.objects.filter(active=True)
    brand_id = request.GET.get("brand") or request.POST.get("brand")
    brand = brands.filter(id=brand_id).first() if brand_id else brands.filter(name="دارما").first() or brands.first()
    sizes = _sizes_for_brand(brand) if brand else []
    colors = list(colors_for_brand(brand)) if brand else []
    home = StockLocation.objects.get(key=StockLocation.HOME)
    khorshid = StockLocation.objects.filter(key=StockLocation.KHORSHID).first()

    if request.method == "POST" and brand:
        with transaction.atomic():
            for color in colors:
                for size in sizes:
                    home_qty = _int(request.POST.get(f"home_{color.id}_{size.id}"))
                    kh_qty = 0 if brand.name == "تکوین" else _int(request.POST.get(f"kh_{color.id}_{size.id}"))
                    StockBalance.objects.update_or_create(brand=brand, size=size, color=color, location=home, defaults={"qty": home_qty})
                    if brand.name == "دارما" and khorshid:
                        StockBalance.objects.update_or_create(brand=brand, size=size, color=color, location=khorshid, defaults={"qty": kh_qty})
                    StockThreshold.objects.update_or_create(
                        brand=brand, size=size, color=color,
                        defaults={
                            "home_min": max(0, _int(request.POST.get(f"home_min_{color.id}_{size.id}"))),
                            "total_min": max(0, _int(request.POST.get(f"total_min_{color.id}_{size.id}"))),
                        },
                    )
        messages.success(request, f"موجودی و حداقل‌های {brand.name} ذخیره شد.")
        return redirect(f"/settings/stock/?brand={brand.id}")

    rows = []
    for color in colors:
        cells = []
        for size in sizes:
            balances = StockBalance.objects.filter(brand=brand, color=color, size=size)
            h = balances.filter(location=home).first()
            k = balances.filter(location=khorshid).first() if khorshid else None
            t = StockThreshold.objects.filter(brand=brand, color=color, size=size).first()
            cells.append({"size": size, "home": h.qty if h else 0, "kh": k.qty if k else 0, "home_min": t.home_min if t else 0, "total_min": t.total_min if t else 0})
        rows.append({"color": color, "cells": cells})
    return render(request, "core/settings_stock.html", {"brands": brands, "brand": brand, "sizes": sizes, "rows": rows})
