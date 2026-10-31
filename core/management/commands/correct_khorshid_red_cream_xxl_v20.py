from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

from core.brand_colors import norm
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import Brand, Color, InventoryMovement, Size, StockBalance, StockLocation


REFERENCE = "physical-correction-khorshid-red-cream-xxl-v20"
SIZE_NAME = "XXL"
EXPECTED_RED_BEFORE = 140
EXPECTED_CREAM_BEFORE = 260
TARGET_RED = 0
TARGET_CREAM = 400


def _find_color(brand, wanted):
    colors = list(Color.objects.filter(stockbalance__brand=brand).distinct().order_by("id"))
    matches = [c for c in colors if norm(c.name) == norm(wanted)]
    if len(matches) != 1:
        raise CommandError(f"Expected exactly one Darma color for {wanted}; found {len(matches)}")
    return matches[0]


def _darma_total(brand):
    return int(StockBalance.objects.filter(brand=brand).aggregate(v=Sum("qty"))["v"] or 0)


class Command(BaseCommand):
    help = "Correct the physical Khorshid XXL misclassification: red 140->0, cream 260->400. Dry-run by default."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Apply the two-cell correction atomically.")

    def handle(self, *args, **options):
        apply = bool(options["apply"])
        brand = Brand.objects.get(name="دارما")
        size = Size.objects.get(name=SIZE_NAME)
        location = StockLocation.objects.get(key=StockLocation.KHORSHID)
        red = _find_color(brand, "قرمز")
        cream = _find_color(brand, "کرم")

        red_row, _ = StockBalance.objects.get_or_create(
            brand=brand, size=size, color=red, location=location, defaults={"qty": 0}
        )
        cream_row, _ = StockBalance.objects.get_or_create(
            brand=brand, size=size, color=cream, location=location, defaults={"qty": 0}
        )

        red_before = int(red_row.qty or 0)
        cream_before = int(cream_row.qty or 0)
        total_before = _darma_total(brand)
        finished_before = int(finished_inventory_value_v17())

        self.stdout.write("=== KHORSHID XXL PHYSICAL CORRECTION V20 ===")
        self.stdout.write(f"قرمز / XXL / خورشید: {red_before} -> {TARGET_RED} (delta {TARGET_RED-red_before:+d})")
        self.stdout.write(f"کرم / XXL / خورشید: {cream_before} -> {TARGET_CREAM} (delta {TARGET_CREAM-cream_before:+d})")
        self.stdout.write(f"DARMA TOTAL BEFORE = {total_before}")
        self.stdout.write(f"FINISHED INVENTORY BEFORE = {finished_before}")

        if red_before == TARGET_RED and cream_before == TARGET_CREAM:
            self.stdout.write(self.style.SUCCESS("ALREADY CORRECT: no stock change needed."))
            return

        if red_before != EXPECTED_RED_BEFORE or cream_before != EXPECTED_CREAM_BEFORE:
            raise CommandError(
                "Current cells no longer match the known bad baseline. "
                f"Expected red={EXPECTED_RED_BEFORE}, cream={EXPECTED_CREAM_BEFORE}; "
                f"found red={red_before}, cream={cream_before}. Refusing to overwrite newer stock."
            )

        if not apply:
            self.stdout.write(self.style.WARNING("DRY RUN ONLY — rerun with --apply to commit."))
            return

        with transaction.atomic():
            red_locked = StockBalance.objects.select_for_update().get(pk=red_row.pk)
            cream_locked = StockBalance.objects.select_for_update().get(pk=cream_row.pk)
            if int(red_locked.qty or 0) != EXPECTED_RED_BEFORE or int(cream_locked.qty or 0) != EXPECTED_CREAM_BEFORE:
                raise CommandError("Stock changed after preflight; transaction aborted.")

            red_delta = TARGET_RED - int(red_locked.qty or 0)
            cream_delta = TARGET_CREAM - int(cream_locked.qty or 0)
            if red_delta + cream_delta != 0:
                raise CommandError("Correction would change total quantity; transaction aborted.")

            red_locked.qty = TARGET_RED
            cream_locked.qty = TARGET_CREAM
            red_locked.save(update_fields=["qty"])
            cream_locked.save(update_fields=["qty"])

            InventoryMovement.objects.create(
                movement_type=InventoryMovement.ADJUST,
                brand=brand,
                size=size,
                color=red,
                location=location,
                delta=red_delta,
                reference=REFERENCE,
            )
            InventoryMovement.objects.create(
                movement_type=InventoryMovement.ADJUST,
                brand=brand,
                size=size,
                color=cream,
                location=location,
                delta=cream_delta,
                reference=REFERENCE,
            )

            total_after = _darma_total(brand)
            if total_after != total_before:
                raise CommandError(
                    f"Darma total changed unexpectedly: before={total_before}, after={total_after}. Rolling back."
                )

        finished_after = int(finished_inventory_value_v17())
        self.stdout.write(f"DARMA TOTAL AFTER = {_darma_total(brand)}")
        self.stdout.write(f"FINISHED INVENTORY AFTER = {finished_after}")
        self.stdout.write(f"FINISHED VALUE DELTA = {finished_after-finished_before:+d}")
        self.stdout.write(self.style.SUCCESS("KHORSHID RED/CREAM XXL PHYSICAL CORRECTION APPLIED"))
