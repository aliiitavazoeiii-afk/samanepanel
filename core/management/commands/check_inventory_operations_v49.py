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
    _bulk_transfer_khorshid_to_home,
    _set_inventory_target,
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
    help = "Regression check for V49 inventory operations UI and rollback-safe business behavior."

    def handle(self, *args, **options):
        self._source_checks()
        self._roundtrip_check()
        self.stdout.write(self.style.SUCCESS("SUCCESS: INVENTORY OPERATIONS V49 CHECK PASSED"))
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
            'name="target_qty"',
            "موجودی اصلی",
            'name="qty_{{ color.id }}"',
            "انتقال از خورشید به خانه",
        ]
        for marker in required:
            if marker not in source:
                raise CommandError(f"V49 template marker missing: {marker}")

        forbidden = [
            'name="from_location"',
            'name="to_location"',
        ]
        for marker in forbidden:
            if marker in source:
                raise CommandError(f"old transfer field still present: {marker}")

        self.stdout.write("V49 SOURCE CHECK OK")

    def _roundtrip_check(self):
        darma = Brand.objects.get(name="دارما")
        home = StockLocation.objects.get(key=StockLocation.HOME)
        khorshid = StockLocation.objects.get(key=StockLocation.KHORSHID)
        colors = list(colors_for_brand(darma)[:2])
        if len(colors) < 2:
            raise CommandError("need at least two Darma colors for V49 rollback test")

        size_id = (
            StockBalance.objects.filter(brand=darma)
            .values_list("size_id", flat=True)
            .order_by("size__sort_order", "size_id")
            .first()
        )
        if not size_id:
            raise CommandError("no Darma stock size available for V49 rollback test")
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

            result = _set_inventory_target(
                adjustment_date=date(2099, 12, 29),
                brand=darma,
                size=size,
                color=c1,
                location=home,
                target_qty=140,
                note="V49 rollback test",
            )
            h1.refresh_from_db()
            if result["before"] != 160 or result["after"] != 140 or result["delta"] != -20:
                raise CommandError(f"absolute adjustment arithmetic wrong: {result}")
            if int(h1.qty) != 140:
                raise CommandError(f"absolute adjustment did not set final stock to 140: got {h1.qty}")

            combined_before = sum(
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
            if (int(h1.qty), int(k1.qty), int(h2.qty), int(k2.qty)) != (260, 380, 140, 380):
                raise CommandError(
                    "bulk transfer quantities wrong: "
                    f"{c1.name} HOME/KH={h1.qty}/{k1.qty}, {c2.name} HOME/KH={h2.qty}/{k2.qty}"
                )

            combined_after = sum(
                int(row.qty or 0)
                for row in StockBalance.objects.filter(
                    brand=darma,
                    size=size,
                    color__in=[c1, c2],
                    location__in=[home, khorshid],
                )
            )
            if combined_after != combined_before:
                raise CommandError(
                    f"bulk transfer changed combined stock: before={combined_before} after={combined_after}"
                )

            self.stdout.write("ABSOLUTE ADJUST TEST OK: 160 -> target 140 -> delta -20")
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

        self.stdout.write("V49 ROLLBACK CHECK OK")
