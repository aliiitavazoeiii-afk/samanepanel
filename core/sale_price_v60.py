from datetime import date

from django.db import transaction

from .models import AppSetting, ProductSize


MANAGED_BRANDS = ("دارما", "تکوین")
RULE_PREFIX = "sale_price_rule_v60_"


def _clean_int(value, default=0):
    try:
        return max(
            0,
            int(
                str(value if value not in (None, "") else default)
                .replace("٬", "")
                .replace(",", "")
                .replace(" ", "")
            ),
        )
    except (TypeError, ValueError):
        return int(default or 0)


def _rule_key(product_size_id, effective_from):
    return f"{RULE_PREFIX}{int(product_size_id)}_{effective_from.isoformat()}"


def _parse_rule_key(key):
    text = str(key or "")
    if not text.startswith(RULE_PREFIX):
        return None
    rest = text[len(RULE_PREFIX):]
    try:
        ps_text, date_text = rest.split("_", 1)
        return int(ps_text), date.fromisoformat(date_text)
    except (TypeError, ValueError):
        return None


def list_sale_price_rules(product_size):
    ps_id = int(product_size.pk if hasattr(product_size, "pk") else product_size)
    prefix = f"{RULE_PREFIX}{ps_id}_"
    rows = []
    for obj in AppSetting.objects.filter(key__startswith=prefix).order_by("key"):
        parsed = _parse_rule_key(obj.key)
        price = _clean_int(obj.value)
        if parsed and parsed[0] == ps_id and price > 0:
            rows.append(
                {
                    "id": obj.id,
                    "effective_from": parsed[1],
                    "price": price,
                }
            )
    rows.sort(key=lambda row: (row["effective_from"], row["id"]), reverse=True)
    return rows


def sale_price_for(product_size, on_date=None):
    """Canonical default sale price for a ProductSize on a SaleDay date.

    Existing SaleLine.sale_price remains authoritative once a line has been saved.
    This helper is only the default for a not-yet-saved sale line/import row.
    """
    if not isinstance(product_size, ProductSize):
        product_size = ProductSize.objects.select_related("product__brand", "size").get(pk=product_size)
    on_date = on_date or date.today()
    if product_size.product.brand.name not in MANAGED_BRANDS:
        return int(product_size.default_sale_price or 0)

    best = None
    for row in list_sale_price_rules(product_size):
        if row["effective_from"] <= on_date:
            if best is None or row["effective_from"] > best["effective_from"]:
                best = row
    if best:
        return int(best["price"])
    return int(product_size.default_sale_price or 0)


def next_sale_price_rule(product_size, after_date=None):
    after_date = after_date or date.today()
    future = [row for row in list_sale_price_rules(product_size) if row["effective_from"] > after_date]
    if not future:
        return None
    return min(future, key=lambda row: (row["effective_from"], row["id"]))


@transaction.atomic
def set_sale_price_rule(product_size, effective_from, price):
    if not isinstance(product_size, ProductSize):
        product_size = ProductSize.objects.select_related("product__brand", "size").get(pk=product_size)
    if product_size.product.brand.name not in MANAGED_BRANDS:
        raise ValueError("قیمت تاریخ‌دار V60 فقط برای دارما و تکوین فعال است.")
    if not isinstance(effective_from, date):
        raise ValueError("تاریخ شروع قیمت فروش معتبر نیست.")
    price = _clean_int(price)
    if price <= 0:
        raise ValueError("قیمت فروش باید بیشتر از صفر باشد.")

    obj, _ = AppSetting.objects.update_or_create(
        key=_rule_key(product_size.id, effective_from),
        defaults={
            "value": str(price),
            "label": (
                f"قیمت فروش {product_size.product.brand.name} / "
                f"{product_size.product.code} / {product_size.size.name} از {effective_from.isoformat()}"
            ),
        },
    )
    return obj


def ensure_current_default_baseline(product_size):
    """Keep the legacy ProductSize default as the pre-rule fallback.

    No database row is needed: the existing default_sale_price is intentionally
    the immutable fallback for dates before the first V60 rule.
    """
    return int(product_size.default_sale_price or 0)
