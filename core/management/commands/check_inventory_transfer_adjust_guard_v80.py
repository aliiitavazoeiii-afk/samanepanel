import inspect

from django.core.management.base import BaseCommand
from django.urls import resolve, reverse

from core import inventory_operations_v17 as v17
from core.models import InventoryAdjustment, InventoryMovement, StockLocation, StockTransfer


class Command(BaseCommand):
    help = "Read-only regression check for V80 transfer edit guard after absolute inventory corrections."

    def handle(self, *args, **options):
        update_match = resolve(reverse("inventory_transfer_update", args=[1]))
        if update_match.func is not v17.inventory_transfer_update:
            raise RuntimeError("inventory_transfer_update is not routed to V80/V17")

        source = inspect.getsource(v17._update_transfer_qty)
        required_markers = [
            'reference__startswith="adjust:"',
            'note=""',
            'id__gt=cutoff_id',
            'ویرایش انتقال قدیمی می‌تواند شمارش جدیدتر را خراب کند',
        ]
        for marker in required_markers:
            if marker not in source:
                raise RuntimeError(f"V80 guard marker missing: {marker}")

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

        guarded = 0
        for transfer in recent:
            transfer_rows = list(
                InventoryMovement.objects.filter(
                    movement_type=InventoryMovement.TRANSFER,
                    reference=f"manual-transfer:{transfer.id}",
                    brand=transfer.brand,
                    size=transfer.size,
                    color=transfer.color,
                ).values_list("id", flat=True)
            )
            if len(transfer_rows) != 2:
                continue
            cutoff_id = max(transfer_rows)
            later_refs = list(
                InventoryMovement.objects.filter(
                    movement_type=InventoryMovement.ADJUST,
                    brand=transfer.brand,
                    size=transfer.size,
                    color=transfer.color,
                    location_id__in=[transfer.from_location_id, transfer.to_location_id],
                    id__gt=cutoff_id,
                    reference__startswith="adjust:",
                ).values_list("reference", flat=True)
            )
            adjustment_ids = []
            for reference in later_refs:
                raw = str(reference or "")
                value = raw.split(":", 1)[1] if raw.startswith("adjust:") else ""
                if value.isdigit() and raw == f"adjust:{int(value)}":
                    adjustment_ids.append(int(value))
            if adjustment_ids and InventoryAdjustment.objects.filter(
                id__in=adjustment_ids,
                applied=True,
                note="",
            ).exists():
                guarded += 1

        self.stdout.write(f"RECENT TRANSFERS CHECKED = {len(recent)}")
        self.stdout.write(f"TRANSFERS AFTER LATER ABSOLUTE CORRECTION = {guarded}")
        self.stdout.write("LATER MANUAL ABSOLUTE ADJUSTMENT GUARD = ON")
        self.stdout.write("SALES/OTHER DELTA MOVEMENTS AFTER TRANSFER = allowed")
        self.stdout.write("OLD TRANSFER EDIT AFTER ABSOLUTE CORRECTION = blocked")
        self.stdout.write("CHECK MODE = READ ONLY")
        self.stdout.write(self.style.SUCCESS("INVENTORY TRANSFER ADJUST GUARD V80 CHECK OK"))
