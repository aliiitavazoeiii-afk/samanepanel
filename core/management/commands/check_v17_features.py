from django.core.management.base import BaseCommand, CommandError

from core.models import Brand, TakvinCostRule
from core.takvin_pricing_v17 import DEFAULT_COSTS, TAKVIN_SIZES, takvin_cost_for


class Command(BaseCommand):
    help = "Verify Anbaresh brand and date-effective Takvin cost rules."

    def handle(self, *args, **options):
        errors = []
        if not Brand.objects.filter(name="انبارش", active=True).exists():
            errors.append("Anbaresh brand is missing or inactive")

        for size_name in TAKVIN_SIZES:
            rules = TakvinCostRule.objects.filter(size__name=size_name).order_by("effective_from")
            if not rules.exists():
                errors.append(f"Takvin {size_name} has no cost rule")
                continue
            current = takvin_cost_for(size_name)
            if current <= 0:
                errors.append(f"Takvin {size_name} current cost is not positive")
            self.stdout.write(f"TAKVIN {size_name}: rules={rules.count()} current={current}")

        if errors:
            for error in errors:
                self.stderr.write(self.style.ERROR(error))
            raise CommandError("V17 feature preflight failed")

        self.stdout.write(self.style.SUCCESS("V17 ANBARESH + TAKVIN COST RULES OK"))
