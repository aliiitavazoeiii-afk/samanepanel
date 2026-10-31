from .darma_cost_v55 import darma_cost_for
from .finance import digikala_fee_for_unit
from .final_services import inventory_unit_cost
from .models import SaleSnapshot
from .novani_cost_v59 import novani_cost_for
from .takvin_pricing_v17 import takvin_cost_for


def darma_actual_unit_cost(line, ps=None, stock_brand_id=None):
    """Compatibility wrapper for the canonical date-effective Darma cost."""
    return int(darma_cost_for(line.day.date))


def snapshot_sale_line(line, ps=None, price=None):
    ps = ps or line.product_size
    price = int(line.sale_price if price is None else price)
    snap, _ = SaleSnapshot.objects.get_or_create(sale_line=line)
    snap.pack_qty = int(ps.product.pack_qty or 0)
    brand_name = ps.product.brand.name
    if brand_name in {"دارما", "انبارش"}:
        snap.unit_cost = int(darma_cost_for(line.day.date))
    elif brand_name == "Novani":
        # V59: Novani COGS is frozen from the single rule effective on sale date.
        snap.unit_cost = int(novani_cost_for(line.day.date))
    elif brand_name == "تکوین":
        snap.unit_cost = takvin_cost_for(ps.size, line.day.date)
    elif ps.unit_cost:
        snap.unit_cost = int(ps.unit_cost)
    else:
        snap.unit_cost = int(inventory_unit_cost(ps.product.brand, ps.size))
    snap.digikala_fee_unit = digikala_fee_for_unit(price, line.day.date)
    snap.save()
    return snap
