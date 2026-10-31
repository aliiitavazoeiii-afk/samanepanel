import inspect

from django.core.management.base import BaseCommand, CommandError
from django.template.loader import get_template
from django.urls import resolve, reverse

from core import daily_order_views_v8
from core.finance_excel_v9 import sale_receivable_value
from core.models import SaleLine


class Command(BaseCommand):
    help = "Verify dashboard/daily-report UI and Digikala finance hooks for sales fix v10."

    def handle(self, *args, **options):
        errors = []

        for template_name in ["core/dashboard_excel.html", "core/daily_report.html", "core/daily_report_v8.html"]:
            try:
                template = get_template(template_name)
                source = template.template.source
                self.stdout.write(f"template OK: {template_name}")
                if template_name.endswith("dashboard_excel.html") and "dir=\"ltr\"" not in source:
                    errors.append("dashboard chart is not forced LTR")
                if template_name.endswith("daily_report.html") and "brand-summary-table" not in source:
                    errors.append("daily report fixed brand summary table is missing")
            except Exception as exc:
                errors.append(f"template {template_name}: {exc}")

        try:
            url = reverse("daily_order_import", args=[1])
            resolved = resolve(url)
            if resolved.func.__module__ != "core.daily_order_views_v8":
                errors.append("daily_order_import route is not using daily_order_views_v8")
            else:
                self.stdout.write("route OK: daily_order_import")
        except Exception as exc:
            errors.append(f"route daily_order_import: {exc}")

        source = inspect.getsource(daily_order_views_v8.import_daily_orders)
        if "sync_sale_receivable" not in source:
            errors.append("Excel upload does not sync Digikala receivable")
        else:
            self.stdout.write("Digikala upload finance sync OK")

        try:
            SaleLine.objects.count()
            sale_receivable_value
            self.stdout.write("sales finance models OK")
        except Exception as exc:
            errors.append(f"sales finance models: {exc}")

        if errors:
            for error in errors:
                self.stderr.write(self.style.ERROR(error))
            raise CommandError("Sales fix v10 preflight failed")

        self.stdout.write(self.style.SUCCESS("SALES FIX V10 OK"))
