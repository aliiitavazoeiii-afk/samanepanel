from datetime import date
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum
from django.http import QueryDict
from django.template.loader import get_template
from django.urls import resolve

from core import business_tools_v21 as v21
from core import business_tools_v62 as v62
from core.models import BusinessPayment, ExcelManualRow, InventoryMovement, RawMaterialStock, StockBalance
from core.self_spend_v62 import (
    SELF_ACCOUNT_NOTE_PREFIX,
    SELF_ACCOUNT_TITLE,
    SELF_PAYEE,
    manual_accounts_capital_total,
    self_tracking_row,
)


class Command(BaseCommand):
    help = "V62 regression: self is one normal payment target, Pedram removed, self tracking account excluded from capital."

    def _state(self):
        self_row = self_tracking_row(create=False)
        return {
            "payments": BusinessPayment.objects.count(),
            "mellat": int(v21.mellat_balance()),
            "self_rows": ExcelManualRow.objects.filter(
                section=ExcelManualRow.ACCOUNTS,
                active=True,
                note__startswith=SELF_ACCOUNT_NOTE_PREFIX,
            ).count(),
            "self_amount": int(self_row.amount or 0) if self_row else 0,
            "capital_accounts": int(manual_accounts_capital_total()),
            "stock_qty": int(StockBalance.objects.aggregate(v=Sum("qty"))["v"] or 0),
            "raw_qty": str(
                RawMaterialStock.objects.filter(active=True).aggregate(v=Sum("quantity"))["v"]
                or Decimal("0")
            ),
            "movements": InventoryMovement.objects.count(),
        }

    def handle(self, *args, **options):
        for template_name in ("core/payments_v60.html", "core/payments_v62.html", "core/report_excel_v45.html"):
            try:
                get_template(template_name)
            except Exception as exc:
                raise CommandError(f"V62 template failed to compile: {template_name}: {exc}") from exc

        source_checks = {
            "core/business_tools_v62.py": (
                'PAYEE_CHOICES = [(key, label) for key, label in v60.PAYEE_CHOICES if key != "pedram"]',
                'PAYEE_CHOICES.append((SELF_PAYEE, "خودم"))',
                "adjust_self_tracking(int(payment.amount or 0))",
                "adjust_self_tracking(-int(payment.amount or 0))",
            ),
            "core/self_spend_v62.py": (
                'SELF_ACCOUNT_TITLE = "خودم"',
                "SELF_ACCOUNT_NOTE_PREFIX",
                "exclude(note__startswith=SELF_ACCOUNT_NOTE_PREFIX)",
            ),
            "templates/core/payments_v62.html": ("{% extends 'core/payments_v60.html' %}",),
            "core/report_v10.py": (
                "capital_accounts_queryset",
                "accounts_rows = list",
                "حساب «خودم»",
            ),
        }
        for relative, markers in source_checks.items():
            text = (Path(settings.BASE_DIR) / relative).read_text(encoding="utf-8")
            for marker in markers:
                if marker not in text:
                    raise CommandError(f"V62 source marker missing: {relative}: {marker}")

        template_text = (Path(settings.BASE_DIR) / "templates/core/payments_v62.html").read_text(encoding="utf-8")
        if "selfPaymentPanelV61" in template_text or "self-payment-v61" in template_text:
            raise CommandError("V62 dedicated self-spend panel still exists")

        route_expectations = {
            "/payments/": "core.business_tools_v62",
            "/payments/add/": "core.business_tools_v62",
            "/payments/1/edit/": "core.business_tools_v62",
            "/payments/1/delete/": "core.business_tools_v62",
            "/report/": "core.report_v10",
            "/report/manual/": "core.report_v10",
        }
        for url, expected in route_expectations.items():
            module = resolve(url).func.__module__
            if module != expected:
                raise CommandError(f"V62 route mismatch: {url} -> {module}, expected {expected}")

        choices = dict(v62.PAYEE_CHOICES)
        if "pedram" in choices:
            raise CommandError("V62 Pedram is still offered as a new payment target")
        if choices.get(SELF_PAYEE) != "خودم":
            raise CommandError("V62 self payment target is missing")
        if v62.PAYEE_LABELS.get("pedram") != "خیاط":
            raise CommandError("V62 legacy Pedram rows are not displayed as tailor")

        legacy_post = QueryDict("", mutable=True)
        legacy_post["date"] = "1405/06/15"
        legacy_post["payee"] = "pedram"
        legacy_post["amount"] = "1000"
        legacy_post["note"] = "legacy"
        if v62._parse_payment_post(legacy_post)["payee"] != "tailor":
            raise CommandError("V62 legacy Pedram input did not normalize to tailor")

        amount = 1_234_567
        post = QueryDict("", mutable=True)
        post["date"] = "1405/06/15"
        post["payee"] = SELF_PAYEE
        post["amount"] = str(amount)
        post["note"] = "v62 regression"
        parsed = v62._parse_payment_post(post)
        if parsed["payee"] != SELF_PAYEE or int(parsed["paid"]) != amount:
            raise CommandError("V62 self payment parser returned wrong data")
        if parsed["purchase"] is not None:
            raise CommandError("V62 self payment must never create purchase data")

        before = self._state()
        with transaction.atomic():
            payment = BusinessPayment.objects.create(
                date=date.today(),
                payee=SELF_PAYEE,
                amount=amount,
                note="v62 regression",
            )
            mellat_before = int(v21.mellat_balance())
            capital_accounts_before = int(manual_accounts_capital_total())
            row_before = self_tracking_row(create=False)
            self_before = int(row_before.amount or 0) if row_before else 0

            v62._apply_full(payment, parsed)

            if int(v21.mellat_balance()) != mellat_before - amount:
                raise CommandError("V62 self payment did not reduce Mellat exactly")
            row_after = self_tracking_row(create=False)
            if row_after is None:
                raise CommandError("V62 self tracking account was not created")
            if row_after.title != SELF_ACCOUNT_TITLE:
                raise CommandError("V62 self tracking account title is wrong")
            if int(row_after.amount or 0) != self_before + amount:
                raise CommandError("V62 self tracking account did not increase exactly")
            if int(manual_accounts_capital_total()) != capital_accounts_before - amount:
                raise CommandError(
                    "V62 capital-account total did not fall by exact self payment; tracking row may be counted as asset"
                )
            if int(StockBalance.objects.aggregate(v=Sum("qty"))["v"] or 0) != before["stock_qty"]:
                raise CommandError("V62 self payment changed finished inventory")
            if str(RawMaterialStock.objects.filter(active=True).aggregate(v=Sum("quantity"))["v"] or 0) != before["raw_qty"]:
                raise CommandError("V62 self payment changed raw materials")
            if InventoryMovement.objects.count() != before["movements"]:
                raise CommandError("V62 self payment created inventory movement")

            v62._reverse_full(payment)
            if int(v21.mellat_balance()) != mellat_before:
                raise CommandError("V62 self reverse did not restore Mellat")
            row_reversed = self_tracking_row(create=False)
            if int(row_reversed.amount or 0) != self_before:
                raise CommandError("V62 self reverse did not restore tracking account")
            if int(manual_accounts_capital_total()) != capital_accounts_before:
                raise CommandError("V62 self reverse did not restore capital-account total")
            payment.delete()
            transaction.set_rollback(True)

        after = self._state()
        if before != after:
            raise CommandError(f"V62 regression left persistent data changed: {before} != {after}")

        self.stdout.write("PAYMENTS UI: dedicated personal-spend panel removed")
        self.stdout.write("PAYEE LIST: خودم added to normal payment target list")
        self.stdout.write("PAYEE LIST: Pedram removed; legacy Pedram normalizes/displays as tailor")
        self.stdout.write("SELF PAYMENT: Mellat decreases by exact amount")
        self.stdout.write("SELF ACCOUNT: حساب‌ها / خودم increases by exact amount")
        self.stdout.write("CAPITAL: self tracking row excluded, so capital decreases by exact amount")
        self.stdout.write("SELF REVERSE: Mellat + tracking account restore exactly")
        self.stdout.write("NO STOCK/RAW/INVENTORY SIDE EFFECTS")
        self.stdout.write("NO TEST DATA CHANGED")
        self.stdout.write(self.style.SUCCESS("SUCCESS: SELF PAYEE ACCOUNT V62 CHECK PASSED"))
