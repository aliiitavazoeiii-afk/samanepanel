from django.core.management.base import BaseCommand, CommandError
from django.urls import resolve, reverse

from core.finance_excel_v9 import digikala_receivable_total
from core.models import Account, BusinessPayment, DigikalaSettlement


class Command(BaseCommand):
    help = "Verify Digikala finance routes/models across supported payment controllers."

    def handle(self, *args, **options):
        errors = []
        finance_modules = {"core.business_tools_v9", "core.business_tools_v13", "core.business_tools_v14"}
        checks = {
            "report": {"core.report_v9"},
            "manual_report_action": {"core.report_v9"},
            "payments": finance_modules,
            "payment_add": finance_modules,
            "receipt_add": finance_modules,
            "calculator": finance_modules,
        }
        route_args = {"receipt_add": [], "payment_add": []}
        for name, allowed_modules in checks.items():
            try:
                url = reverse(name, args=route_args.get(name, []))
                actual = resolve(url).func.__module__
                if actual not in allowed_modules:
                    expected = " or ".join(sorted(allowed_modules))
                    errors.append(f"{name} points to {actual}, expected {expected}")
                else:
                    self.stdout.write(f"route OK: {name} -> {actual}")
            except Exception as exc:
                errors.append(f"route {name}: {exc}")

        try:
            Account.objects.get_or_create(
                key=Account.DIGIKALA,
                defaults={"title": "دیجی‌کالا", "opening_balance": 0},
            )
            BusinessPayment.objects.count()
            DigikalaSettlement.objects.count()
            digikala_receivable_total()
            self.stdout.write("finance models OK")
        except Exception as exc:
            errors.append(f"finance models: {exc}")

        if errors:
            for error in errors:
                self.stderr.write(self.style.ERROR(error))
            raise CommandError("Finance flow preflight failed")

        self.stdout.write(self.style.SUCCESS("FINANCE FLOW V9/V13/V14 OK"))
