from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render

from .darma_pricing import DEFAULT_GROUP_PRICES, SIZE_NAMES, apply_group_prices, get_group_prices, save_group_prices
from .models import ProductCode


def _int(value):
    try:
        return int(str(value or 0).replace("٬", "").replace(",", "").replace(" ", "").strip())
    except Exception:
        return 0


def _pricing_rows():
    rows = []
    for pack_qty in sorted(DEFAULT_GROUP_PRICES):
        prices = get_group_prices(pack_qty)
        rows.append({
            "pack_qty": pack_qty,
            "prices": [{"size": size, "value": prices[size]} for size in SIZE_NAMES],
            "product_count": ProductCode.objects.filter(brand__name="دارما", pack_qty=pack_qty, active=True).count(),
        })
    return rows


@login_required
@transaction.atomic
def settings_products(request):
    if request.method == "POST" and request.POST.get("action") == "bulk_darma_prices":
        try:
            pack_qty = _int(request.POST.get("pack_qty"))
            if pack_qty not in DEFAULT_GROUP_PRICES:
                raise ValueError("پک انتخاب‌شده معتبر نیست.")
            prices = {}
            for size_name in SIZE_NAMES:
                prices[size_name] = _int(request.POST.get(f"price_{size_name}"))
            prices = save_group_prices(pack_qty, prices)
            result = apply_group_prices(pack_qty, prices)
            messages.success(
                request,
                f"قیمت پک {pack_qty} تایی ذخیره شد و روی {result['products']} کد دارما اعمال شد.",
            )
        except Exception as exc:
            messages.error(request, str(exc))
        return redirect("settings_products")

    products = (
        ProductCode.objects.select_related("brand")
        .prefetch_related("composition__color", "sizes__size")
        .all()
        .order_by("brand__name", "code")
    )
    return render(request, "core/settings_products.html", {
        "products": products,
        "pricing_rows": _pricing_rows(),
        "pricing_sizes": SIZE_NAMES,
    })
