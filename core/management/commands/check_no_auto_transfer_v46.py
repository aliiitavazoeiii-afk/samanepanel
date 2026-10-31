import inspect
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

from core.final_services import _transfer_for_need, sync_stock_transfer
from core.models import (
    Brand,
    InventoryMovement,
    StockBalance,
    StockLocation,
    StockTransfer,
)
from core.variant_sale_v12 import sync_variant_inventory


def _qty(brand):
    return int(StockBalance.objects.filter(brand=brand).aggregate(v=Sum("qty"))["v"] or 0)


class Command(BaseCommand):
    help = "Regression check for V46: sales never auto-transfer Darma KHORSHID stock."

    def add_arguments(self, parser):
        parser.add_argument("--source-only", action="store_true")

    def handle(self, *args, **options):
        helper_source = inspect.getsource(_transfer_for_need)
        variant_source = inspect.getsource(sync_variant_inventory)

        if "StockLocation.KHORSHID" in helper_source or "kh_bal" in helper_source:
            raise CommandError("V46 source guard failed: sale helper still references KHORSHID.")
        if "variant-auto-transfer" in variant_source or "kh_row" in variant_source:
            raise CommandError("V46 source guard failed: s3 variant sale can still auto-transfer.")

        self.stdout.write("V46 SOURCE CHECK OK")
        self.stdout.write("- standard/Dia/Anbaresh helper is HOME-only")
        self.stdout.write("- s3 variable-color sale is HOME-only")

        if options["source_only"]:
            return

        darma = Brand.objects.get(name="دارما")
        home = StockLocation.objects.get(key=StockLocation.HOME)
        kh = StockLocation.objects.get(key=StockLocation.KHORSHID)
        cell = (
            StockBalance.objects.filter(brand=darma, location=home)
            .select_related("color", "size")
            .order_by("id")
            .first()
        )
        if cell is None:
            raise CommandError("No Darma HOME stock cell available for rollback test.")

        before_total = _qty(darma)
        before_movements = InventoryMovement.objects.count()
        before_transfers = StockTransfer.objects.count()

        with transaction.atomic():
            home_row, _ = StockBalance.objects.get_or_create(
                brand=darma,
                color=cell.color,
                size=cell.size,
                location=home,
                defaults={"qty": 0},
            )
            kh_row, _ = StockBalance.objects.get_or_create(
                brand=darma,
                color=cell.color,
                size=cell.size,
                location=kh,
                defaults={"qty": 0},
            )
            home_row = StockBalance.objects.select_for_update().get(pk=home_row.pk)
            kh_row = StockBalance.objects.select_for_update().get(pk=kh_row.pk)

            # Exact requested semantics example:
            # HOME=-10; a sale need must not touch KHORSHID.
            home_row.qty = -10
            kh_row.qty = 50
            home_row.save(update_fields=["qty"])
            kh_row.save(update_fields=["qty"])

            returned = _transfer_for_need(
                brand=darma,
                size=cell.size,
                color=cell.color,
                needed=30,
                reference="v46-regression-no-auto-transfer",
            )
            returned.refresh_from_db()
            kh_row.refresh_from_db()
            if int(returned.qty) != -10 or int(kh_row.qty) != 50:
                raise CommandError(
                    f"Sale helper moved stock automatically: HOME={returned.qty} KH={kh_row.qty}"
                )

            # Only an explicit manual transfer may move warehouse stock.
            transfer = StockTransfer.objects.create(
                date=date.today(),
                brand=darma,
                color=cell.color,
                size=cell.size,
                qty=30,
                from_location=kh,
                to_location=home,
                note="V46 rollback regression",
            )
            sync_stock_transfer(transfer)
            returned.refresh_from_db()
            kh_row.refresh_from_db()
            if int(returned.qty) != 20 or int(kh_row.qty) != 20:
                raise CommandError(
                    f"Manual transfer arithmetic failed: HOME={returned.qty} KH={kh_row.qty}"
                )

            self.stdout.write(
                f"V46 ROLLBACK TEST OK: HOME -10 -> 20 after explicit transfer 30; KH 50 -> 20"
            )
            transaction.set_rollback(True)

        if _qty(darma) != before_total:
            raise CommandError("Rollback test changed Darma total stock.")
        if InventoryMovement.objects.count() != before_movements:
            raise CommandError("Rollback test left InventoryMovement rows behind.")
        if StockTransfer.objects.count() != before_transfers:
            raise CommandError("Rollback test left StockTransfer rows behind.")

        self.stdout.write("NO TEST DATA CHANGED")
        self.stdout.write(self.style.SUCCESS("SUCCESS: V46 NO-AUTO-TRANSFER REGRESSION PASSED"))