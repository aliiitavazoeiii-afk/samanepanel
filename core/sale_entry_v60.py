from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .anbaresh_catalog_v19 import sync_anbaresh_catalog
from .cost_accounting_v14 import snapshot_sale_line
from .finance_excel_v9 import sync_sale_receivable
from .models import Brand, Color, ProductSize, SaleDay, SaleLine, SaleShortage, Size
from .sale_inventory_v19 import sync_sale_inventory_v19
from .sale_price_v60 import sale_price_for


SALES_BRANDS = {"دارما", "تکوین", "انبارش"}


def _int(value, default=0):
    try:
        if value in (None, ""):
            return int(default or 0)
        return int(str(value).replace(" ", "").replace(",", "").replace("٬", "").strip())
    except (TypeError, ValueError):
        return int(default or 0)


def _brand_sizes(brand):
    qs = Size.objects.all().order_by("sort_order", "id")
    if brand.name == "تکوین":
        qs = qs.exclude(name__in=["3XL", "4XL"])
    return list(qs)


@login_required
def sale_size(request, day_id, brand_id, size_id):
    day = get_object_or_404(SaleDay, id=day_id)
    brand = get_object_or_404(Brand, id=brand_id)
    if brand.name not in SALES_BRANDS:
        return redirect("sale_brand", day_id=day.id)
    if brand.name == "انبارش":
        sync_anbaresh_catalog()

    size = get_object_or_404(Size, id=size_id)
    sizes = _brand_sizes(brand)
    ids = [s.id for s in sizes]
    if size.id not in ids:
        return redirect("sale_brand", day_id=day.id)

    product_sizes = list(
        ProductSize.objects.filter(
            product__brand=brand,
            size=size,
            active=True,
            product__active=True,
        )
        .select_related("product__brand", "product", "size")
        .prefetch_related("product__composition__color")
        .order_by("product__code")
    )
    rows = []
    for ps in product_sizes:
        line = SaleLine.objects.filter(day=day, product_size=ps).first()
        if brand.name in {"دارما", "تکوین"}:
            # Presentation-only in-memory override. ProductSize is never saved here.
            # Existing SaleLine.sale_price remains authoritative once a row exists.
            ps.default_sale_price = int(sale_price_for(ps, day.date))
        rows.append((ps, line))

    idx = ids.index(size.id)
    prev_size = sizes[idx - 1] if idx > 0 else None
    next_size = sizes[idx + 1] if idx < len(sizes) - 1 else None
    return render(
        request,
        "core/sale_size.html",
        {
            "day": day,
            "brand": brand,
            "size": size,
            "rows": rows,
            "sizes": sizes,
            "prev_size": prev_size,
            "next_size": next_size,
        },
    )


@login_required
@require_POST
@transaction.atomic
def sale_line_save(request):
    day = get_object_or_404(SaleDay, id=request.POST.get("day_id"))
    ps = get_object_or_404(
        ProductSize.objects.select_related("product__brand", "size"),
        id=request.POST.get("product_size_id"),
    )
    if ps.product.brand.name == "تکوین" and ps.size.name in ("3XL", "4XL"):
        return HttpResponse("این سایز برای تکوین فعال نیست.", status=400)
    if ps.product.brand.name == "Novani":
        return HttpResponse("Novani برند موجودی/تولید است و در فروش روزانه ثبت نمی‌شود.", status=400)

    qty = max(0, _int(request.POST.get("quantity")))
    default_price = int(sale_price_for(ps, day.date))
    price = max(0, _int(request.POST.get("sale_price"), default_price))
    line, _ = SaleLine.objects.select_for_update().get_or_create(
        day=day,
        product_size=ps,
        defaults={"quantity": 0, "sale_price": price},
    )
    line.quantity = qty
    line.sale_price = price
    line.save(update_fields=["quantity", "sale_price"])

    result = sync_sale_inventory_v19(line)
    snapshot_sale_line(line, ps, price)
    sync_sale_receivable(line)
    pending = list(line.shortages.filter(resolved=False).select_related("source_color"))
    return render(
        request,
        "core/_sale_saved_final.html",
        {
            "line": line,
            "pending": pending,
            "colors": Color.objects.filter(active=True),
            "result": result,
        },
    )


# Kept here only as an optional compatibility target if the route is ever moved.
# Current V60 leaves shortage_resolve on excel_sales because an existing line's
# frozen sale_price is already the exact value that must be retained.
@login_required
@require_POST
@transaction.atomic
def shortage_resolve(request, shortage_id):
    shortage = get_object_or_404(
        SaleShortage.objects.select_for_update().select_related(
            "sale_line__product_size__product__brand", "sale_line__product_size__size"
        ),
        id=shortage_id,
    )
    choice = request.POST.get("target_color")
    keep_negative = choice == "none"
    target = None
    if choice and choice != "none":
        target = get_object_or_404(Color, id=choice)
    shortage.resolved = True
    shortage.target_color = None if keep_negative else target
    shortage.save(update_fields=["resolved", "target_color"])
    line = shortage.sale_line
    result = sync_sale_inventory_v19(line)
    snapshot_sale_line(line, line.product_size, line.sale_price)
    sync_sale_receivable(line)
    pending = list(line.shortages.filter(resolved=False).select_related("source_color"))
    return render(
        request,
        "core/_sale_saved_final.html",
        {"line": line, "pending": pending, "colors": Color.objects.filter(active=True), "result": result},
    )
