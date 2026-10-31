from datetime import date
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum
from django.http import QueryDict
from django.template.loader import get_template

from core import business_tools_v21 as v21
from core import business_tools_v62 as v62
from core.models import BusinessPayment, ExcelManualRow, InventoryMovement, MoneyMovement, RawMaterialStock, StockBalance
from core.payment_source_v63 import SOURCE_MELAT, SOURCE_MOFID, source_balance
from core.self_spend_v62 import manual_accounts_capital_total, self_tracking_row


class Command(BaseCommand):
    help = "V63 regression: each payment debits exactly the selected Mellat/Mofid source and reverses safely."

    def _state(self):
        self_row = self_tracking_row(create=False)
        return {
            "payments": BusinessPayment.objects.count(),
            "mellat": int(v21.mellat_balance()),
            "mofid": int(source_balance(SOURCE_MOFID)),
            "manual_rows": ExcelManualRow.objects.count(),
            "self_amount": int(self_row.amount or 0) if self_row else 0,
            "money_movements": MoneyMovement.objects.count(),
            "stock_qty": int(StockBalance.objects.aggregate(v=Sum("qty"))["v"] or 0),
            "raw_qty": str(
                RawMaterialStock.objects.filter(active=True).aggregate(v=Sum("quantity"))["v"]
                or Decimal("0")
            ),
            "inventory_movements": InventoryMovement.objects.count(),
        }

    def handle(self, *args, **options):
        try:
            get_template("core/payments_v62.html")
        except Exception as exc:
            raise CommandError(f"V63 payments template failed to compile: {exc}") from exc

        source_checks = {
            "core/models.py": (
                'SOURCE_MELAT = "melat"',
                'SOURCE_MOFID = "mofid"',
                'source_account = models.CharField',
            ),
            "core/payment_source_v63.py": (
                "adjust_source_account",
                'return "ملت" if source == SOURCE_MELAT else "مفید"',
            ),
            "core/business_tools_v62.py": (
                'parsed["source_account"]',
                "_reroute_legacy_apply_from_mellat",
                "_reroute_legacy_reverse_from_mellat",
                "payment_source_payloads",
            ),
            "templates/core/payments_v62.html": (
                "payment-source-v63-data",
                "payments_source_v63.js",
            ),
            "core/static/core/payments_source_v63.js": (
                'name="source_account"',
                '>ملت<',
                '>مفید<',
            ),
            "core/migrations/0016_businesspayment_source_account.py": (
                'default="melat"',
                'name="source_account"',
            ),
        }
        for relative, markers in source_checks.items():
            text = (Path(settings.BASE_DIR) / relative).read_text(encoding="utf-8")
            for marker in markers:
                if marker not in text:
                    raise CommandError(f"V63 source marker missing: {relative}: {marker}")

        field = BusinessPayment._meta.get_field("source_account")
        if field.default != SOURCE_MELAT:
            raise CommandError("V63 historical-payment default is not Mellat")
        if dict(field.choices).get(SOURCE_MOFID) != "مفید":
            raise CommandError("V63 Mofid source choice missing")
        if BusinessPayment.objects.exclude(source_account__in=[SOURCE_MELAT, SOURCE_MOFID]).exists():
            raise CommandError("V63 found payment with invalid source account")

        default_post = QueryDict("", mutable=True)
        default_post.update({"date": "1405/06/16", "payee": "self", "amount": "1000"})
        if v62._parse_payment_post(default_post)["source_account"] != SOURCE_MELAT:
            raise CommandError("V63 payment without source no longer defaults to Mellat")

        explicit_post = default_post.copy()
        explicit_post["source_account"] = SOURCE_MOFID
        if v62._parse_payment_post(explicit_post)["source_account"] != SOURCE_MOFID:
            raise CommandError("V63 explicit Mofid source was not parsed")

        before = self._state()
        with transaction.atomic():
            # Personal payment from Mofid: Mofid down, Mellat untouched, capital down.
            self_amount = 1_234_567
            self_post = QueryDict("", mutable=True)
            self_post.update({
                "date": "1405/06/16",
                "payee": "self",
                "source_account": SOURCE_MOFID,
                "amount": str(self_amount),
                "note": "v63 self source regression",
            })
            parsed_self = v62._parse_payment_post(self_post)
            mellat_before = int(v21.mellat_balance())
            mofid_before = int(source_balance(SOURCE_MOFID))
            capital_before = int(manual_accounts_capital_total())
            self_row_before = self_tracking_row(create=False)
            self_before = int(self_row_before.amount or 0) if self_row_before else 0

            p1 = BusinessPayment.objects.create(
                date=date.today(),
                payee="self",
                source_account=SOURCE_MOFID,
                amount=self_amount,
                note="v63 self source regression",
            )
            v62._apply_full(p1, parsed_self)
            if int(v21.mellat_balance()) != mellat_before:
                raise CommandError("V63 Mofid self payment changed Mellat")
            if int(source_balance(SOURCE_MOFID)) != mofid_before - self_amount:
                raise CommandError("V63 Mofid self payment did not reduce Mofid exactly")
            self_after = self_tracking_row(create=False)
            if not self_after or int(self_after.amount or 0) != self_before + self_amount:
                raise CommandError("V63 self tracking did not increase exactly")
            if int(manual_accounts_capital_total()) != capital_before - self_amount:
                raise CommandError("V63 self payment did not reduce capital-account total exactly")

            v62._reverse_full(p1)
            if int(v21.mellat_balance()) != mellat_before:
                raise CommandError("V63 self reverse changed Mellat")
            if int(source_balance(SOURCE_MOFID)) != mofid_before:
                raise CommandError("V63 self reverse did not restore Mofid")
            if int(manual_accounts_capital_total()) != capital_before:
                raise CommandError("V63 self reverse did not restore capital-account total")
            p1.delete()

            # Supplier prepayment from Mofid: cash moves from Mofid into supplier receivable;
            # Mellat stays untouched and total capital-account value stays unchanged.
            supplier_amount = 2_000_000
            supplier_post = QueryDict("", mutable=True)
            supplier_post.update({
                "date": "1405/06/16",
                "payee": "fabric",
                "source_account": SOURCE_MOFID,
                "amount": str(supplier_amount),
                "note": "v63-temp-fabric-supplier",
            })
            parsed_supplier = v62._parse_payment_post(supplier_post)
            mellat_before_2 = int(v21.mellat_balance())
            mofid_before_2 = int(source_balance(SOURCE_MOFID))
            capital_before_2 = int(manual_accounts_capital_total())
            p2 = BusinessPayment.objects.create(
                date=date.today(),
                payee="fabric",
                source_account=SOURCE_MOFID,
                amount=supplier_amount,
                note="v63-temp-fabric-supplier",
            )
            v62._apply_full(p2, parsed_supplier)
            if int(v21.mellat_balance()) != mellat_before_2:
                raise CommandError("V63 Mofid fabric payment changed Mellat")
            if int(source_balance(SOURCE_MOFID)) != mofid_before_2 - supplier_amount:
                raise CommandError("V63 Mofid fabric payment did not reduce Mofid exactly")
            if int(manual_accounts_capital_total()) != capital_before_2:
                raise CommandError("V63 supplier prepayment changed total capital-account value")

            v62._reverse_full(p2)
            if int(v21.mellat_balance()) != mellat_before_2:
                raise CommandError("V63 fabric reverse changed Mellat")
            if int(source_balance(SOURCE_MOFID)) != mofid_before_2:
                raise CommandError("V63 fabric reverse did not restore Mofid")
            if int(manual_accounts_capital_total()) != capital_before_2:
                raise CommandError("V63 fabric reverse did not restore capital-account value")
            p2.delete()

            transaction.set_rollback(True)

        after = self._state()
        if before != after:
            raise CommandError(f"V63 regression left persistent data changed: {before} != {after}")

        self.stdout.write("PAYMENT SOURCE UI: از = ملت / مفید")
        self.stdout.write("HISTORICAL PAYMENTS: default source remains Mellat")
        self.stdout.write("MOFID PAYMENT: Mofid decreases exactly; Mellat is unchanged")
        self.stdout.write("SELF FROM MOFID: capital decreases exactly and self tracking increases")
        self.stdout.write("FABRIC PREPAYMENT FROM MOFID: source moves to supplier receivable without touching Mellat")
        self.stdout.write("EDIT/DELETE SOURCE ROUTING: reverse helpers restore original selected source")
        self.stdout.write("NO TEST DATA CHANGED")
        self.stdout.write(self.style.SUCCESS("SUCCESS: PAYMENT SOURCE V63 CHECK PASSED"))
