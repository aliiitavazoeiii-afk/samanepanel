from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .darma_cost_v55 import darma_cost_for
from .excel_views import _int
from .finance import digikala_fee_for_unit
from .models import ProductSize
from .sale_price_v60 import sale_price_for
from .takvin_pricing_v17 import takvin_cost_for


TARGET_BRANDS = ("دارما", "تکوین")


def _percent(value):
    text = str(value or "").strip()
    if not text:
        return None
    text = (
        text.replace("٪", "")
        .replace("٫", ".")
        .replace(",", ".")
        .replace(" ", "")
    )
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if value < 0 or value >= 100:
        return None
    return value


def _round_half_up(value):
    return int(Decimal(value or 0).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _solve_sale_price(cost, target_margin_on_sale):
    """Minimum whole-toman sale price for a requested net margin on sale.

    Target percentage means:
        net profit / sale price * 100

    Condition:
        price - canonical Digikala fee(price) - cost >= price * target_margin
    """
    cost = max(0, int(cost or 0))
    if cost <= 0:
        return 0

    margin = Decimal(target_margin_on_sale) / Decimal(100)

    def surplus(price):
        price = int(price)
        fee = int(digikala_fee_for_unit(price, date.today()))
        profit = Decimal(price - fee - cost)
        target_profit = Decimal(price) * margin
        return profit - target_profit

    lo = 0
    hi = max(100_000, cost * 2)
    while surplus(hi) < 0:
        hi *= 2
        if hi > 100_000_000_000:
            raise ValueError("با این درصد سود و ساختار فعلی کارمزد دیجی‌کالا قیمت قابل‌دستیابی پیدا نشد.")

    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if surplus(mid) >= 0:
            hi = mid
        else:
            lo = mid
    return int(hi)


def _rounded_up(value, step=1000):
    value = int(value or 0)
    return ((value + step - 1) // step) * step if value > 0 else 0


def _size_profitability_rows():
    today = date.today()
    rows = list(
        ProductSize.objects.filter(
            product__brand__name__in=TARGET_BRANDS,
            product__active=True,
            active=True,
        )
        .select_related("product__brand", "product", "size")
        .order_by("product__brand__name", "product__code", "size__sort_order", "id")
    )

    result = []
    for ps in rows:
        brand = ps.product.brand.name
        pack_qty = int(ps.product.pack_qty or 0)
        sale_price = int(sale_price_for(ps, today) or 0)

        if brand == "دارما":
            unit_cost = int(darma_cost_for(today) or 0)
        else:
            unit_cost = int(takvin_cost_for(ps.size.name, today) or 0)

        finished_cost = pack_qty * unit_cost
        fee = int(digikala_fee_for_unit(sale_price, today)) if sale_price > 0 else 0
        profit = sale_price - fee - finished_cost if sale_price > 0 else 0
        margin_on_sale = (profit * 100 / sale_price) if sale_price else 0
        profit_on_cost = (profit * 100 / finished_cost) if finished_cost else 0

        result.append({
            "ps_id": ps.id,
            "product_id": ps.product_id,
            "brand": brand,
            "code": ps.product.code,
            "size": ps.size.name,
            "size_order": int(ps.size.sort_order or 0),
            "pack_qty": pack_qty,
            "sale_price": sale_price,
            "unit_cost": unit_cost,
            "finished_cost": finished_cost,
            "fee": fee,
            "profit": profit,
            "margin_on_sale": margin_on_sale,
            "profit_on_cost": profit_on_cost,
        })
    return result


def _mean_int(rows, key):
    if not rows:
        return 0
    return _round_half_up(
        sum(Decimal(int(row[key] or 0)) for row in rows) / Decimal(len(rows))
    )


def _mean_decimal(rows, key):
    if not rows:
        return 0
    return float(
        sum(Decimal(str(row[key] or 0)) for row in rows) / Decimal(len(rows))
    )


def _profitability_sections():
    size_rows = _size_profitability_rows()
    grouped = {brand: {} for brand in TARGET_BRANDS}

    for row in size_rows:
        key = int(row["product_id"])
        grouped[row["brand"]].setdefault(key, []).append(row)

    sections = []
    for brand in TARGET_BRANDS:
        codes = []
        for product_rows in grouped[brand].values():
            product_rows.sort(key=lambda row: (row["size_order"], row["ps_id"]))
            first = product_rows[0]
            codes.append({
                "product_id": first["product_id"],
                "brand": brand,
                "code": first["code"],
                "pack_qty": first["pack_qty"],
                "size_count": len(product_rows),
                "avg_sale_price": _mean_int(product_rows, "sale_price"),
                "avg_finished_cost": _mean_int(product_rows, "finished_cost"),
                "avg_fee": _mean_int(product_rows, "fee"),
                "avg_profit": _mean_int(product_rows, "profit"),
                "avg_margin_on_sale": _mean_decimal(product_rows, "margin_on_sale"),
                "avg_profit_on_cost": _mean_decimal(product_rows, "profit_on_cost"),
                "sizes": product_rows,
            })

        codes.sort(key=lambda row: str(row["code"]))
        sections.append({
            "brand": brand,
            "codes": codes,
            "code_count": len(codes),
            "size_count": sum(code["size_count"] for code in codes),
        })
    return sections


@login_required
def calculator(request):
    return render(
        request,
        "core/calculator_v37.html",
        {"profitability_sections": _profitability_sections()},
    )


@login_required
def calculator_quote(request):
    sale_price = _int(request.GET.get("sale_price"))
    cost = _int(request.GET.get("cost"))
    if sale_price <= 0 or cost <= 0:
        return render(
            request,
            "core/_calculator_result_v104.html",
            {"error": "قیمت فروش و قیمت تمام‌شده را کامل وارد کن."},
        )

    fee = int(digikala_fee_for_unit(sale_price, date.today()))
    profit = sale_price - fee - cost
    return render(request, "core/_calculator_result_v104.html", {
        "sale_price": sale_price,
        "cost": cost,
        "fee": fee,
        "profit": profit,
        "profit_on_sale": (profit * 100 / sale_price) if sale_price else 0,
        "profit_on_cost": (profit * 100 / cost) if cost else 0,
    })


@login_required
def calculator_target_quote(request):
    cost = _int(request.GET.get("cost"))
    target_percent = _percent(request.GET.get("target_profit_percent"))
    if cost <= 0:
        return render(
            request,
            "core/_calculator_target_result_v104.html",
            {"error": "قیمت تمام‌شده کالا را وارد کن."},
        )
    if target_percent is None:
        return render(
            request,
            "core/_calculator_target_result_v104.html",
            {"error": "حاشیه سود هدف را به‌صورت عددی از ۰ تا کمتر از ۱۰۰ وارد کن."},
        )

    try:
        exact_price = _solve_sale_price(cost, target_percent)
    except ValueError as exc:
        return render(
            request,
            "core/_calculator_target_result_v104.html",
            {"error": str(exc)},
        )

    suggested_price = _rounded_up(exact_price, 1000)
    fee = int(digikala_fee_for_unit(suggested_price, date.today()))
    profit = suggested_price - fee - cost
    return render(request, "core/_calculator_target_result_v104.html", {
        "cost": cost,
        "target_profit_percent": float(target_percent),
        "exact_price": exact_price,
        "suggested_price": suggested_price,
        "fee": fee,
        "profit": profit,
        "profit_on_cost": (profit * 100 / cost) if cost else 0,
        "profit_on_sale": (profit * 100 / suggested_price) if suggested_price else 0,
    })
