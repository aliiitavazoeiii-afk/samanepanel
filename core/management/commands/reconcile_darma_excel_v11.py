from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

from core.brand_colors import DARMA_BASE_COLORS, norm
from core.models import Brand, Color, InventoryMovement, Size, StockBalance, StockLocation


EXPECTED = {
    "M": {
        "مشکی": 312, "سفید": 340, "سرمه ای": 146, "صورتی": 163, "کرم": 348,
        "قرمز": 153, "زرد": -4, "طوسی": 100, "راه راه": 218, "راه راه طوسی": 218,
        "برعکس مشکی": 47, "برعکس سفید": 45, "برعکس سرمه ای": 0,
    },
    "L": {
        "مشکی": 664, "سفید": 251, "سرمه ای": 656, "صورتی": 690, "کرم": 1009,
        "قرمز": -34, "زرد": 80, "طوسی": 101, "راه راه": 107, "راه راه طوسی": 313,
        "برعکس مشکی": 83, "برعکس سفید": 72, "برعکس سرمه ای": 71,
    },
    "XL": {
        "مشکی": 716, "سفید": 164, "سرمه ای": 708, "صورتی": 94, "کرم": 616,
        "قرمز": -29, "زرد": 0, "طوسی": 32, "راه راه": 39, "راه راه طوسی": 444,
        "برعکس مشکی": 79, "برعکس سفید": 38, "برعکس سرمه ای": 67,
    },
    "XXL": {
        "مشکی": 791, "سفید": 351, "سرمه ای": 903, "صورتی": 547, "کرم": 702,
        "قرمز": -39, "زرد": 0, "طوسی": -3, "راه راه": 105, "راه راه طوسی": 439,
        "برعکس مشکی": 85, "برعکس سفید": 121, "برعکس سرمه ای": 72,
    },
    "3XL": {
        "مشکی": 95, "سفید": 152, "سرمه ای": 298, "صورتی": 53, "کرم": 124,
        "قرمز": 0, "زرد": 0, "طوسی": 10, "راه راه": 41, "راه راه طوسی": 100,
        "برعکس مشکی": 87, "برعکس سفید": 84, "برعکس سرمه ای": 76,
    },
    "4XL": {name: 0 for name in DARMA_BASE_COLORS},
}

EXPECTED_QTY = 14311
UNIT_COST = 61000
EXPECTED_VALUE = 872971000


def _brand_colors(brand):
    colors = list(Color.objects.filter(stockbalance__brand=brand).distinct())
    by_norm = {}
    for color in colors:
        by_norm.setdefault(norm(color.name), []).append(color)
    return by_norm


class Command(BaseCommand):
    help = "Compare/reconcile current Darma stock totals to the user's Excel reference snapshot."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Apply only the displayed per-cell deltas to HOME stock.")

    @transaction.atomic
    def handle(self, *args, **options):
        apply_changes = bool(options["apply"])
        brand = Brand.objects.get(name="دارما")
        home = StockLocation.objects.get(key=StockLocation.HOME)
        sizes = {s.name: s for s in Size.objects.filter(name__in=EXPECTED.keys())}
        colors_by_norm = _brand_colors(brand)

        missing = []
        diffs = []
        current_reference_qty = 0
        expected_reference_qty = 0

        self.stdout.write("=== DARMA EXCEL RECONCILE V11 ===")
        for size_name, expected_colors in EXPECTED.items():
            size = sizes.get(size_name)
            if not size:
                missing.append(f"size {size_name}")
                continue
            for color_name, target in expected_colors.items():
                color_list = colors_by_norm.get(norm(color_name), [])
                if not color_list:
                    missing.append(f"color {color_name}")
                    continue
                color_ids = [c.id for c in color_list]
                current = int(
                    StockBalance.objects.filter(brand=brand, size=size, color_id__in=color_ids)
                    .aggregate(v=Sum("qty"))["v"] or 0
                )
                current_reference_qty += current
                expected_reference_qty += int(target)
                delta = int(target) - current
                if delta:
                    diffs.append((size_name, color_name, current, int(target), delta, color_list[0]))
                    self.stdout.write(
                        f"{size_name:4} | {color_name:18} | current={current:6} | expected={int(target):6} | delta={delta:+6}"
                    )

        if missing:
            raise CommandError("Missing catalog rows: " + ", ".join(missing))

        base_norms = {norm(x) for x in DARMA_BASE_COLORS}
        extra_rows = []
        for row in (
            StockBalance.objects.filter(brand=brand)
            .values("color_id", "color__name")
            .annotate(qty=Sum("qty"))
        ):
            if norm(row["color__name"]) not in base_norms and int(row["qty"] or 0) != 0:
                extra_rows.append((row["color__name"], int(row["qty"] or 0)))

        self.stdout.write(f"REFERENCE CURRENT QTY = {current_reference_qty}")
        self.stdout.write(f"REFERENCE TARGET QTY  = {expected_reference_qty}")
        self.stdout.write(f"REFERENCE DELTA       = {expected_reference_qty - current_reference_qty:+d}")
        self.stdout.write(f"TARGET VALUE          = {EXPECTED_VALUE}")
        if extra_rows:
            self.stdout.write(self.style.WARNING("Non-base Darma stock detected:"))
            for name, qty in extra_rows:
                self.stdout.write(self.style.WARNING(f"  {name}: {qty:+d}"))

        if expected_reference_qty != EXPECTED_QTY:
            raise CommandError(f"Embedded Excel snapshot total is {expected_reference_qty}, expected {EXPECTED_QTY}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("DRY RUN ONLY — run again with --apply after reviewing the diffs."))
            return

        if extra_rows:
            raise CommandError("Unexpected non-zero stock exists on newer Darma colors. Nothing was changed; review the dry-run output first.")

        for size_name, color_name, current, target, delta, color in diffs:
            size = sizes[size_name]
            home_row, _ = StockBalance.objects.get_or_create(
                brand=brand, size=size, color=color, location=home, defaults={"qty": 0}
            )
            home_row.qty = int(home_row.qty or 0) + delta
            home_row.save(update_fields=["qty"])
            InventoryMovement.objects.create(
                movement_type=InventoryMovement.ADJUST,
                brand=brand,
                size=size,
                color=color,
                location=home,
                delta=delta,
                reference="excel-reconcile-v11",
            )

        final_reference_qty = 0
        for size_name, expected_colors in EXPECTED.items():
            size = sizes[size_name]
            for color_name in expected_colors:
                color_ids = [c.id for c in colors_by_norm[norm(color_name)]]
                final_reference_qty += int(
                    StockBalance.objects.filter(brand=brand, size=size, color_id__in=color_ids)
                    .aggregate(v=Sum("qty"))["v"] or 0
                )

        if final_reference_qty != EXPECTED_QTY:
            raise CommandError(f"Reconcile verification failed: final qty={final_reference_qty}, expected={EXPECTED_QTY}")

        self.stdout.write(self.style.SUCCESS(f"DARMA RECONCILED: {final_reference_qty} pcs = {EXPECTED_VALUE} toman at 61,000"))
