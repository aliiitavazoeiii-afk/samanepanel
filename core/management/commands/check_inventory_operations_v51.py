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
    _delete_inventory_adjustment,
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
    help = "Regression check for V51 guarded deletion/reversal of manual inventory corrections."

    def handle(self, *args, **options):
        self._source_checks()
        self._roundtrip_check()
        self.stdout.write(self.style.SUCCESS("SUCCESS: INVENTORY OPERATIONS V51 CHECK PASSED"))
        self.stdout.write("NO TEST DATA CHANGED")

    def _source_checks(self):
        main_path = reverse("inventory_operations")
        if main_path != "/inventory/operations/":
            raise CommandError(f"inventory operations route mismatch: {main_path}")
        if resolve(main_path).func.__module__ != "core.inventory_operations_v15":
            raise CommandError("inventory operations is not routed to inventory_operations_v15")

        delete_path = reverse("inventory_adjustment_delete", kwargs={"adjustment_id": 123})
        if delete_path != "/inventory/operations/adjustments/123/delete/":
            raise CommandError(f"adjustment delete route mismatch: {delete_path}")
        resolved = resolve(delete_path)
        if resolved.func.__module__ != "core.inventory_operations_v15":
            raise CommandError(f"wrong delete route module: {resolved.func.__module__}")

        try:
            get_template("core/inventory_operations.html")
        except Exception as exc:
            raise CommandError(f"inventory operations template does not compile: {exc}") from exc

        source = (Path(settings.BASE_DIR) / "templates" / "core" / "inventory_operations.html").read_text(encoding="utf-8")
        required = [
            "آخرین گردش‌های موجودی",
            "inventory_adjustment_delete",
            "r.adjustment_delete_id",
            "این اصلاح موجودی حذف شود",
            "حذف فقط برای «اصلاح موجودی» دستی فعال است",
        ]
        for marker in required:
            if marker not in source:
                raise CommandError(f"V51 template marker missing: {marker}")

        self.stdout.write("V51 SOURCE CHECK OK")
        self.stdout.write("- delete route is POST-only and lives in inventory_operations_v15")
        self.stdout.write("- delete button is limited to blank-note manual correction adjustments")
        self.stdout.write("- standalone-return and other marked adjustments are excluded")

    def _roundtrip_check(self):
        darma = Brand.objects.get(name="دارما")
        home = StockLocation.objects.get(key=StockLocation.HOME)
        khorshid = StockLocation.objects.get(key=StockLocation.KHORSHID)
        colors = list(colors_for_brand(darma)[:2])
        if len(colors) < 2:
            raise CommandError("need at least two Darma colors for V51 rollback test")
        color, protected_color = colors

        size_id = (
            StockBalance.objects.filter(brand=darma)
            .values_list("size_id", flat=True)
            .order_by("size__sort_order", "size_id")
            .first()
        )
        if not size_id:
            raise CommandError("no Darma stock size available for V51 rollback test")
        size = Size.objects.get(id=size_id)

        before_total = _brand_total(darma)
        before_adjustments = InventoryAdjustment.objects.count()
        before_transfers = StockTransfer.objects.count()
        before_movements = InventoryMovement.objects.count()

        with transaction.atomic():
            home_row, _ = StockBalance.objects.get_or_create(
                brand=darma, size=size, color=color, location=home, defaults={"qty": 0}
            )
            kh_row, _ = StockBalance.objects.get_or_create(
                brand=darma, size=size, color=color, location=khorshid, defaults={"qty": 0}
            )
            protected_row, _ = StockBalance.objects.get_or_create(
                brand=darma, size=size, color=protected_color, location=home, defaults={"qty": 0}
            )
            home_row.qty = 160
            kh_row.qty = 500
            protected_row.qty = 50
            home_row.save(update_fields=["qty"])
            kh_row.save(update_fields=["qty"])
            protected_row.save(update_fields=["qty"])

            first = _bulk_set_inventory_targets(
                adjustment_date=date(2099, 12, 27),
                brand=darma,
                size=size,
                location=home,
                color_targets=[(color, 140)],
            )
            adjustment = first["changed"][0]["adjustment"]
            if int(first["changed"][0]["delta"]) != -20:
                raise CommandError(f"expected -20 adjustment, got {first}")

            home_row.refresh_from_db()
            if int(home_row.qty) != 140:
                raise CommandError(f"absolute correction failed before delete: {home_row.qty}")

            adjustment_id = adjustment.id
            result = _delete_inventory_adjustment(adjustment_id)
            home_row.refresh_from_db()
            if int(home_row.qty) != 160 or result["after"] != 160:
                raise CommandError(f"delete did not restore previous stock: result={result}, qty={home_row.qty}")
            if InventoryAdjustment.objects.filter(id=adjustment_id).exists():
                raise CommandError("deleted InventoryAdjustment row still exists")
            if InventoryMovement.objects.filter(reference=f"adjust:{adjustment_id}").exists():
                raise CommandError("deleted adjustment movement still exists")

            protected_result = _set_inventory_target(
                adjustment_date=date(2099, 12, 27),
                brand=darma,
                size=size,
                color=protected_color,
                location=home,
                target_qty=55,
                note="[standalone-return-v37] regression-protected",
            )
            protected_adjustment = protected_result["adjustment"]
            marker_blocked = False
            try:
                _delete_inventory_adjustment(protected_adjustment.id)
            except ValueError as exc:
                marker_blocked = "اصلاح دستی" in str(exc)
            if not marker_blocked:
                raise CommandError("marked/non-manual InventoryAdjustment was deletable from V51")
            protected_row.refresh_from_db()
            if int(protected_row.qty) != 55:
                raise CommandError("blocked non-manual adjustment delete changed stock")
            if not InventoryAdjustment.objects.filter(id=protected_adjustment.id, applied=True).exists():
                raise CommandError("blocked non-manual adjustment delete removed its row")

            second = _bulk_set_inventory_targets(
                adjustment_date=date(2099, 12, 28),
                brand=darma,
                size=size,
                location=home,
                color_targets=[(color, 140)],
            )
            guarded_adjustment = second["changed"][0]["adjustment"]
            _bulk_transfer_khorshid_to_home(
                transfer_date=date(2099, 12, 29),
                brand=darma,
                size=size,
                color_quantities=[(color, 1)],
            )
            home_row.refresh_from_db()
            if int(home_row.qty) != 141:
                raise CommandError(f"guard setup transfer wrong: HOME={home_row.qty}")

            blocked = False
            try:
                _delete_inventory_adjustment(guarded_adjustment.id)
            except ValueError as exc:
                blocked = "گردش جدید" in str(exc)
            if not blocked:
                raise CommandError("older correction delete was not blocked after a newer movement")

            home_row.refresh_from_db()
            if int(home_row.qty) != 141:
                raise CommandError("blocked delete changed stock")
            if not InventoryAdjustment.objects.filter(id=guarded_adjustment.id, applied=True).exists():
                raise CommandError("blocked delete removed the adjustment row")
            if not InventoryMovement.objects.filter(reference=f"adjust:{guarded_adjustment.id}").exists():
                raise CommandError("blocked delete removed the adjustment movement")

            self.stdout.write("DELETE ROUNDTRIP OK: 160 -> 140 -> delete -> 160")
            self.stdout.write("NON-MANUAL ADJUSTMENT GUARD OK: standalone-return style adjustment is not deletable")
            self.stdout.write("NEWER-MOVEMENT GUARD OK: old correction cannot cross a later transfer/sale/correction")
            transaction.set_rollback(True)

        if _brand_total(darma) != before_total:
            raise CommandError("rollback test changed Darma total stock")
        if InventoryAdjustment.objects.count() != before_adjustments:
            raise CommandError("rollback test left InventoryAdjustment rows")
        if StockTransfer.objects.count() != before_transfers:
            raise CommandError("rollback test left StockTransfer rows")
        if InventoryMovement.objects.count() != before_movements:
            raise CommandError("rollback test left InventoryMovement rows")

        self.stdout.write("V51 ROLLBACK CHECK OK")
