from collections import defaultdict
from datetime import date

import jdatetime
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .anbaresh_catalog_v19 import sync_anbaresh_catalog
from .dateutils import format_jalali
from .finance import sale_line_metrics
from .jalali_calendar import jalali_month_data
from .models import Brand, ProductSize, SaleDay, SaleLine, Size


SALES_BRANDS = {"دارما", "تکوین", "انبارش"}


def _brand_sizes(brand):
    qs = Size.objects.all().order_by("sort_order", "id")
    if brand.name == "تکوین":
        qs = qs.exclude(name__in=["3XL", "4XL"])
    return list(qs)


@login_required
def sale_calendar(request):
    today_j = jdatetime.date.fromgregorian(date=date.today())
    try:
        jy = int(request.GET.get("jy", today_j.year))
        jm = int(request.GET.get("jm", today_j.month))
        if not 1 <= jm <= 12:
            raise ValueError
    except (TypeError, ValueError):
        jy, jm = today_j.year, today_j.month

    cal = jalali_month_data(jy, jm)
    existing = {
        d.date: d
        for d in SaleDay.objects.filter(date__gte=cal["first_g"], date__lt=cal["next_g"]).prefetch_related("lines", "dia_gallery_sales")
    }
    for week in cal["weeks"]:
        for cell in week:
            if not cell:
                continue
            g = jdatetime.date(jy, jm, cell["day"]).togregorian()
            sale_day = existing.get(g)
            normal_sales = bool(sale_day and any(line.quantity > 0 for line in sale_day.lines.all()))
            dia_sales = bool(sale_day and any(line.quantity > 0 for line in sale_day.dia_gallery_sales.all()))
            cell["has_sales"] = normal_sales or dia_sales
            cell["sale_day"] = sale_day

    return render(request, "core/sale_calendar.html", {
        "jy": jy,
        "jm": jm,
        "month_name": cal["month_name"],
        "weekdays": cal["weekdays"],
        "weeks": cal["weeks"],
        "prev_y": cal["prev_y"],
        "prev_m": cal["prev_m"],
        "next_y": cal["next_y"],
        "next_m": cal["next_m"],
    })


@login_required
def select_sale_day(request, jy, jm, jd):
    g = jdatetime.date(jy, jm, jd).togregorian()
    day, _ = SaleDay.objects.get_or_create(date=g)
    if day.lines.filter(quantity__gt=0).exists() or day.dia_gallery_sales.filter(quantity__gt=0).exists():
        return redirect("daily_report", day_id=day.id)
    return redirect("sale_brand", day_id=day.id)


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

    product_sizes = ProductSize.objects.filter(
        product__brand=brand, size=size, active=True, product__active=True
    ).select_related("product", "size").order_by("product__code")
    rows = []
    for ps in product_sizes:
        line = SaleLine.objects.filter(day=day, product_size=ps).first()
        rows.append((ps, line))

    idx = ids.index(size.id)
    prev_size = sizes[idx - 1] if idx > 0 else None
    next_size = sizes[idx + 1] if idx < len(sizes) - 1 else None
    return render(request, "core/sale_size.html", {
        "day": day, "brand": brand, "size": size, "rows": rows,
        "sizes": sizes, "prev_size": prev_size, "next_size": next_size,
    })


@login_required
def daily_report(request, day_id):
    day = get_object_or_404(SaleDay, id=day_id)
    lines = list(
        SaleLine.objects.filter(day=day, quantity__gt=0)
        .select_related("product_size__product__brand", "product_size__size")
        .order_by("product_size__product__brand__name", "product_size__size__sort_order", "product_size__product__code")
    )

    by_brand = defaultdict(lambda: {
        "gross": 0, "digikala_fee": 0, "cogs": 0, "profit": 0,
        "shorts": 0, "packs": 0, "margin": 0,
    })
    total = {"gross": 0, "digikala_fee": 0, "cogs": 0, "profit": 0, "shorts": 0, "packs": 0, "margin": 0}
    detail_rows = []

    for line in lines:
        m = sale_line_metrics(line)
        brand_name = line.product_size.product.brand.name
        for key in ["gross", "digikala_fee", "cogs", "profit", "shorts", "packs"]:
            by_brand[brand_name][key] += m[key]
            total[key] += m[key]
        detail_rows.append({"line": line, **m})

    for values in by_brand.values():
        values["margin"] = (values["profit"] / values["gross"] * 100) if values["gross"] else 0
    total["margin"] = (total["profit"] / total["gross"] * 100) if total["gross"] else 0

    ordered_brands = []
    for brand_name in ["تکوین", "دارما", "انبارش"]:
        if brand_name in by_brand:
            ordered_brands.append((brand_name, by_brand[brand_name]))
    for brand_name, values in by_brand.items():
        if brand_name not in ["تکوین", "دارما", "انبارش"]:
            ordered_brands.append((brand_name, values))

    return render(request, "core/daily_report.html", {
        "day": day,
        "jalali_date": format_jalali(day.date),
        "detail_rows": detail_rows,
        "by_brand": ordered_brands,
        "total": total,
    })
