from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.dateutils import format_jalali, parse_jalali_date
from core.models import InventoryMovement, TakvinPurchase
from core.takvin_pricing_v17 import takvin_cost_for
from core.takvin_v5 import PREFIX, _apply_purchase_stock, _purchase_movement


class Command(BaseCommand):
    help = "Repair Excel-web Takvin purchases that increased debt but never added stock."

    def add_arguments(self, parser):
        parser.add_argument("--date", dest="jalali_date", default="")
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        raw_date = (options.get("jalali_date") or "").strip()
        target_date = parse_jalali_date(raw_date) if raw_date else date.today()
        rows = list(
            TakvinPurchase.objects.filter(
                date=target_date,
                note__startswith=PREFIX,
            )
            .select_related("size", "color")
            .order_by("id")
        )

        missing = []
        already_ok = []
        for row in rows:
            try:
                movement = _purchase_movement(row, lock=False)
            except Exception as exc:
                raise CommandError(str(exc)) from exc
            if movement is None:
                if not row.applied:
                    raise CommandError(
                        f"TakvinPurchase #{row.id} is unapplied and has no movement; "
                        "repair command refuses to guess its intended state."
                    )
                missing.append(row)
            else:
                already_ok.append(row)

        added_qty = sum(int(row.qty or 0) for row in missing)
        expected_finished_delta = sum(
            int(row.qty or 0) * int(takvin_cost_for(row.size))
            for row in missing
        )
        debt_value = sum(int(row.total_cost or 0) for row in rows)

        self.stdout.write(f"TAKVIN_REPAIR_DATE={format_jalali(target_date)}")
        self.stdout.write(f"TAKVIN_REPAIR_ROWS={len(rows)}")
        self.stdout.write(f"TAKVIN_REPAIR_ALREADY_OK={len(already_ok)}")
        self.stdout.write(f"TAKVIN_REPAIR_MISSING_ROWS={len(missing)}")
        self.stdout.write(f"TAKVIN_REPAIR_ADD_QTY={added_qty}")
        self.stdout.write(f"TAKVIN_REPAIR_EXPECTED_FINISHED_DELTA={expected_finished_delta}")
        self.stdout.write(f"TAKVIN_REPAIR_DAY_DEBT_VALUE={debt_value}")

        if not options.get("apply"):
            self.stdout.write("DRY_RUN=1")
            if missing:
                self.stdout.write(
                    "Missing purchase movements detected. Re-run with --apply to add only the missing Takvin HOME stock."
                )
            else:
                self.stdout.write("No missing Takvin purchase stock found for this date.")
            return

        if not missing:
            self.stdout.write("TAKVIN_REPAIR_APPLIED=0")
            self.stdout.write(self.style.SUCCESS("SUCCESS: TAKVIN PURCHASE STOCK V59 REPAIR ALREADY CLEAN"))
            return

        with transaction.atomic():
            # Re-lock the exact rows before applying. No debt/account change occurs.
            locked = list(
                TakvinPurchase.objects.select_for_update()
                .filter(id__in=[row.id for row in missing])
                .select_related("size", "color")
                .order_by("id")
            )
            if len(locked) != len(missing):
                raise CommandError("Takvin purchase rows changed during repair; nothing applied.")
            for row in locked:
                if _purchase_movement(row, lock=True) is not None:
                    continue
                _apply_purchase_stock(row, allow_legacy_applied_missing=True)

        # Verify exact movements now exist.
        repaired = 0
        for row in missing:
            row.refresh_from_db()
            movement = _purchase_movement(row, lock=False)
            if movement is None:
                raise CommandError(f"Repair verification failed for TakvinPurchase #{row.id}")
            repaired += 1

        self.stdout.write(f"TAKVIN_REPAIR_APPLIED={repaired}")
        self.stdout.write(
            self.style.SUCCESS("SUCCESS: TAKVIN PURCHASE STOCK V59 REPAIR APPLIED")
        )
