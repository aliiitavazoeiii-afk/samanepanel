from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum
from django.template.loader import get_template
from django.urls import resolve, reverse

from core.dia_gallery_v45 import (
    DIA_GALLERY_UNIT_PRICE,
    dia_gallery_receivable_total,
    sync_dia_gallery_sale,
)
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import (
    AccountEntry,
    Brand,
    DiaGallerySale,
    InventoryModelCost,
    SaleDay,
    StockBalance,
)


class Command(BaseCommand):
    help = "Validate Dia Gallery V45 route, UI and accounting/inventory roundtrip."

    def add_arguments(self, parser):
        parser.add_argument("--source-only", action="store_true")

    def handle(self, *args, **options):
        self._source_checks()
        self.stdout.write("DIA GALLERY V45 SOURCE CHECK OK")
        if options["source_only"]:
            return
        self._roundtrip_check()
        self.stdout.write("DIA GALLERY V45 ACCOUNTING ROUNDTRIP OK")
        self.stdout.write("NO TEST DATA CHANGED")

    def _source_checks(self):
        required_files = (
            "core/dia_gallery_v45.py",
            "core/migrations/0015_dia_gallery_sale.py",
            "templates/core/dia_gallery_sale_v45.html",
            "templates/core/sale_brand_v45.html",
            "templates/core/daily_report_v45.html",
            "templates/core/report_excel_v45.html",
        )
        for filename in required_files:
            if not Path(filename).is_file():
                raise CommandError(f"missing V45 file: {filename}")

        source = Path("core/dia_gallery_v45.py").read_text(encoding="utf-8")
        report = Path("core/report_v9.py").read_text(encoding="utf-8")
        if "DIA_GALLERY_UNIT_PRICE = 71_000" not in source:
            raise CommandError("Dia Gallery fixed 71,000 price marker missing")
        if 'entry_type="dia_gallery_sale"' not in source:
            raise CommandError("Dia Gallery receivable ledger marker missing")
        if "digikala_fee" not in source or '"digikala_fee": 0' not in source:
            raise CommandError("Dia Gallery no-Digikala-fee rule missing")
        if "+ dia_gallery_receivable" not in report:
            raise CommandError("Dia Gallery receivable is not included in accounts/capital")

        path = reverse("dia_gallery_sales", args=[1])
        if path != "/sales/1/dia-gallery/":
            raise CommandError(f"Dia Gallery route mismatch: {path}")
        resolve(path)
        for template in (
            "core/dia_gallery_sale_v45.html",
            "core/sale_brand_v45.html",
            "core/daily_report_v45.html",
            "core/report_excel_v45.html",
        ):
            get_template(template)

    def _roundtrip_check(self):
        darma = Brand.objects.get(name="دارما")
        candidate = (
            StockBalance.objects.filter(brand=darma)
            .values("size_id", "color_id")
            .annotate(total=Sum("qty"))
            .filter(total__gt=0)
            .order_by("-total")
        )
        chosen = None
        for row in candidate:
            cost = InventoryModelCost.objects.filter(
                brand=darma,
                size_id=row["size_id"],
                color_id=row["color_id"],
                unit_cost__gt=0,
            ).values_list("unit_cost", flat=True).first()
            if cost:
                chosen = (row["size_id"], row["color_id"], int(cost))
                break
        if chosen is None:
            raise CommandError("no positive Darma stock cell with valuation cost found for rollback test")

        size_id, color_id, expected_cost = chosen
        test_date = date(2099, 12, 31)
        if SaleDay.objects.filter(date=test_date).exists():
            raise CommandError("reserved V45 test date already exists")

        before_qty = int(StockBalance.objects.filter(brand=darma).aggregate(v=Sum("qty"))["v"] or 0)
        before_finished = int(finished_inventory_value_v17())
        before_receivable = int(dia_gallery_receivable_total())
        before_entries = AccountEntry.objects.count()
        before_lines = DiaGallerySale.objects.count()

        with transaction.atomic():
            day = SaleDay.objects.create(date=test_date)
            line = DiaGallerySale.objects.create(
                day=day,
                size_id=size_id,
                color_id=color_id,
                quantity=1,
                unit_price=DIA_GALLERY_UNIT_PRICE,
            )
            sync_dia_gallery_sale(line)
            line.refresh_from_db()

            qty1 = int(StockBalance.objects.filter(brand=darma).aggregate(v=Sum("qty"))["v"] or 0)
            finished1 = int(finished_inventory_value_v17())
            recv1 = int(dia_gallery_receivable_total())
            if qty1 != before_qty - 1:
                raise CommandError(f"Dia qty=1 stock mismatch: before={before_qty} after={qty1}")
            if recv1 != before_receivable + DIA_GALLERY_UNIT_PRICE:
                raise CommandError(f"Dia qty=1 receivable mismatch: before={before_receivable} after={recv1}")
            if int(line.unit_cost or 0) != expected_cost:
                raise CommandError(f"Dia unit-cost snapshot mismatch: expected={expected_cost} got={line.unit_cost}")
            expected_capital_delta = DIA_GALLERY_UNIT_PRICE - expected_cost
            actual_capital_delta = (finished1 + recv1) - (before_finished + before_receivable)
            if actual_capital_delta != expected_capital_delta:
                raise CommandError(
                    f"Dia capital delta mismatch: expected={expected_capital_delta} got={actual_capital_delta}"
                )

            line.quantity = 2
            line.save(update_fields=["quantity", "updated_at"])
            sync_dia_gallery_sale(line)
            qty2 = int(StockBalance.objects.filter(brand=darma).aggregate(v=Sum("qty"))["v"] or 0)
            recv2 = int(dia_gallery_receivable_total())
            if qty2 != before_qty - 2:
                raise CommandError(f"Dia qty=2 stock mismatch: before={before_qty} after={qty2}")
            if recv2 != before_receivable + 2 * DIA_GALLERY_UNIT_PRICE:
                raise CommandError(f"Dia qty=2 receivable mismatch: before={before_receivable} after={recv2}")

            line.quantity = 0
            line.save(update_fields=["quantity", "updated_at"])
            sync_dia_gallery_sale(line)
            qty0 = int(StockBalance.objects.filter(brand=darma).aggregate(v=Sum("qty"))["v"] or 0)
            recv0 = int(dia_gallery_receivable_total())
            if qty0 != before_qty:
                raise CommandError(f"Dia reversal stock mismatch: before={before_qty} after={qty0}")
            if recv0 != before_receivable:
                raise CommandError(f"Dia reversal receivable mismatch: before={before_receivable} after={recv0}")

            transaction.set_rollback(True)

        after_qty = int(StockBalance.objects.filter(brand=darma).aggregate(v=Sum("qty"))["v"] or 0)
        after_finished = int(finished_inventory_value_v17())
        after_receivable = int(dia_gallery_receivable_total())
        after_entries = AccountEntry.objects.count()
        after_lines = DiaGallerySale.objects.count()
        if (after_qty, after_finished, after_receivable, after_entries, after_lines) != (
            before_qty, before_finished, before_receivable, before_entries, before_lines
        ):
            raise CommandError("V45 rollback test left persistent business changes")
