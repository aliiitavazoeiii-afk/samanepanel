from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum
from django.http import QueryDict
from django.template.loader import get_template
from django.urls import resolve

from core import business_tools_v21 as v21
from core import business_tools_v61 as v61
from core.models import BusinessPayment, ExcelManualRow, InventoryMovement, RawMaterialStock, StockBalance


class Command(BaseCommand):
    help = "V61 regression: tracked personal spending reduces only Mellat/capital and reverses exactly."

    def _state(self):
        return {
            "payments": BusinessPayment.objects.count(),
            "mellat": int(v21.mellat_balance()),
            "stock_qty": int(StockBalance.objects.aggregate(v=Sum("qty"))["v"] or 0),
            "raw_qty": str(RawMaterialStock.objects.filter(active=True).aggregate(v=Sum("quantity"))["v"] or 0),
            "movements": InventoryMovement.objects.count(),
            "manual_rows": ExcelManualRow.objects.count(),
        }

    def handle(self, *args, **options):
        try:
            get_template("core/payments_v61.html")
        except Exception as exc:
            raise CommandError(f"V61 payments template failed to compile: {exc}") from exc

        source_checks = {
            "core/business_tools_v61.py": (
                'SELF_PAYEE = "self"',
                'PAYEE_CHOICES.append((SELF_PAYEE, "خودم"))',
                'self_month_total',
                'self_total',
            ),
            "templates/core/payments_v61.html": (
                'id="self-payment-v61"',
                'name="payee" value="self"',
                'خرج خودم این ماه',
                'جمع کل خرج خودم',
            ),
        }
        for relative, markers in source_checks.items():
            text = (Path(settings.BASE_DIR) / relative).read_text(encoding="utf-8")
            for marker in markers:
                if marker not in text:
                    raise CommandError(f"V61 source marker missing: {relative}: {marker}")

        route_expectations = {
            "/payments/": v61.payments,
            "/payments/add/": v61.payment_add,
            "/payments/1/edit/": v61.payment_update,
            "/payments/1/delete/": v61.payment_delete,
        }
        for url, expected in route_expectations.items():
            active = resolve(url).func
            if active is not expected:
                raise CommandError(f"V61 route mismatch: {url} is not the V61 callable")

        if v61.PAYEE_LABELS.get(v61.SELF_PAYEE) != "خودم":
            raise CommandError("V61 personal payee label is not registered")

        post = QueryDict("", mutable=True)
        post["date"] = "1405/06/15"
        post["payee"] = v61.SELF_PAYEE
        post["amount"] = "1234567"
        post["note"] = "v61 regression"
        parsed = v61._parse_payment_post(post)
        if parsed["payee"] != v61.SELF_PAYEE or int(parsed["paid"]) != 1_234_567:
            raise CommandError("V61 personal payment parser returned wrong data")
        if parsed["purchase"] is not None:
            raise CommandError("V61 personal payment must never create purchase data")

        before = self._state()
        with transaction.atomic():
            payment = BusinessPayment.objects.create(
                date=date.today(),
                payee=v61.SELF_PAYEE,
                amount=1_234_567,
                note="v61 regression",
            )
            mellat_before = int(v21.mellat_balance())
            v61.v60._apply_full(payment, parsed)
            mellat_after = int(v21.mellat_balance())
            if mellat_after != mellat_before - 1_234_567:
                raise CommandError(
                    f"V61 personal spend Mellat delta wrong: {mellat_after - mellat_before}"
                )

            if int(StockBalance.objects.aggregate(v=Sum("qty"))["v"] or 0) != before["stock_qty"]:
                raise CommandError("V61 personal spend changed finished inventory quantity")
            if str(RawMaterialStock.objects.filter(active=True).aggregate(v=Sum("quantity"))["v"] or 0) != before["raw_qty"]:
                raise CommandError("V61 personal spend changed raw-material quantity")
            if InventoryMovement.objects.count() != before["movements"]:
                raise CommandError("V61 personal spend created inventory movement")

            v61.v60._reverse_full(payment)
            if int(v21.mellat_balance()) != mellat_before:
                raise CommandError("V61 personal spend reverse did not restore Mellat exactly")
            payment.delete()
            transaction.set_rollback(True)

        after = self._state()
        if before != after:
            raise CommandError(f"V61 regression left persistent data changed: {before} != {after}")

        self.stdout.write("SELF PAYEE: registered as «خودم»")
        self.stdout.write("SELF SPEND: reduces Mellat by exact amount")
        self.stdout.write("SELF SPEND: no stock/raw/inventory movement side effects")
        self.stdout.write("SELF DELETE/REVERSE: restores Mellat exactly")
        self.stdout.write("SELF TOTALS: monthly + lifetime totals exposed to payments UI")
        self.stdout.write("NO TEST DATA CHANGED")
        self.stdout.write(self.style.SUCCESS("SUCCESS: SELF SPEND V61 CHECK PASSED"))
