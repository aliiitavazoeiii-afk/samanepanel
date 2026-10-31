from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from .anbaresh_catalog_v19 import sync_anbaresh_catalog
from .models import Brand, ProductSize, SaleDay


SALES_BRANDS = ("دارما", "تکوین", "انبارش")
BRAND_ORDER = {"دارما": 0, "تکوین": 1, "انبارش": 2}


@login_required
def sale_brand(request, day_id):
    day = get_object_or_404(SaleDay, id=day_id)

    # Anbaresh is not an inventory brand. It mirrors Darma's active manual-sale
    # catalog so the user never has to define Anbaresh products separately.
    sync_anbaresh_catalog()

    brands = list(Brand.objects.filter(active=True, name__in=SALES_BRANDS))
    brands.sort(key=lambda b: (BRAND_ORDER.get(b.name, 99), b.id))
    cards = []
    for brand in brands:
        qs = ProductSize.objects.filter(
            product__brand=brand,
            product__active=True,
            active=True,
        ).select_related("size").order_by("size__sort_order", "size__id")
        if brand.name == "تکوین":
            qs = qs.exclude(size__name__in=["3XL", "4XL"])
        first_ps = qs.first()
        cards.append({"brand": brand, "first": first_ps.size if first_ps else None})
    return render(request, "core/sale_brand_v45.html", {"day": day, "cards": cards})
