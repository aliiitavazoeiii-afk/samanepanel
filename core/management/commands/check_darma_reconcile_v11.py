from django.core.management.base import BaseCommand, CommandError

from core.management.commands.reconcile_darma_excel_v11 import EXPECTED_QTY, EXPECTED_VALUE


class Command(BaseCommand):
    help = "Verify embedded Darma Excel reference totals."

    def handle(self, *args, **options):
        if EXPECTED_QTY != 14311:
            raise CommandError(f"Unexpected Darma reference qty: {EXPECTED_QTY}")
        if EXPECTED_VALUE != 872971000:
            raise CommandError(f"Unexpected Darma reference value: {EXPECTED_VALUE}")
        self.stdout.write(self.style.SUCCESS("DARMA RECONCILE V11 REFERENCE OK"))
