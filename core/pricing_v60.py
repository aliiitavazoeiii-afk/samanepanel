from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render

from .darma_cost_v55 import darma_cost_for
from .darma_pricing import DEFAULT_GROUP_PRICES, SIZE_NAMES, get_group_prices
from .dateutils import format_jalali, parse_jalali_date
from .models import Brand, ProductCode, ProductSize, Size
from .sale_price_v60 import next_sale_price_rule, sale_price_for, set_sale_price_rule


def _int(value):
    try:
        return int(str(value or 0).replace("٬", "").replace(",", "").replace(" ", "").strip())
    except Exception:
        return 0


def _tomorrow():
    return date.today() + timedelta(days=1)


def _representative_ps(pack_qty, size_name):
    return (
        ProductSize.objects.filter(
            product__brand__name="دارما",
            product__pack_qty=int(pack_qty),
            product__active=True,
            active=True,
            size__name=size_name,
        )
        .select_related("product__brand", "size")
        .order_by("product__code", "id")
        .first()
    )


def _pricing_rows():
    rows = []
    for pack_qty in sorted(DEFAULT_GROUP_PRICES):
        legacy = get_group_prices(pack_qty)
        prices = []
        future_dates = []
        for size_name in SIZE_NAMES:
            ps = _representative_ps(pack_qty, size_name)
            if ps:
                nxt = next_sale_price_rule(ps)
                if nxt:
                    value = int(nxt["price"])
                    future_dates.append(nxt["effective_from"])
                else:
                    value = int(sale_price_for(ps, date.today()))
            else:
                value = int(legacy.get(size_name, DEFAULT_GROUP_PRICES[pack_qty][size_name]) or 0)
            prices.append({"size": size_name, "value": value})
        rows.append(
            {
                "pack_qty": pack_qty,
                "prices": prices,
                "product_count": ProductCode.objects.filter(
                    brand__name="دارما", pack_qty=pack_qty, active=True
                ).count(),
                "effective_j": format_jalali(min(future_dates) if future_dates else _tomorrow()),
            }
        )
    return rows


def _schedule_group_prices(pack_qty, effective_from, prices):
    if pack_qty not in DEFAULT_GROUP_PRICES:
        raise ValueError("پک انتخاب‌شده معتبر نیست.")
    if effective_from < date.today():
        raise ValueError("تاریخ شروع قیمت فروش نمی‌تواند قبل از امروز باشد.")

    cleaned = {}
    for size_name in SIZE_NAMES:
        value = int(prices.get(size_name, 0) or 0)
        if value <= 0:
            raise ValueError(f"قیمت {size_name} باید بیشتر از صفر باشد.")
        cleaned[size_name] = value

    brand = Brand.objects.get(name="دارما")
    sizes = {row.name: row for row in Size.objects.filter(name__in=SIZE_NAMES)}
    products = list(ProductCode.objects.filter(brand=brand, pack_qty=pack_qty, active=True))
    legacy = get_group_prices(pack_qty)
    current_cost = int(darma_cost_for())
    scheduled_rows = 0

    for product in products:
        for size_name in SIZE_NAMES:
            size = sizes.get(size_name)
            if not size:
                continue
            ps = ProductSize.objects.filter(product=product, size=size).first()
            if ps is None:
                fallback = int(legacy.get(size_name, 0) or 0)
                if fallback <= 0:
                    fallback = cleaned[size_name]
                ps = ProductSize.objects.create(
                    product=product,
                    size=size,
                    default_sale_price=fallback,
                    unit_cost=current_cost,
                    active=True,
                )
            else:
                ps.active = True
                ps.unit_cost = current_cost
                ps.save(update_fields=["active", "unit_cost"])
            set_sale_price_rule(ps, effective_from, cleaned[size_name])
            scheduled_rows += 1

    return {"products": len(products), "rows": scheduled_rows}


@login_required
@transaction.atomic
def settings_products(request):
    if request.method == "POST" and request.POST.get("action") == "bulk_darma_prices":
        try:
            pack_qty = _int(request.POST.get("pack_qty"))
            effective_from = parse_jalali_date(
                request.POST.get("effective_from") or format_jalali(_tomorrow())
            )
            prices = {size_name: _int(request.POST.get(f"price_{size_name}")) for size_name in SIZE_NAMES}
            result = _schedule_group_prices(pack_qty, effective_from, prices)
            messages.success(
                request,
                f"قیمت پک {pack_qty} تایی برای {result['products']} کد دارما از تاریخ "
                f"{format_jalali(effective_from)} زمان‌بندی شد. قیمت روزهای قبل از این تاریخ تغییر نمی‌کند.",
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
    return render(
        request,
        "core/settings_products_v60.html",
        {
            "products": products,
            "pricing_rows": _pricing_rows(),
            "pricing_sizes": SIZE_NAMES,
            "bulk_effective_j": format_jalali(_tomorrow()),
        },
    )
