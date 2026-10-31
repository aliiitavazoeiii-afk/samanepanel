from django.core.management.base import BaseCommand, CommandError
from django.template.loader import get_template
from django.urls import resolve, reverse

from core.business_tools_v22 import _invoice_value, _purchase_signature
from core.material_purchase_v14 import purchase_data_for_payment
from core.models import BusinessPayment


class Command(BaseCommand):
    help = "Verify v22 payment routing, templates, invoice-vs-paid semantics, and safe metadata edit prerequisites."

    def handle(self, *args, **options):
        errors = []

        expected_routes = {
            "payments": "core.business_tools_v22",
            "payment_add": "core.business_tools_v22",
        }
        for name, expected in expected_routes.items():
            actual = resolve(reverse(name)).func.__module__
            self.stdout.write(f"route {name} -> {actual}")
            if actual != expected:
                errors.append(f"{name}: expected {expected}, got {actual}")

        for name in ["payment_update", "payment_delete"]:
            actual = resolve(reverse(name, args=[1])).func.__module__
            self.stdout.write(f"route {name} -> {actual}")
            if actual != "core.business_tools_v22":
                errors.append(f"{name}: expected core.business_tools_v22, got {actual}")

        for template in ["core/payments_v22.html", "core/_payment_edit_v22.html"]:
            try:
                get_template(template)
                self.stdout.write(f"template OK: {template}")
            except Exception as exc:
                errors.append(f"template {template}: {exc}")

        elastic_example = {
            "k": "elastic", "m": "black", "t": "مشکی",
            "q16": "10", "p16": 2600000, "q25": "0", "p25": 0, "n": "کش فروش",
        }
        invoice = _invoice_value(elastic_example)
        self.stdout.write(f"10kg x 2,600,000 invoice = {invoice}")
        if invoice != 26000000:
            errors.append(f"elastic invoice example expected 26000000, got {invoice}")

        same_with_new_note = dict(elastic_example)
        same_with_new_note["n"] = "توضیح جدید"
        if _purchase_signature(elastic_example) != _purchase_signature(same_with_new_note):
            errors.append("purchase signature must ignore note-only edits")

        changed_price = dict(elastic_example)
        changed_price["p16"] = 2500000
        if _purchase_signature(elastic_example) == _purchase_signature(changed_price):
            errors.append("purchase signature must detect unit-price changes")

        purchases = 0
        for payment in BusinessPayment.objects.filter(payee__in=["fabric", "elastic"]):
            data = purchase_data_for_payment(payment)
            if data:
                purchases += 1
                if _invoice_value(data) <= 0:
                    errors.append(f"material purchase {payment.id}: non-positive invoice value")
        self.stdout.write(f"existing material purchases checked = {purchases}")

        if errors:
            for error in errors:
                self.stderr.write(self.style.ERROR(error))
            raise CommandError("V22 PAYMENT WORKFLOW CHECK FAILED")
        self.stdout.write(self.style.SUCCESS("V22 PAYMENT WORKFLOW CHECK OK"))