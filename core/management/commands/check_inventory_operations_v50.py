from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum
from django.template.loader import get_template
from django.urls import resolve, reverse

from core.brand_colors import colors_for_brand
from core.inventory_operations_v15 import (
    _bulk_set_inventory_targets,
    _bulk_transfer_khorshid_to_home,
)
from core.models import (
    Brand,
    InventoryAdjustment,
    InventoryMovement,
    Size,
    StockBalance,
    StockLocation,
    StockTransfer,
)


def _brand_total(brand):
    return int(StockBalance.objects.filter(brand=brand).aggregate(v=Sum("qty"))["v"] or 0)


class Command(BaseCommand):
    help = "Regression check for V50 compact inventory operations and multi-color absolute stock correction."

    def handle(self, *args, **options):
        self._source_checks()
        self._roundtrip_check()
        self.stdout.write(self.style.SUCCESS("SUCCESS: INVENTORY OPERATIONS V50 CHECK PASSED"))
        self.stdout.write("NO TEST DATA CHANGED")

    def _source_checks(self):
        path = reverse("inventory_operations")
        if path != "/inventory/operations/":
            raise CommandError(f"inventory operations route mismatch: {path}")
        resolved = resolve(path)
        if resolved.func.__module__ != "core.inventory_operations_v15":
            raise CommandError(f"wrong inventory operations module: {resolved.func.__module__}")

        try:
            get_template("core/inventory_operations.html")
        except Exception as exc:
            raise CommandError(f"inventory operations template does not compile: {exc}") from exc

        source = (Path(settings.BASE_DIR) / "templates" / "core" / "inventory_operations.html").read_text(encoding="utf-8")
        required = [
            'class="col-12 col-lg-6"',
            'name="target_{{ group.brand.id }}_{{ color.id }}"',
            'data-brand-id="{{ group.brand.id }}"',
            "موجودی اصلی",
            "خالی = بدون تغییر",
            "عدد 0 را صریح وارد کن",
            'name="qty_{{ color.id }}"',
            "انتقال از خورشید به خانه",
        ]
        for marker in required:
            if marker not in source:
                raise CommandError(f"V50 template marker missing: {marker}")

        forbidden = [
            'name="from_location"',
            'name="to_location"',
            'name="note"',
            'name="target_qty"',
            'name="color"',
        ]
        for marker in forbidden:
            if marker in source:
                raise CommandError(f"obsolete single-row inventory field still present: {marker}")

        self.stdout.write("V50 SOURCE CHECK OK")
        self.stdout.write("- transfer and correction cards are compact side-by-side desktop cards")
        self.stdout.write("- correction is brand/size/location + brand color list")
        self.stdout.write("- correction reason and one-color selector are removed")

    def _roundtrip_check(self):
        darma = Brand.objects.get(name="دارما")
        home = StockLocation.objects.get(key=StockLocation.HOME)
        khorshid = StockLocation.objects.get(key=StockLocation.KHORSHID)
        colors = list(colors_for_brand(darma)[:2])
        if len(colors) < 2:
            raise CommandError("need at least two Darma colors for V50 rollback test")

        size_id = (
            StockBalance.objects.filter(brand=darma)
            .values_list("size_id", flat=True)
            .order_by("size__sort_order", "size_id")
            .first()
        )
        if not size_id:
            raise CommandError("no Darma stock size available for V50 rollback test")
        size = Size.objects.get(id=size_id)

        before_total = _brand_total(darma)
        before_adjustments = InventoryAdjustment.objects.count()
        before_transfers = StockTransfer.objects.count()
        before_movements = InventoryMovement.objects.count()

        with transaction.atomic():
            c1, c2 = colors
            h1, _ = StockBalance.objects.get_or_create(
                brand=darma, size=size, color=c1, location=home, defaults={"qty": 0}
            )
            k1, _ = StockBalance.objects.get_or_create(
                brand=darma, size=size, color=c1, location=khorshid, defaults={"qty": 0}
            )
            h2, _ = StockBalance.objects.get_or_create(
                brand=darma, size=size, color=c2, location=home, defaults={"qty": 0}
            )
            k2, _ = StockBalance.objects.get_or_create(
                brand=darma, size=size, color=c2, location=khorshid, defaults={"qty": 0}
            )

            h1.qty = 160
            k1.qty = 500
            h2.qty = 20
            k2.qty = 500
            h1.save(update_fields=["qty"])
            k1.save(update_fields=["qty"])
            h2.save(update_fields=["qty"])
            k2.save(update_fields=["qty"])

            adjustment = _bulk_set_inventory_targets(
                adjustment_date=date(2099, 12, 28),
                brand=darma,
                size=size,
                location=home,
                color_targets=[(c1, 140), (c2, 35)],
            )
            h1.refresh_from_db(); h2.refresh_from_db()
            if (int(h1.qty), int(h2.qty)) != (140, 35):
                raise CommandError(f"bulk absolute correction wrong: HOME values={h1.qty}/{h2.qty}")
            deltas = sorted(int(row["delta"]) for row in adjustment["changed"])
            if deltas != [-20, 15]:
                raise CommandError(f"bulk absolute correction deltas wrong: {deltas}")
            if adjustment["entered_count"] != 2 or len(adjustment["changed"]) != 2:
                raise CommandError(f"bulk absolute correction summary wrong: {adjustment}")

            combined_before_transfer = sum(
                int(row.qty or 0)
                for row in StockBalance.objects.filter(
                    brand=darma,
                    size=size,
                    color__in=[c1, c2],
                    location__in=[home, khorshid],
                )
            )

            transfer = _bulk_transfer_khorshid_to_home(
                transfer_date=date(2099, 12, 30),
                brand=darma,
                size=size,
                color_quantities=[(c1, 120), (c2, 120)],
            )
            if transfer["total_qty"] != 240 or len(transfer["transfers"]) != 2:
                raise CommandError(f"bulk transfer summary wrong: {transfer}")

            h1.refresh_from_db(); k1.refresh_from_db(); h2.refresh_from_db(); k2.refresh_from_db()
            if (int(h1.qty), int(k1.qty), int(h2.qty), int(k2.qty)) != (260, 380, 155, 380):
                raise CommandError(
                    "bulk transfer quantities wrong: "
                    f"{c1.name} HOME/KH={h1.qty}/{k1.qty}, {c2.name} HOME/KH={h2.qty}/{k2.qty}"
                )

            combined_after_transfer = sum(
                int(row.qty or 0)
                for row in StockBalance.objects.filter(
                    brand=darma,
                    size=size,
                    color__in=[c1, c2],
                    location__in=[home, khorshid],
                )
            )
            if combined_after_transfer != combined_before_transfer:
                raise CommandError(
                    "bulk transfer changed combined stock: "
                    f"before={combined_before_transfer} after={combined_after_transfer}"
                )

            zero_result = _bulk_set_inventory_targets(
                adjustment_date=date(2099, 12, 31),
                brand=darma,
                size=size,
                location=home,
                color_targets=[(c1, 0)],
            )
            h1.refresh_from_db()
            if int(h1.qty) != 0:
                raise CommandError(f"explicit zero target did not zero stock: got {h1.qty}")
            if not zero_result["changed"]:
                raise CommandError("explicit zero target produced no adjustment")

            self.stdout.write("BULK ABSOLUTE COUNT TEST OK: 160->140 and 20->35 in one atomic submit")
            self.stdout.write("EXPLICIT ZERO TEST OK: entered 0 sets counted stock to zero")
            self.stdout.write("BULK TRANSFER TEST OK: two colors x120 KHORSHID -> HOME")
            transaction.set_rollback(True)

        if _brand_total(darma) != before_total:
            raise CommandError("rollback test changed Darma total stock")
        if InventoryAdjustment.objects.count() != before_adjustments:
            raise CommandError("rollback test left InventoryAdjustment rows")
        if StockTransfer.objects.count() != before_transfers:
            raise CommandError("rollback test left StockTransfer rows")
        if InventoryMovement.objects.count() != before_movements:
            raise CommandError("rollback test left InventoryMovement rows")

        self.stdout.write("V50 ROLLBACK CHECK OK")
