from django.core.management.base import BaseCommand, CommandError
from django.template.loader import get_template
from django.urls import resolve, reverse

from core.models import ExcelManualRow


class Command(BaseCommand):
    help = "Verify v21 editable daily report and prepayment/payment workflows."

    def handle(self, *args, **options):
        errors = []

        for template_name in ("core/daily_report_v21.html", "core/payments_v21.html"):
            try:
                get_template(template_name)
                self.stdout.write(f"TEMPLATE OK = {template_name}")
            except Exception as exc:
                errors.append(f"template {template_name}: {exc}")

        expected = {
            "daily_sale_price_update": "core.daily_report_actions_v21",
            "daily_sale_line_delete": "core.daily_report_actions_v21",
            "payments": "core.business_tools_v21",
            "payment_add": "core.business_tools_v21",
            "payment_update": "core.business_tools_v21",
            "payment_delete": "core.business_tools_v21",
            "receipt_add": "core.business_tools_v21",
            "receipt_update": "core.business_tools_v21",
            "receipt_delete": "core.business_tools_v21",
        }
        kwargs = {
            "daily_sale_price_update": {"line_id": 1},
            "daily_sale_line_delete": {"line_id": 1},
            "payment_update": {"payment_id": 1},
            "payment_delete": {"payment_id": 1},
            "receipt_update": {"receipt_id": 1},
            "receipt_delete": {"receipt_id": 1},
        }
        for name, module in expected.items():
            try:
                path = reverse(name, kwargs=kwargs.get(name))
                resolved = resolve(path)
                actual = resolved.func.__module__
                self.stdout.write(f"ROUTE {name} = {actual}")
                if actual != module:
                    errors.append(f"route {name} expected {module}, got {actual}")
            except Exception as exc:
                errors.append(f"route {name}: {exc}")

        # The prepayment asset must live in the same section that report_v9
        # includes in capital as 'ریز حساب‌ها'. This is a schema-only check;
        # no business data is written by this command.
        if ExcelManualRow.ACCOUNTS != "accounts":
            errors.append("ExcelManualRow.ACCOUNTS changed unexpectedly")
        else:
            self.stdout.write("PREPAYMENT ASSET SECTION = accounts / ریز حساب‌ها")

        if errors:
            for error in errors:
                self.stderr.write(self.style.ERROR(error))
            raise CommandError("V21 workflow preflight failed")

        self.stdout.write(self.style.SUCCESS("V21 DAILY EDIT + PREPAYMENT + EDITABLE CASHFLOW OK"))
