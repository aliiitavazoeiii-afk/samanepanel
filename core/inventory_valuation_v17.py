from django.db.models import Avg, Sum

from .darma_cost_v55 import darma_cost_for
from .models import InventoryModelCost, ProductSize, StockBalance
from .novani_cost_v59 import novani_cost_for
from .takvin_pricing_v17 import takvin_cost_for


def _anbaresh_unit_cost(brand_id, color_id, size_id):
    value = (
        ProductSize.objects.filter(
            product__brand_id=brand_id,
            product__composition__color_id=color_id,
            size_id=size_id,
            active=True,
            product__active=True,
            unit_cost__gt=0,
        ).aggregate(v=Avg("unit_cost"))["v"]
    )
    return int(value or 0)


def finished_inventory_value_v17():
    cost_map = {
        (row.brand_id, row.color_id, row.size_id): int(row.unit_cost or 0)
        for row in InventoryModelCost.objects.all()
    }
    current_darma_cost = int(darma_cost_for())
    current_novani_cost = int(novani_cost_for())
    total = 0
    rows = StockBalance.objects.values(
        "brand_id", "brand__name", "color_id", "size_id", "size__name"
    ).annotate(qty=Sum("qty"))
    for row in rows:
        # Anbaresh is only a sales/reporting channel for Darma goods and must never
        # contribute a separate inventory asset.
        if row["brand__name"] == "انبارش":
            continue
        qty = int(row["qty"] or 0)
        key = (row["brand_id"], row["color_id"], row["size_id"])
        if row["brand__name"] == "دارما":
            unit_cost = current_darma_cost
        elif row["brand__name"] == "Novani":
            # V59: one date-effective accounting cost for every Novani short.
            # Legacy color/size InventoryModelCost rows are not an accounting source.
            unit_cost = current_novani_cost
        elif row["brand__name"] == "تکوین":
            unit_cost = takvin_cost_for(row["size__name"])
        else:
            unit_cost = cost_map.get(key, 0)
            if not unit_cost and row["brand__name"] == "انبارش":
                unit_cost = _anbaresh_unit_cost(*key)
        total += qty * int(unit_cost or 0)
    return total
