from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render

from .brand_colors import colors_for_brand
from .models import Brand, Color, InventoryModelCost, Size, StockBalance, StockLocation


def _int(value, default=0):
    try:
        return int(str(value or default).replace("٬", "").replace(",", "").replace(" ", ""))
    except Exception:
        return default


def _sizes_for_brand(brand):
    qs = Size.objects.all().order_by("sort_order", "id")
    if brand and brand.name == "تکوین":
        qs = qs.exclude(name__in=["3XL", "4XL"])
    return list(qs)


def _connect_color(brand, color):
    home = StockLocation.objects.get(key=StockLocation.HOME)
    khorshid = StockLocation.objects.filter(key=StockLocation.KHORSHID).first()
    for size in _sizes_for_brand(brand):
        StockBalance.objects.get_or_create(brand=brand, color=color, size=size, location=home, defaults={"qty": 0})
        if brand.name == "دارما" and khorshid:
            StockBalance.objects.get_or_create(brand=brand, color=color, size=size, location=khorshid, defaults={"qty": 0})
        InventoryModelCost.objects.get_or_create(brand=brand, color=color, size=size, defaults={"unit_cost": 0})


@login_required
@transaction.atomic
def settings_catalog(request):
    brands = Brand.objects.filter(active=True).order_by("id")
    selected_id = request.POST.get("brand") or request.GET.get("brand")
    selected_brand = brands.filter(id=selected_id).first() if selected_id else brands.filter(name="دارما").first() or brands.first()

    if request.method == "POST":
        entity = request.POST.get("entity")
        obj_id = request.POST.get("id")

        if entity == "color":
            brand = brands.filter(id=request.POST.get("brand")).first() or selected_brand
            name = (request.POST.get("name") or "").strip()
            code = (request.POST.get("code") or "").strip()
            if not brand:
                messages.error(request, "برند معتبر نیست.")
            elif not name:
                messages.error(request, "نام رنگ نمی‌تواند خالی باشد.")
            else:
                color = Color.objects.filter(id=obj_id).first() if obj_id else None
                if not color:
                    color, _ = Color.objects.get_or_create(name=name, defaults={"code": code, "active": True})
                color.name = name
                color.code = code
                color.active = bool(request.POST.get("active")) if obj_id else True
                color.save()
                _connect_color(brand, color)
                messages.success(request, f"رنگ «{color.name}» برای {brand.name} ذخیره شد.")
            return redirect(f"/settings/catalog/?brand={brand.id if brand else ''}")

        if entity == "brand":
            name = (request.POST.get("name") or "").strip()
            if name:
                obj = Brand.objects.filter(id=obj_id).first() if obj_id else None
                if obj:
                    obj.name = name
                    obj.active = bool(request.POST.get("active"))
                    obj.save()
                else:
                    Brand.objects.get_or_create(name=name, defaults={"active": True})
                messages.success(request, "برند ذخیره شد.")
            return redirect("settings_catalog")

        if entity == "size":
            name = (request.POST.get("name") or "").strip()
            order = max(0, _int(request.POST.get("sort_order")))
            if name:
                obj = Size.objects.filter(id=obj_id).first() if obj_id else None
                if obj:
                    obj.name, obj.sort_order = name, order
                    obj.save()
                else:
                    Size.objects.get_or_create(name=name, defaults={"sort_order": order})
                messages.success(request, "سایز ذخیره شد.")
            return redirect("settings_catalog")

    colors = colors_for_brand(selected_brand) if selected_brand else Color.objects.none()
    return render(request, "core/settings_catalog.html", {
        "brands": brands,
        "selected_brand": selected_brand,
        "sizes": Size.objects.all(),
        "colors": colors,
    })
