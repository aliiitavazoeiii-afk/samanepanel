from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import render, redirect

from .models import (
    Brand, Color, InventoryModelCost, Size, StockBalance, StockLocation,
)


def _to_int(value, default=0):
    try:
        if value in (None, ""):
            return default
        return int(str(value).replace("٬", "").replace(",", "").replace(" ", ""))
    except (TypeError, ValueError):
        return default


def _sizes_for_brand(brand):
    qs = Size.objects.all().order_by("sort_order", "id")
    if brand and brand.name == "تکوین":
        qs = qs.exclude(name__in=["3XL", "4XL"])
    return list(qs)


def _connect_color_to_brand(color, brand):
    home = StockLocation.objects.filter(key=StockLocation.HOME).first()
    khorshid = StockLocation.objects.filter(key=StockLocation.KHORSHID).first()
    if not home:
        return
    for size in _sizes_for_brand(brand):
        StockBalance.objects.get_or_create(
            brand=brand, size=size, color=color, location=home,
            defaults={"qty": 0},
        )
        if brand.name == "دارما" and khorshid:
            StockBalance.objects.get_or_create(
                brand=brand, size=size, color=color, location=khorshid,
                defaults={"qty": 0},
            )
        InventoryModelCost.objects.get_or_create(
            brand=brand, color=color, size=size,
            defaults={"unit_cost": 0},
        )


@login_required
@transaction.atomic
def settings_catalog(request):
    brands_qs = Brand.objects.all().order_by("id")
    active_brands = Brand.objects.filter(active=True).order_by("id")
    default_brand = active_brands.filter(name="دارما").first() or active_brands.first()

    if request.method == "POST":
        entity = request.POST.get("entity")
        obj_id = request.POST.get("id")

        if entity == "color":
            name = (request.POST.get("name") or "").strip()
            code = (request.POST.get("code") or "").strip()
            brand = active_brands.filter(id=request.POST.get("brand")).first() or default_brand
            if not name:
                messages.error(request, "نام رنگ نمی‌تواند خالی باشد.")
            elif not brand:
                messages.error(request, "اول یک برند فعال تعریف کن.")
            else:
                obj = Color.objects.filter(id=obj_id).first() if obj_id else None
                if obj:
                    obj.name = name
                    obj.code = code
                    obj.active = bool(request.POST.get("active"))
                    obj.save()
                    if request.POST.get("brand"):
                        _connect_color_to_brand(obj, brand)
                    messages.success(request, "رنگ ویرایش شد.")
                else:
                    color, created = Color.objects.get_or_create(
                        name=name,
                        defaults={"code": code, "active": True},
                    )
                    changed = False
                    if code and color.code != code:
                        color.code = code
                        changed = True
                    if not color.active:
                        color.active = True
                        changed = True
                    if changed:
                        color.save(update_fields=["code", "active"])
                    _connect_color_to_brand(color, brand)
                    if created:
                        messages.success(request, f"رنگ «{name}» به {brand.name}، موجودی کالا و لیست رنگ پارچه اضافه شد.")
                    else:
                        messages.success(request, f"رنگ «{name}» به موجودی {brand.name} متصل شد.")

        elif entity == "brand":
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

        elif entity == "size":
            name = (request.POST.get("name") or "").strip()
            order = max(0, _to_int(request.POST.get("sort_order")))
            if name:
                obj = Size.objects.filter(id=obj_id).first() if obj_id else None
                if obj:
                    obj.name = name
                    obj.sort_order = order
                    obj.save()
                else:
                    Size.objects.get_or_create(name=name, defaults={"sort_order": order})
                messages.success(request, "سایز ذخیره شد.")

        return redirect("settings_catalog")

    return render(request, "core/settings_catalog.html", {
        "brands": brands_qs,
        "active_brands": active_brands,
        "default_brand_id": default_brand.id if default_brand else None,
        "sizes": Size.objects.all(),
        "colors": Color.objects.all().order_by("id"),
    })
