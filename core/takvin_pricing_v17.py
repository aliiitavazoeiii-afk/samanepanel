from datetime import date

from .models import ProductSize, Size, TakvinCostRule


TAKVIN_SIZES = ("M", "L", "XL", "XXL")
DEFAULT_COSTS = {
    "M": 108000,
    "L": 126000,
    "XL": 139500,
    "XXL": 153000,
}


def takvin_cost_for(size_or_name, on_date=None):
    """Return the Takvin accounting cost per short effective on a sale date."""
    on_date = on_date or date.today()
    size_name = size_or_name.name if hasattr(size_or_name, "name") else str(size_or_name)
    rule = (
        TakvinCostRule.objects.filter(size__name=size_name, effective_from__lte=on_date)
        .select_related("size")
        .order_by("-effective_from", "-id")
        .first()
    )
    if rule:
        return int(rule.unit_cost or 0)

    # Safe fallback for a database that has not yet been seeded.
    ps = (
        ProductSize.objects.filter(product__brand__name="تکوین", size__name=size_name, active=True)
        .order_by("id")
        .first()
    )
    if ps and int(ps.unit_cost or 0) > 0:
        return int(ps.unit_cost)
    return int(DEFAULT_COSTS.get(size_name, 0))


def current_takvin_costs(on_date=None):
    on_date = on_date or date.today()
    return {size_name: takvin_cost_for(size_name, on_date) for size_name in TAKVIN_SIZES}


def create_rule_set(effective_from, prices):
    created = []
    for size_name in TAKVIN_SIZES:
        value = int(prices.get(size_name, 0) or 0)
        if value <= 0:
            raise ValueError(f"قیمت تمام‌شده تکوین برای {size_name} باید بیشتر از صفر باشد.")
        size = Size.objects.get(name=size_name)
        obj, _ = TakvinCostRule.objects.update_or_create(
            size=size,
            effective_from=effective_from,
            defaults={"unit_cost": value},
        )
        created.append(obj)
    return created
