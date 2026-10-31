from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

from core import material_report_v20 as v20
from core.material_report_v14 import _tailor_row
from core.models import AppSetting, Brand, InventoryMovement, MaterialReportBlock


MARKER_PREFIX = "novani_wage_repair_v34_block_"


class Command(BaseCommand):
    help = "Repair missing tailor wage for Novani output-v21 movements without touching inventory."

    def add_arguments(self, parser):
        parser.add_argument("--block-id", type=int)
        parser.add_argument("--expected-pieces", type=int)
        parser.add_argument("--expected-wage", type=int)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        novani = Brand.objects.get(name="Novani")
        block_id = options.get("block_id")

        if block_id:
            block = MaterialReportBlock.objects.filter(id=block_id, brand=novani).first()
        else:
            candidate_ids = []
            for ref in InventoryMovement.objects.filter(
                brand=novani,
                movement_type=InventoryMovement.PRODUCTION,
                reference__endswith=":output-v21",
                delta__gt=0,
            ).order_by("-id").values_list("reference", flat=True):
                try:
                    candidate_ids.append(int(str(ref).split(":")[1]))
                except Exception:
                    continue
            block = MaterialReportBlock.objects.filter(id__in=candidate_ids, brand=novani).order_by("-id").first()

        if not block:
            raise CommandError("No Novani block with v21 output movements was found")

        reference = f"material-report:{block.id}:output-v21"
        pieces = int(
            InventoryMovement.objects.filter(
                brand=novani,
                movement_type=InventoryMovement.PRODUCTION,
                reference=reference,
                delta__gt=0,
            ).aggregate(v=Sum("delta"))["v"] or 0
        )
        if pieces <= 0:
            raise CommandError(f"Block #{block.id} has no positive v21 output movements")

        rate = int(v20._dozen_wage())
        wage = int(v20._wage_for_pieces(pieces, rate))
        marker = f"{MARKER_PREFIX}{block.id}"
        already = AppSetting.objects.filter(key=marker, value="1").exists()
        tailor = _tailor_row(create=False)
        tailor_before = int(tailor.amount or 0) if tailor else 0

        self.stdout.write(f"BLOCK_ID={block.id}")
        self.stdout.write(f"NOVANI_V21_PIECES={pieces}")
        self.stdout.write(f"DOZEN_WAGE={rate}")
        self.stdout.write(f"MISSING_WAGE={wage}")
        self.stdout.write(f"BLOCK_DELIVERY_WAGE_BEFORE={int(block.delivery_wage or 0)}")
        self.stdout.write(f"TAILOR_BEFORE={tailor_before}")
        self.stdout.write(f"REPAIR_ALREADY_APPLIED={1 if already else 0}")
        self.stdout.write("INVENTORY_CHANGE=0")
        self.stdout.write("RAW_MATERIAL_CHANGE=0")

        expected_pieces = options.get("expected_pieces")
        expected_wage = options.get("expected_wage")
        if expected_pieces is not None and pieces != expected_pieces:
            raise CommandError(f"piece guard failed: expected {expected_pieces}, found {pieces}")
        if expected_wage is not None and wage != expected_wage:
            raise CommandError(f"wage guard failed: expected {expected_wage}, calculated {wage}")
        if already:
            raise CommandError(f"Block #{block.id} wage repair was already applied; refusing duplicate deduction")

        if not options["apply"]:
            self.stdout.write("DRY RUN ONLY: NO DATA CHANGED")
            return

        with transaction.atomic():
            block = MaterialReportBlock.objects.select_for_update().get(pk=block.pk)
            if AppSetting.objects.select_for_update().filter(key=marker, value="1").exists():
                raise CommandError("repair marker appeared concurrently; refusing duplicate deduction")

            # Saved wage follows actual delivered pieces only; cut quantity is irrelevant here.
            block.delivery_wage = wage
            block.save(update_fields=["delivery_wage", "updated_at"])

            v20._adjust_tailor_balance(-wage)
            AppSetting.objects.update_or_create(
                key=marker,
                defaults={"value": "1", "label": f"Novani missing wage repaired for material block {block.id}"},
            )
            tailor_after_obj = _tailor_row(create=False)
            tailor_after = int(tailor_after_obj.amount or 0) if tailor_after_obj else 0
            if tailor_after != tailor_before - wage:
                raise CommandError(
                    f"tailor verification failed: expected {tailor_before - wage}, found {tailor_after}"
                )

        self.stdout.write(f"BLOCK_DELIVERY_WAGE_AFTER={wage}")
        self.stdout.write(f"TAILOR_AFTER={tailor_before - wage}")
        self.stdout.write("SUCCESS: NOVANI MISSING WAGE V34 REPAIRED; INVENTORY UNCHANGED")
