from django.core.management.base import BaseCommand
from django.db.models import Sum

from core.models import (
    Brand, Color, InventoryMovement, SaleAllocation, Size,
    StockBalance, StockLocation, StockTransfer,
)


class Command(BaseCommand):
    help = "Read-only trace for negative Darma stock rows and transfer history."

    def add_arguments(self, parser):
        parser.add_argument("--color", default="طوسی")
        parser.add_argument("--size", default="XXL")

    def handle(self, *args, **options):
        brand = Brand.objects.get(name="دارما")
        color = Color.objects.get(name=options["color"])
        size = Size.objects.get(name=options["size"])

        self.stdout.write("=== NEGATIVE DARMA TRACE V15 (READ ONLY) ===")
        self.stdout.write(f"TARGET = {color.name} / {size.name}")

        self.stdout.write("\n--- CURRENT BALANCES ---")
        total = 0
        for loc in StockLocation.objects.order_by("id"):
            qty = int(
                StockBalance.objects.filter(
                    brand=brand, color=color, size=size, location=loc
                ).values_list("qty", flat=True).first() or 0
            )
            total += qty
            self.stdout.write(f"{loc.key} ({loc.title}): {qty}")
        self.stdout.write(f"NET TARGET QTY = {total}")

        self.stdout.write("\n--- MANUAL STOCK TRANSFERS ---")
        transfers = StockTransfer.objects.filter(
            brand=brand, color=color, size=size
        ).select_related("from_location", "to_location").order_by("id")
        if not transfers.exists():
            self.stdout.write("NONE")
        for t in transfers:
            self.stdout.write(
                f"TRANSFER id={t.id} date={t.date} qty={t.qty} "
                f"{t.from_location.key}->{t.to_location.key} applied={t.applied} "
                f"created={t.created_at} note={t.note!r}"
            )

        self.stdout.write("\n--- INVENTORY MOVEMENTS FOR TARGET ---")
        movements = InventoryMovement.objects.filter(
            brand=brand, color=color, size=size
        ).select_related("location").order_by("id")
        movement_total = 0
        for m in movements:
            movement_total += int(m.delta or 0)
            self.stdout.write(
                f"MOVE id={m.id} created={m.created_at} type={m.movement_type} "
                f"loc={m.location.key} delta={m.delta:+d} ref={m.reference!r}"
            )
        self.stdout.write(f"MOVEMENT HISTORY NET = {movement_total:+d}")

        self.stdout.write("\n--- CURRENT SALE ALLOCATIONS FOR TARGET ---")
        allocs = SaleAllocation.objects.filter(
            sale_line__product_size__product__brand=brand,
            sale_line__product_size__size=size,
            color=color,
            sale_line__quantity__gt=0,
        ).select_related(
            "sale_line__day", "sale_line__product_size__product", "location"
        ).order_by("sale_line__day__date", "id")
        alloc_total = 0
        if not allocs.exists():
            self.stdout.write("NONE")
        for a in allocs:
            alloc_total += int(a.qty or 0)
            self.stdout.write(
                f"ALLOC id={a.id} day={a.sale_line.day.date} "
                f"code={a.sale_line.product_size.product.code} qty={a.qty} "
                f"loc={a.location.key} replacement={a.is_replacement}"
            )
        self.stdout.write(f"CURRENT ALLOCATED SOLD TARGET = {alloc_total}")

        self.stdout.write("\n--- ALL NEGATIVE DARMA ROWS ---")
        negatives = StockBalance.objects.filter(
            brand=brand, qty__lt=0
        ).select_related("color", "size", "location").order_by("location__key", "color__name", "size__sort_order")
        for row in negatives:
            self.stdout.write(
                f"NEG id={row.id} loc={row.location.key} color={row.color.name} "
                f"size={row.size.name} qty={row.qty}"
            )
        self.stdout.write(f"NEGATIVE ROW COUNT = {negatives.count()}")
        self.stdout.write(self.style.SUCCESS("=== END NEGATIVE DARMA TRACE V15 ==="))
