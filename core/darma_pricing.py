from django.db import transaction

from .darma_cost_v55 import darma_cost_for
from .models import AppSetting, Brand, ProductCode, ProductSize, Size


SIZE_NAMES = ["M", "L", "XL", "XXL", "3XL", "4XL"]

# Pack-1 is intentionally initialized to zero because the Digikala delivery XLSX
# does not carry the sale price. The user sets these once from the bulk-pricing UI;
# imports refuse a single-item sale until its size has a real price.
DEFAULT_GROUP_PRICES = {
    1: {"M": 0, "L": 0, "XL": 0, "XXL": 0, "3XL": 0, "4XL": 0},
    3: {"M": 385000, "L": 405000, "XL": 430000, "XXL": 455000, "3XL": 470000, "4XL": 495000},
    4: {"M": 485000, "L": 515000, "XL": 545000, "XXL": 570000, "3XL": 610000, "4XL": 630000},
    5: {"M": 570000, "L": 618000, "XL": 658000, "XXL": 701000, "3XL": 743000, "4XL": 790000},
    6: {"M": 699000, "L": 755000, "XL": 795000, "XXL": 860000, "3XL": 920000, "4XL": 980000},
}


def setting_key(pack_qty, size_name):
    return f"darma_group_price_pack{int(pack_qty)}_{size_name}"


def get_group_prices(pack_qty):
    pack_qty = int(pack_qty)
    defaults = DEFAULT_GROUP_PRICES[pack_qty]
    result = {}
    for size_name in SIZE_NAMES:
        key = setting_key(pack_qty, size_name)
        obj, _ = AppSetting.objects.get_or_create(
            key=key,
            defaults={
                "value": str(defaults[size_name]),
                "label": f"قیمت دارما پک {pack_qty} تایی - {size_name}",
            },
        )
        try:
            result[size_name] = max(0, int(str(obj.value).replace("٬", "").replace(",", "").replace(" ", "")))
        except Exception:
            result[size_name] = defaults[size_name]
    return result


def save_group_prices(pack_qty, prices):
    pack_qty = int(pack_qty)
    if pack_qty not in DEFAULT_GROUP_PRICES:
        raise ValueError("تعداد پک معتبر نیست.")
    cleaned = {}
    for size_name in SIZE_NAMES:
        value = int(prices.get(size_name, 0) or 0)
        if value <= 0:
            raise ValueError(f"قیمت {size_name} باید بیشتر از صفر باشد.")
        cleaned[size_name] = value
        AppSetting.objects.update_or_create(
            key=setting_key(pack_qty, size_name),
            defaults={
                "value": str(value),
                "label": f"قیمت دارما پک {pack_qty} تایی - {size_name}",
            },
        )
    return cleaned


@transaction.atomic
def apply_group_prices(pack_qty, prices=None):
    pack_qty = int(pack_qty)
    if pack_qty not in DEFAULT_GROUP_PRICES:
        raise ValueError("تعداد پک معتبر نیست.")
    prices = prices or get_group_prices(pack_qty)
    brand = Brand.objects.get(name="دارما")
    sizes = {row.name: row for row in Size.objects.filter(name__in=SIZE_NAMES)}
    products = list(ProductCode.objects.filter(brand=brand, pack_qty=pack_qty, active=True))
    current_cost = int(darma_cost_for())
    updated_rows = 0
    for product in products:
        for size_name in SIZE_NAMES:
            size = sizes.get(size_name)
            if not size:
                continue
            ps, _ = ProductSize.objects.get_or_create(
                product=product,
                size=size,
                defaults={
                    "default_sale_price": prices[size_name],
                    # Compatibility only. Darma accounting never reads this field
                    # as its source of truth after V55; keep it aligned anyway.
                    "unit_cost": current_cost,
                    "active": True,
                },
            )
            ps.default_sale_price = prices[size_name]
            ps.active = True
            ps.unit_cost = current_cost
            ps.save(update_fields=["default_sale_price", "active", "unit_cost"])
            updated_rows += 1
    return {"products": len(products), "rows": updated_rows}


@transaction.atomic
def apply_all_group_prices():
    summary = {}
    for pack_qty in sorted(DEFAULT_GROUP_PRICES):
        prices = get_group_prices(pack_qty)
        summary[pack_qty] = apply_group_prices(pack_qty, prices)
    return summary
