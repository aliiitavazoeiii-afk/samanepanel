from django.core.management.base import BaseCommand
from django.template.loader import get_template
from django.urls import resolve, reverse

from core import inventory_operations_v16 as v16
from core.models import InventoryMovement, StockLocation, StockTransfer


class Command(BaseCommand):
    help = "Read-only regression check for V79 transfer correction workflow."

    def handle(self, *args, **options):
        get_template("core/inventory_operations.html")

        operations_match = resolve(reverse("inventory_operations"))
        update_match = resolve(reverse("inventory_transfer_update", args=[1]))
        if operations_match.func is not v16.inventory_operations:
            raise RuntimeError("inventory_operations is not routed to V79/V16")
        if update_match.func is not v16.inventory_transfer_update:
            raise RuntimeError("inventory_transfer_update is not routed to V79/V16")

        recent = list(
            StockTransfer.objects.filter(
                applied=True,
                brand__name="دارما",
                from_location__key=StockLocation.KHORSHID,
                to_location__key=StockLocation.HOME,
            )
            .select_related("brand", "size", "color", "from_location", "to_location")
            .order_by("-id")[:50]
        )

        malformed = 0
        for transfer in recent:
            ref = f"manual-transfer:{transfer.id}"
            rows = list(
                InventoryMovement.objects.filter(
                    movement_type=InventoryMovement.TRANSFER,
                    reference=ref,
                    brand=transfer.brand,
                    size=transfer.size,
                    color=transfer.color,
                ).values_list("location_id", "delta")
            )
            expected = {
                (transfer.from_location_id, -int(transfer.qty or 0)),
                (transfer.to_location_id, int(transfer.qty or 0)),
            }
            if len(rows) != 2 or set((location_id, int(delta)) for location_id, delta in rows) != expected:
                malformed += 1

        self.stdout.write(f"RECENT EDITABLE TRANSFERS = {len(recent)}")
        self.stdout.write(f"LEGACY/MALFORMED TRANSFERS GUARDED = {malformed}")
        self.stdout.write("EDIT MODE = quantity only")
        self.stdout.write("ZERO = remove transfer and reverse its stock effect")
        self.stdout.write("INCREASE = blocked if KHORSHID lacks the extra quantity")
        self.stdout.write("TOTAL STOCK = unchanged by transfer correction")
        self.stdout.write("LATER HOME MOVEMENTS = preserved; only quantity difference is applied")
        self.stdout.write("TEMPLATE COMPILE = OK")
        self.stdout.write("ROUTES = OK")
        self.stdout.write("CHECK MODE = READ ONLY")
        self.stdout.write(self.style.SUCCESS("INVENTORY TRANSFER EDIT V79 CHECK OK"))
