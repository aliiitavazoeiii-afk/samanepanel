from django.db import transaction

from .final_services import _record_stock, _stock, _transfer_for_need, sync_sale_inventory as standard_sync_sale_inventory
from .models import Brand, InventoryMovement, ProductComposition, SaleAllocation, SaleLine, SaleShortage, StockLocation


@transaction.atomic
def sync_sale_inventory_v19(line):
    """
    Normal brands keep the existing inventory engine.

    Anbaresh is a SALES CHANNEL for Darma goods, not an inventory brand. Its SaleLine
    stays under brand=Anbaresh for reporting, while physical stock is deducted from
    Darma HOME/KHORSHID using the mirrored Darma composition.
    """
    line = (
        SaleLine.objects.select_for_update()
        .select_related("day", "product_size__product__brand", "product_size__size")
        .get(pk=line.pk)
    )
    if line.product_size.product.brand.name != "انبارش":
        return standard_sync_sale_inventory(line)

    product = line.product_size.product
    size = line.product_size.size
    stock_brand = Brand.objects.get(name="دارما")
    home = StockLocation.objects.get(key=StockLocation.HOME)
    ref = f"anbaresh-sale:{line.id}"

    previous_choices = {
        row.source_color_id: (row.resolved, row.target_color_id)
        for row in line.shortages.all().order_by("id")
    }

    # Revert the previous application of this line before recalculating it.
    for alloc in list(line.allocations.select_related("color", "location").all()):
        balance = _stock(
            brand=stock_brand,
            size=size,
            color=alloc.color,
            location=alloc.location,
        )
        balance.qty += int(alloc.qty or 0)
        balance.save(update_fields=["qty"])
        _record_stock(
            movement_type=InventoryMovement.ADJUST,
            brand=stock_brand,
            size=size,
            color=alloc.color,
            location=alloc.location,
            delta=int(alloc.qty or 0),
            reference=f"{ref}:recalc",
        )
    line.allocations.all().delete()
    line.shortages.all().delete()

    if line.quantity <= 0:
        line.inventory_applied_quantity = 0
        line.save(update_fields=["inventory_applied_quantity"])
        return {"shortages": [], "transferred": 0, "stock_brand": "دارما"}

    transferred = 0
    created_shortages = []
    for comp in ProductComposition.objects.filter(product=product).select_related("color"):
        needed = int(line.quantity) * int(comp.qty)
        before = _stock(brand=stock_brand, size=size, color=comp.color, location=home).qty
        source_bal = _transfer_for_need(
            brand=stock_brand,
            size=size,
            color=comp.color,
            needed=needed,
            reference=f"{ref}:auto-transfer:{comp.color_id}",
        )
        transferred += max(0, int(source_bal.qty or 0) - int(before or 0))
        available = max(0, int(source_bal.qty or 0))

        if available >= needed:
            source_bal.qty -= needed
            source_bal.save(update_fields=["qty"])
            SaleAllocation.objects.create(
                sale_line=line,
                color=comp.color,
                location=home,
                qty=needed,
            )
            _record_stock(
                movement_type=InventoryMovement.SALE,
                brand=stock_brand,
                size=size,
                color=comp.color,
                location=home,
                delta=-needed,
                reference=ref,
            )
            continue

        source_take = available
        shortage = needed - source_take
        choice = previous_choices.get(comp.color_id)
        if source_take:
            source_bal.qty -= source_take
            source_bal.save(update_fields=["qty"])
            SaleAllocation.objects.create(
                sale_line=line,
                color=comp.color,
                location=home,
                qty=source_take,
            )
            _record_stock(
                movement_type=InventoryMovement.SALE,
                brand=stock_brand,
                size=size,
                color=comp.color,
                location=home,
                delta=-source_take,
                reference=ref,
            )

        if choice and choice[0] and choice[1]:
            target = comp.color.__class__.objects.get(pk=choice[1])
            target_bal = _transfer_for_need(
                brand=stock_brand,
                size=size,
                color=target,
                needed=shortage,
                reference=f"{ref}:replacement-transfer:{target.id}",
            )
            target_available = max(0, int(target_bal.qty or 0))
            target_bal.qty -= shortage
            target_bal.save(update_fields=["qty"])
            SaleAllocation.objects.create(
                sale_line=line,
                color=target,
                location=home,
                qty=shortage,
                is_replacement=True,
            )
            _record_stock(
                movement_type=InventoryMovement.SALE,
                brand=stock_brand,
                size=size,
                color=target,
                location=home,
                delta=-shortage,
                reference=f"{ref}:replacement",
            )
            if target_available < shortage:
                extra = SaleShortage.objects.create(
                    sale_line=line,
                    source_color=target,
                    qty=shortage - target_available,
                    resolved=False,
                )
                created_shortages.append(extra)
        else:
            source_bal.qty -= shortage
            source_bal.save(update_fields=["qty"])
            SaleAllocation.objects.create(
                sale_line=line,
                color=comp.color,
                location=home,
                qty=shortage,
            )
            _record_stock(
                movement_type=InventoryMovement.SALE,
                brand=stock_brand,
                size=size,
                color=comp.color,
                location=home,
                delta=-shortage,
                reference=ref,
            )
            resolved_none = bool(choice and choice[0] and not choice[1])
            shortage_obj = SaleShortage.objects.create(
                sale_line=line,
                source_color=comp.color,
                qty=shortage,
                resolved=resolved_none,
                target_color=None,
            )
            if not resolved_none:
                created_shortages.append(shortage_obj)

    line.inventory_applied_quantity = line.quantity
    line.save(update_fields=["inventory_applied_quantity"])
    return {"shortages": created_shortages, "transferred": transferred, "stock_brand": "دارما"}
