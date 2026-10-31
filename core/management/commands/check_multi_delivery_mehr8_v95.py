"""Read-only regression for V95 multi-file Digikala import + Mehr 8 zero commission."""
from datetime import date
from hashlib import sha256
from inspect import getsource
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from core.cost_accounting_v14 import snapshot_sale_line
from core.daily_order_import_v23 import merge_delivery_previews
from core.daily_order_views_v60 import import_daily_orders
from core.dateutils import parse_jalali_date
from core.finance import digikala_fee_for_unit, is_digikala_zero_commission_date
from core.models import AppSetting, AccountEntry, InventoryMovement, SaleLine, SaleSnapshot, StockBalance


def _digest_model(model):
    fields = [field.attname for field in model._meta.concrete_fields]
    digest = sha256()
    for row in model.objects.order_by(model._meta.pk.attname).values_list(*fields):
        digest.update(repr(tuple(row)).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _state():
    return {
        "settings": _digest_model(AppSetting),
        "stock": _digest_model(StockBalance),
        "movements": _digest_model(InventoryMovement),
        "sales": _digest_model(SaleLine),
        "snapshots": _digest_model(SaleSnapshot),
        "ledger": _digest_model(AccountEntry),
    }


class Command(BaseCommand):
    help = "Read-only: validate multi-file authoritative import and one-day zero commission."

    def handle(self, *args, **kwargs):
        before = _state()

        # Pure merge check: overlapping rows from two shipment files must SUM,
        # while the selected file set remains the authoritative full-day target.
        p1 = {
            "filename": "shipment-a.xlsx",
            "source_rows": 1,
            "ignored_rows": 0,
            "raw_quantity": 2,
            "errors": [],
            "rows": [
                {"brand": "دارما", "code": "220", "size": "M", "color": "", "quantity": 2}
            ],
        }
        p2 = {
            "filename": "shipment-b.xlsx",
            "source_rows": 2,
            "ignored_rows": 0,
            "raw_quantity": 4,
            "errors": [],
            "rows": [
                {"brand": "دارما", "code": "220", "size": "M", "color": "", "quantity": 3},
                {"brand": "تکوین", "code": "15", "size": "L", "color": "", "quantity": 1},
            ],
        }
        merged = merge_delivery_previews([p1, p2])
        if merged["files_count"] != 2 or merged["total_quantity"] != 6:
            raise RuntimeError(f"V95 merge totals wrong: {merged}")
        keyed = {
            (row["brand"], row["code"], row["size"], row["color"]): row["quantity"]
            for row in merged["rows"]
        }
        if keyed.get(("دارما", "220", "M", "")) != 5:
            raise RuntimeError("Overlapping same-day shipment rows were not summed")
        if keyed.get(("تکوین", "15", "L", "")) != 1:
            raise RuntimeError("Non-overlapping shipment row was lost")

        # 8 Mehr 1405 is the ONLY commission-zero date.
        special = parse_jalali_date("1405/07/08")
        if special != date(2026, 9, 30):
            raise RuntimeError(f"Unexpected Gregorian mapping for 1405/07/08: {special}")
        if not is_digikala_zero_commission_date(special):
            raise RuntimeError("8 Mehr 1405 is not marked zero-commission")
        for other in (date(2026, 9, 29), date(2026, 10, 1)):
            if is_digikala_zero_commission_date(other):
                raise RuntimeError(f"Zero-commission exception leaked to {other}")

        price = 500_000
        special_fee = int(digikala_fee_for_unit(price, special))
        normal_fee = int(digikala_fee_for_unit(price, date(2026, 10, 1)))
        if special_fee < 0 or normal_fee < special_fee:
            raise RuntimeError(
                f"Mehr 8 fee relationship invalid: special={special_fee}, normal={normal_fee}"
            )

        finance_source = getsource(digikala_fee_for_unit)
        if "commission_rate = Decimal(0)" not in finance_source:
            raise RuntimeError("V95 zero-commission branch missing")
        if "processing_rate" not in finance_source or "processing_floor" not in finance_source:
            raise RuntimeError("Processing fee logic disappeared from V95 fee function")

        snapshot_source = getsource(snapshot_sale_line)
        if "digikala_fee_for_unit(price, line.day.date)" not in snapshot_source:
            raise RuntimeError("SaleSnapshot fee is not frozen using sale date")

        import_source = getsource(import_daily_orders)
        if 'request.FILES.getlist("orders_file")' not in import_source:
            raise RuntimeError("Daily import does not read all selected XLSX files")
        if "apply_delivery_reports_v60" not in import_source:
            raise RuntimeError("Daily import is not using V95 merged-file path")

        upload_template = (
            Path(settings.BASE_DIR) / "templates/core/_daily_order_upload.html"
        ).read_text(encoding="utf-8")
        if 'name="orders_file"' not in upload_template or " multiple" not in upload_template:
            raise RuntimeError("Upload UI is not multi-file enabled")

        after = _state()
        if before != after:
            raise RuntimeError("V95 read-only regression changed business/inventory/ledger state")

        self.stdout.write("TWO-FILE SAME-DAY MERGE = OK")
        self.stdout.write("OVERLAPPING PRODUCT QUANTITIES SUM = OK")
        self.stdout.write("MULTI-FILE UPLOAD UI = OK")
        self.stdout.write("1405/07/08 == 2026-09-30 = OK")
        self.stdout.write("MEHR 8 ZERO COMMISSION ONLY = OK")
        self.stdout.write("PROCESSING FEE LOGIC PRESERVED = OK")
        self.stdout.write("SALE-DATE FEE SNAPSHOT = OK")
        self.stdout.write("NO STOCK / SALE / SNAPSHOT / LEDGER WRITE = OK")
        self.stdout.write(self.style.SUCCESS("SUCCESS: MULTI DELIVERY + MEHR8 ZERO COMMISSION V95 CHECK PASSED"))
