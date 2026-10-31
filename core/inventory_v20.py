from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .brand_colors import colors_for_brand, norm
from .darma_cost_v55 import darma_cost_for
from .models import Brand, Color, InventoryModelCost, Size, StockBalance, StockLocation
from .novani_cost_v59 import novani_cost_for
from .takvin_pricing_v17 import takvin_cost_for

INVENTORY_BRANDS = ("دارما", "تکوین", "Novani")
BRAND_ORDER = {"دارما": 0, "تکوین": 1, "Novani": 2}
SIZE_NAMES = {
    "دارما": ["M", "L", "XL", "XXL", "3XL", "4XL"],
    "تکوین": ["M", "L", "XL", "XXL"],
    "Novani": ["S", "M", "L", "XL", "XXL", "3XL"],
}


# V52 is presentation-only. These colors/models are intentionally excluded from
# low-stock highlighting at the user's request. norm() makes Persian spacing/ZWNJ
# variants equivalent, while the keyword pairs cover reversed naming order such as
# «مشکی کبریتی» / «کبریتی مشکی».
def _inventory_alert_exempt(color_name):
    value = norm(color_name)
    if value in {norm("زرد"), norm("قرمز")}:
        return True
    if "خرسی" in value or "پلنگی" in value:
        return True
    if "کبریتی" in value and "مشکی" in value:
        return True
    if norm("راه راه") in value and norm("سرمه ای") in value:
        return True
    return False


def _inventory_alert_level(qty, *, exempt=False):
    """V123 unified, intentionally sparse thresholds for each physical stock cell.

    0 = strong red; 1..9 (and exceptional negative stock) = soft red;
    10+ = normal. The user's latest universal rule supersedes the old
    model exclusions for display only; the signature remains compatible.
    """
    qty = int(qty)
    if qty == 0:
        return "red"
    if qty < 10:
        return "orange"
    return ""


def _home_alert_level(qty, *, exempt=False):
    return _inventory_alert_level(qty, exempt=exempt)


def _total_alert_level(qty, *, exempt=False):
    return _inventory_alert_level(qty, exempt=exempt)


def _sizes_for_brand(brand):
    if not brand:
        return []
    names = SIZE_NAMES.get(brand.name, [])
    by_name = {s.name: s for s in Size.objects.filter(name__in=names)}
    return [by_name[name] for name in names if name in by_name]


def _int(value, default=0):
    try:
        if value in (None, ""):
            return default
        return int(str(value).replace(" ", "").replace(",", "").replace("٬", ""))
    except (TypeError, ValueError):
        return default


def _inventory_unit_cost(
    brand,
    size,
    color,
    cost_map=None,
    darma_current_cost=None,
    novani_current_cost=None,
):
    """Return the accounting value used by the inventory page for one unit."""
    if brand.name == "دارما":
        return int(darma_current_cost if darma_current_cost is not None else darma_cost_for())
    if brand.name == "Novani":
        return int(novani_current_cost if novani_current_cost is not None else novani_cost_for())
    if brand.name == "تکوین":
        return int(takvin_cost_for(size))
    return int((cost_map or {}).get((color.id, size.id), 0) or 0)


@login_required
def inventory(request):
    brands = list(Brand.objects.filter(active=True, name__in=INVENTORY_BRANDS))
    brands.sort(key=lambda b: (BRAND_ORDER.get(b.name, 99), b.id))
    brand_ids = {b.id for b in brands}
    requested = _int(request.GET.get("brand"))
    brand = next((b for b in brands if b.id == requested), None) if requested else None
    if brand is None:
        brand = next((b for b in brands if b.name == "دارما"), None) or (brands[0] if brands else None)

    sizes = _sizes_for_brand(brand)
    rows = []
    size_summaries = [{"size": size, "qty": 0, "value": 0} for size in sizes]
    grand_qty = 0
    grand_value = 0
    darma_current_cost = int(darma_cost_for()) if brand and brand.name == "دارما" else None
    novani_current_cost = int(novani_cost_for()) if brand and brand.name == "Novani" else None

    if brand and brand.id in brand_ids:
        colors = colors_for_brand(brand)
        color_ids = list(colors.values_list("id", flat=True))
        # Darma and Novani each have one central accounting cost. Keep the legacy
        # color/size map only for brands whose valuation still depends on it.
        cost_map = {}
        if brand.name not in {"دارما", "Novani"}:
            cost_map = {
                (obj.color_id, obj.size_id): int(obj.unit_cost or 0)
                for obj in InventoryModelCost.objects.filter(brand=brand, color_id__in=color_ids)
            }
        for color in colors:
            cells = []
            row_total = 0
            row_value = 0
            alert_exempt = _inventory_alert_exempt(color.name)
            for index, size in enumerate(sizes):
                qs = StockBalance.objects.filter(brand=brand, size=size, color=color)
                home = int(qs.filter(location__key=StockLocation.HOME).aggregate(v=Sum("qty"))["v"] or 0)
                kh = int(qs.filter(location__key=StockLocation.KHORSHID).aggregate(v=Sum("qty"))["v"] or 0)
                if brand.name == "Novani":
                    kh = 0
                total = home + kh
                unit_cost = _inventory_unit_cost(
                    brand,
                    size,
                    color,
                    cost_map=cost_map,
                    darma_current_cost=darma_current_cost,
                    novani_current_cost=novani_current_cost,
                )
                capital = total * unit_cost
                cells.append({
                    "size": size,
                    "home": home,
                    "kh": kh,
                    "total": total,
                    "unit_cost": unit_cost,
                    "capital": capital,
                    "home_alert": _home_alert_level(home, exempt=alert_exempt),
                    "total_alert": _total_alert_level(total, exempt=alert_exempt),
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
                "alert_exempt": alert_exempt,
            })

    return render(request, "core/inventory_v19.html", {
        "brands": brands,
        "brand": brand,
        "sizes": sizes,
        "rows": rows,
        "size_summaries": size_summaries,
        "grand_qty": grand_qty,
        "grand_value": grand_value,
        "darma_current_cost": darma_current_cost,
        "novani_current_cost": novani_current_cost,
        "single_table": bool(brand and brand.name == "Novani"),
    })


@login_required
@require_POST
def add_color_model(request):
    name = (request.POST.get("name") or "").strip()
    code = (request.POST.get("code") or "").strip()
    requested_unit_cost = _int(request.POST.get("unit_cost"))
    brand = Brand.objects.filter(id=request.POST.get("brand"), name__in=INVENTORY_BRANDS).first()
    if brand and brand.name == "دارما":
        unit_cost = int(darma_cost_for())
    elif brand and brand.name == "Novani":
        unit_cost = int(novani_cost_for())
    else:
        unit_cost = requested_unit_cost

    if not name:
        messages.error(request, "نام رنگ / مدل را وارد کن.")
    elif not brand:
        messages.error(request, "برند موجودی معتبر نیست.")
    elif brand.name not in {"دارما", "Novani"} and unit_cost <= 0:
        messages.error(request, "قیمت تمام‌شده هر عدد را وارد کن.")
    else:
        color, _ = Color.objects.get_or_create(name=name, defaults={"code": code, "active": True})
        if code:
            color.code = code
        color.active = True
        color.save()
        home = StockLocation.objects.get(key=StockLocation.HOME)
        khorshid = StockLocation.objects.filter(key=StockLocation.KHORSHID).first()
        for size in _sizes_for_brand(brand):
            StockBalance.objects.get_or_create(
                brand=brand,
                size=size,
                color=color,
                location=home,
                defaults={"qty": 0},
            )
            if brand.name == "دارما" and khorshid:
                StockBalance.objects.get_or_create(
                    brand=brand,
                    size=size,
                    color=color,
                    location=khorshid,
                    defaults={"qty": 0},
                )
            if brand.name not in {"دارما", "Novani"}:
                InventoryModelCost.objects.update_or_create(
                    brand=brand,
                    color=color,
                    size=size,
                    defaults={"unit_cost": unit_cost},
                )
        if brand.name in {"دارما", "Novani"}:
            messages.success(
                request,
                f"«{name}» به موجودی {brand.name} اضافه شد؛ بهای تمام‌شده از نرخ مرکزی {unit_cost:,} تومان خوانده می‌شود.",
            )
        else:
            messages.success(request, f"«{name}» فقط به کاتالوگ موجودی {brand.name} اضافه شد.")
    url = reverse("inventory_stock")
    if brand:
        url += f"?brand={brand.id}"
    return redirect(url)
