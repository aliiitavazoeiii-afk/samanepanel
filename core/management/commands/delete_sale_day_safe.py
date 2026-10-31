from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

from core.dateutils import format_jalali, parse_jalali_date
from core.final_services import sync_sale_inventory
from core.finance import sale_line_metrics
from core.finance_excel_v9 import digikala_receivable_total, sync_sale_receivable
from core.models import InventoryMovement, SaleDay, StockBalance


class Command(BaseCommand):
    help = "Safely delete one Jalali sale day after reversing its inventory and Digikala receivable effects."

    def add_arguments(self, parser):
        parser.add_argument("jalali_date", help="Example: 1405/06/01")

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            target_date = parse_jalali_date(options["jalali_date"])
        except ValueError as exc:
            raise CommandError(str(exc))

        day = SaleDay.objects.select_for_update().filter(date=target_date).first()
        if not day:
            self.stdout.write(self.style.WARNING(f"No sale day found for {options['jalali_date']}"))
            return

        lines = list(
            day.lines.select_for_update().select_related(
                "day", "product_size__product__brand", "product_size__product", "product_size__size"
            )
        )
        gross = 0
        fee = 0
        cogs = 0
        packs = 0
        shorts = 0
        line_ids = []
        expected_restore = {}
        for line in lines:
            metrics = sale_line_metrics(line)
            gross += int(metrics["gross"] or 0)
            fee += int(metrics["digikala_fee"] or 0)
            cogs += int(metrics["cogs"] or 0)
            packs += int(metrics["packs"] or 0)
            shorts += int(metrics["shorts"] or 0)
            line_ids.append(line.id)
            brand_name = line.product_size.product.brand.name
            expected_restore[brand_name] = expected_restore.get(brand_name, 0) + (
                int(line.inventory_applied_quantity or 0) * int(line.product_size.product.pack_qty or 0)
            )

        before_stock = {
            brand_name: int(
                StockBalance.objects.filter(brand__name=brand_name).aggregate(v=Sum("qty"))["v"] or 0
            )
            for brand_name in expected_restore
        }
        receivable_before = int(digikala_receivable_total())

        # Setting quantity to zero lets the same inventory engine restore every
        # active allocation before the SaleLine objects are deleted.
        for line in lines:
            line.quantity = 0
            line.save(update_fields=["quantity"])
            sync_sale_inventory(line)
            sync_sale_receivable(line)

        for brand_name, expected_delta in expected_restore.items():
            after_qty = int(
                StockBalance.objects.filter(brand__name=brand_name).aggregate(v=Sum("qty"))["v"] or 0
            )
            actual_delta = after_qty - before_stock[brand_name]
            if actual_delta != expected_delta:
                raise CommandError(
                    f"Inventory guard failed for {brand_name}: restored {actual_delta:+d}, expected {expected_delta:+d}. "
                    "Transaction rolled back; sale day was NOT deleted."
                )

        # Stock balances are already restored; historical movement rows for this
        # deleted day are removed so the movement log does not keep orphan sale refs.
        for line_id in line_ids:
            InventoryMovement.objects.filter(reference__startswith=f"sale:{line_id}").delete()

        day_label = format_jalali(day.date)
        day.delete()
        receivable_after = int(digikala_receivable_total())

        self.stdout.write("=== SAFE SALE DAY DELETE ===")
        self.stdout.write(f"DATE              = {day_label}")
        self.stdout.write(f"LINES             = {len(lines)}")
        self.stdout.write(f"PACKS             = {packs}")
        self.stdout.write(f"SHORTS            = {shorts}")
        self.stdout.write(f"GROSS SALES       = {gross}")
        self.stdout.write(f"DIGIKALA FEE      = {fee}")
        self.stdout.write(f"COGS RESTORED     = {cogs}")
        self.stdout.write(f"NET RECEIVABLE    = {gross - fee}")
        self.stdout.write(f"DIGI BEFORE       = {receivable_before}")
        self.stdout.write(f"DIGI AFTER        = {receivable_after}")
        self.stdout.write(self.style.SUCCESS("SALE DAY DELETED; INVENTORY/RECEIVABLE EFFECTS REVERSED"))
