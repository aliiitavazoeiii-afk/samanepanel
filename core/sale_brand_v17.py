from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from .models import Brand, ProductSize, SaleDay


BRAND_ORDER = {"دارما": 0, "تکوین": 1, "انبارش": 2}


@login_required
def sale_brand(request, day_id):
    day = get_object_or_404(SaleDay, id=day_id)
    brands = list(Brand.objects.filter(active=True))
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
    return render(request, "core/sale_brand_final.html", {"day": day, "cards": cards})
