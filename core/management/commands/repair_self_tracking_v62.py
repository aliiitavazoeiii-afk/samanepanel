from django.core.management.base import BaseCommand, CommandError

from core.models import BusinessPayment
from core.self_spend_v62 import (
    SELF_PAYEE,
    expected_self_total,
    reconcile_self_tracking,
    self_tracking_row,
)


class Command(BaseCommand):
    help = "Dry-run/apply V62 reconciliation of historical self payments into the visible non-capital حساب‌ها/خودم tracker."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        expected = int(expected_self_total())
        current_row = self_tracking_row(create=False)
        current = int(current_row.amount or 0) if current_row else 0
        count = BusinessPayment.objects.filter(payee=SELF_PAYEE).count()

        self.stdout.write(f"SELF_PAYMENT_COUNT={count}")
        self.stdout.write(f"SELF_PAYMENT_TOTAL={expected}")
        self.stdout.write(f"SELF_TRACKING_CURRENT={current}")
        self.stdout.write(f"SELF_TRACKING_EXPECTED={expected}")
        self.stdout.write(f"SELF_TRACKING_DELTA={expected-current}")

        if not options["apply"]:
            self.stdout.write("DRY_RUN=YES")
            return

        result = reconcile_self_tracking()
        row = self_tracking_row(create=False)
        final = int(row.amount or 0) if row else 0
        if final != expected:
            raise CommandError(f"V62 self tracking reconciliation failed: {final} != {expected}")

        self.stdout.write(f"SELF_TRACKING_CREATED={'YES' if result['created'] else 'NO'}")
        self.stdout.write(f"SELF_TRACKING_FINAL={final}")
        self.stdout.write(self.style.SUCCESS("SUCCESS: SELF TRACKING V62 RECONCILED"))
