from django.core.management.base import BaseCommand

from core.finance import digikala_fee_for_unit
from core.final_services import inventory_unit_cost, setting_decimal, sync_sale_finance
from core.models import SaleLine, SaleSnapshot


class Command(BaseCommand):
    help = "Backfill immutable sale snapshots and rebuild Digikala receivable entries."

    def handle(self, *args, **options):
        count = 0
        for line in SaleLine.objects.select_related(
            "product_size__product__brand", "product_size__size", "day"
        ).iterator():
            snap, _ = SaleSnapshot.objects.get_or_create(sale_line=line)
            if not snap.pack_qty:
                snap.pack_qty = int(line.product_size.product.pack_qty or 0)
            if not snap.unit_cost:
                if line.product_size.product.brand.name == "دارما":
                    snap.unit_cost = int(
                        line.product_size.unit_cost
                        or setting_decimal("darma_accounting_unit_cost", 61000)
                    )
                else:
                    snap.unit_cost = int(
                        line.product_size.unit_cost
                        or inventory_unit_cost(
                            line.product_size.product.brand, line.product_size.size
                        )
                    )
            if not snap.digikala_fee_unit and line.sale_price:
                snap.digikala_fee_unit = digikala_fee_for_unit(line.sale_price)
            snap.save()
            sync_sale_finance(line)
            count += 1
        self.stdout.write(
            self.style.SUCCESS(f"Financial state synced for {count} sale lines")
        )
