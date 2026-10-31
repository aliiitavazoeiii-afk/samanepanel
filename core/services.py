from django.db import transaction
from django.db.models import F

from .models import InventoryMovement, ProductComposition, SaleLine, StockBalance, StockLocation


def home_and_total(brand, size, color):
    qs = StockBalance.objects.filter(brand=brand, size=size, color=color)
    home = qs.filter(location__key="home").values_list("qty", flat=True).first() or 0
    total = sum(qs.values_list("qty", flat=True))
    return home, total


@transaction.atomic
def apply_stock_delta(*, brand, size, color, location, delta, movement_type, reference=""):
    bal, _ = StockBalance.objects.select_for_update().get_or_create(
        brand=brand, size=size, color=color, location=location, defaults={"qty": 0}
    )
    bal.qty = F("qty") + delta
    bal.save(update_fields=["qty"])
    bal.refresh_from_db()
    InventoryMovement.objects.create(
        movement_type=movement_type,
        brand=brand,
        size=size,
        color=color,
        location=location,
        delta=delta,
        reference=reference,
    )
    return bal.qty


def _locked_balance(*, brand, size, color, location):
    obj, _ = StockBalance.objects.get_or_create(
        brand=brand, size=size, color=color, location=location, defaults={"qty": 0}
    )
    return StockBalance.objects.select_for_update().get(pk=obj.pk)


@transaction.atomic
def sync_sale_line_inventory(line):
    line = (
        SaleLine.objects.select_for_update()
        .select_related("day", "product_size__product__brand", "product_size__size")
        .get(pk=line.pk)
    )
    delta_packs = line.quantity - line.inventory_applied_quantity
    if delta_packs == 0:
        return {"applied": True, "delta_packs": 0, "transferred": 0, "shortfall": 0}

    ps = line.product_size
    product = ps.product
    brand = product.brand
    size = ps.size
    composition = list(ProductComposition.objects.filter(product=product).select_related("color"))
    if not composition:
        return {
            "applied": False,
            "delta_packs": delta_packs,
            "transferred": 0,
            "shortfall": 0,
            "message": "ترکیب رنگ این کد تعریف نشده؛ موجودی تغییر نکرد.",
        }

    home = StockLocation.objects.get(key="home")
    khorshid = StockLocation.objects.get(key="khorshid")
    reference = f"sale:{line.id}:{line.day.date.isoformat()}:{product.code}:{size.name}"
    transferred_total = 0
    shortfall_total = 0

    for comp in composition:
        units = abs(delta_packs) * comp.qty
        home_bal = _locked_balance(brand=brand, size=size, color=comp.color, location=home)

        if delta_packs > 0:
            if brand.name == "دارما" and home_bal.qty < units:
                kh_bal = _locked_balance(brand=brand, size=size, color=comp.color, location=khorshid)
                needed = max(0, units - home_bal.qty)
                transfer_qty = min(needed, max(0, kh_bal.qty))
                if transfer_qty:
                    kh_bal.qty -= transfer_qty
                    home_bal.qty += transfer_qty
                    kh_bal.save(update_fields=["qty"])
                    home_bal.save(update_fields=["qty"])
                    InventoryMovement.objects.create(
                        movement_type=InventoryMovement.TRANSFER,
                        brand=brand,
                        size=size,
                        color=comp.color,
                        location=khorshid,
                        delta=-transfer_qty,
                        reference=reference,
                    )
                    InventoryMovement.objects.create(
                        movement_type=InventoryMovement.TRANSFER,
                        brand=brand,
                        size=size,
                        color=comp.color,
                        location=home,
                        delta=transfer_qty,
                        reference=reference,
                    )
                    transferred_total += transfer_qty

            if home_bal.qty < units:
                shortfall_total += units - home_bal.qty

            home_bal.qty -= units
            home_bal.save(update_fields=["qty"])
            InventoryMovement.objects.create(
                movement_type=InventoryMovement.SALE,
                brand=brand,
                size=size,
                color=comp.color,
                location=home,
                delta=-units,
                reference=reference,
            )
        else:
            home_bal.qty += units
            home_bal.save(update_fields=["qty"])
            InventoryMovement.objects.create(
                movement_type=InventoryMovement.SALE,
                brand=brand,
                size=size,
                color=comp.color,
                location=home,
                delta=units,
                reference=f"{reference}:correction",
            )

    line.inventory_applied_quantity = line.quantity
    line.save(update_fields=["inventory_applied_quantity"])
    return {
        "applied": True,
        "delta_packs": delta_packs,
        "transferred": transferred_total,
        "shortfall": shortfall_total,
    }
