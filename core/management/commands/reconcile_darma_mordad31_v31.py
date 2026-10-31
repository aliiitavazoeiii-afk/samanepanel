from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

from core.brand_colors import norm
from core.dateutils import parse_jalali_date
from core.models import Brand, Color, InventoryMovement, SaleDay, Size, StockBalance, StockLocation


# Authoritative snapshot from user workbook: `mojodi 31 mordad.xlsx`.
# The workbook is a COMBINED Darma total (HOME + KHORSHID), not a per-location count.
# Therefore this reconcile preserves KHORSHID and applies only the required delta to HOME.
EXPECTED = {
    "M": {
        "مشکی": 316, "سفید": 244, "سرمه ای": 152, "صورتی": 263, "کرم": 357,
        "قرمز": 153, "زرد": -4, "طوسی": 100, "راه راه": 218, "راه راه طوسی": 218,
        "برعکس مشکی": 47, "برعکس سفید": 45, "برعکس سرمه ای": 0,
    },
    "L": {
        "مشکی": 673, "سفید": 260, "سرمه ای": 663, "صورتی": 697, "کرم": 1010,
        "قرمز": -34, "زرد": 80, "طوسی": 101, "راه راه": 107, "راه راه طوسی": 313,
        "برعکس مشکی": 83, "برعکس سفید": 72, "برعکس سرمه ای": 71,
    },
    "XL": {
        "مشکی": 724, "سفید": 173, "سرمه ای": 713, "صورتی": 99, "کرم": 623,
        "قرمز": -29, "زرد": 0, "طوسی": 32, "راه راه": 39, "راه راه طوسی": 444,
        "برعکس مشکی": 79, "برعکس سفید": 38, "برعکس سرمه ای": 67,
    },
    "XXL": {
        "مشکی": 799, "سفید": 360, "سرمه ای": 911, "صورتی": 553, "کرم": 703,
        "قرمز": -39, "زرد": 0, "طوسی": -3, "راه راه": 105, "راه راه طوسی": 439,
        "برعکس مشکی": 85, "برعکس سفید": 121, "برعکس سرمه ای": 72,
    },
    "3XL": {
        "مشکی": 97, "سفید": 157, "سرمه ای": 306, "صورتی": 59, "کرم": 126,
        "قرمز": 0, "زرد": 0, "طوسی": 10, "راه راه": 41, "راه راه طوسی": 100,
        "برعکس مشکی": 87, "برعکس سفید": 84, "برعکس سرمه ای": 76,
    },
    "4XL": {
        "مشکی": 79, "سفید": 80, "سرمه ای": 88, "صورتی": 81, "کرم": 80,
        "قرمز": 0, "زرد": 0, "طوسی": 0, "راه راه": 0, "راه راه طوسی": 0,
        "برعکس مشکی": 0, "برعکس سفید": 0, "برعکس سرمه ای": 0,
    },
}

EXPECTED_QTY = 14864
EXPECTED_SIZE_TOTALS = {"M": 2109, "L": 4096, "XL": 3002, "XXL": 4106, "3XL": 1143, "4XL": 408}
UNIT_COST = 61000
EXPECTED_VALUE = EXPECTED_QTY * UNIT_COST
BOUNDARY = "1405/06/01"
REFERENCE = "mordad31-baseline-v31"


def _brand_colors(brand):
    colors = list(Color.objects.filter(stockbalance__brand=brand).distinct())
    by_norm = {}
    for color in colors:
        by_norm.setdefault(norm(color.name), []).append(color)
    return by_norm


def _combined_qty(brand, size, color_ids):
    return int(
        StockBalance.objects.filter(brand=brand, size=size, color_id__in=color_ids)
        .aggregate(v=Sum("qty"))["v"] or 0
    )


class Command(BaseCommand):
    help = "Reconcile combined Darma inventory to the authoritative 31-Mordad workbook. Default is read-only."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        apply_changes = bool(options["apply"])
        boundary = parse_jalali_date(BOUNDARY)
        post_boundary_days = SaleDay.objects.filter(date__gte=boundary).count()
        if post_boundary_days:
            raise CommandError(
                f"There are still {post_boundary_days} SaleDays from {BOUNDARY} onward. "
                "Run the Shahrivar workflow reset first; baseline was NOT changed."
            )

        brand = Brand.objects.get(name="دارما")
        home = StockLocation.objects.get(key=StockLocation.HOME)
        khorshid = StockLocation.objects.get(key=StockLocation.KHORSHID)
        sizes = {s.name: s for s in Size.objects.filter(name__in=EXPECTED.keys())}
        colors_by_norm = _brand_colors(brand)

        missing = []
        diffs = []
        current_total = 0
        target_total = 0

        self.stdout.write("=== DARMA 31 MORDAD BASELINE V31 ===")
        self.stdout.write("Source: user workbook `mojodi 31 mordad.xlsx`")
        self.stdout.write("Semantics: target is combined HOME+KHORSHID; KHORSHID is preserved; delta is applied to HOME.")
        self.stdout.write("")

        for size_name, expected_colors in EXPECTED.items():
            size = sizes.get(size_name)
            if size is None:
                missing.append(f"size {size_name}")
                continue
            for color_name, target in expected_colors.items():
                color_list = colors_by_norm.get(norm(color_name), [])
                if not color_list:
                    missing.append(f"color {color_name}")
                    continue
                color_ids = [c.id for c in color_list]
                current = _combined_qty(brand, size, color_ids)
                current_total += current
                target_total += int(target)
                delta = int(target) - current
                if delta:
                    kh_qty = int(
                        StockBalance.objects.filter(
                            brand=brand, size=size, color_id__in=color_ids, location=khorshid
                        ).aggregate(v=Sum("qty"))["v"] or 0
                    )
                    diffs.append((size_name, color_name, current, int(target), delta, kh_qty, color_list[0]))
                    self.stdout.write(
                        f"{size_name:4} | {color_name:18} | total={current:6} -> {int(target):6} "
                        f"delta={delta:+6} | kh-preserved={kh_qty:6}"
                    )

        if missing:
            raise CommandError("Missing catalog rows: " + ", ".join(missing))
        if target_total != EXPECTED_QTY:
            raise CommandError(f"Embedded snapshot total={target_total}; expected={EXPECTED_QTY}")

        self.stdout.write("")
        self.stdout.write(f"CURRENT COMBINED QTY = {current_total}")
        self.stdout.write(f"TARGET COMBINED QTY  = {target_total}")
        self.stdout.write(f"TOTAL DELTA          = {target_total - current_total:+d}")
        self.stdout.write(f"TARGET VALUE @61,000 = {EXPECTED_VALUE:,}")
        self.stdout.write(f"CHANGED CELLS        = {len(diffs)}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("DRY RUN ONLY — run with --apply after DB backup."))
            return

        for size_name, color_name, current, target, delta, kh_qty, color in diffs:
            size = sizes[size_name]
            home_row, _ = StockBalance.objects.select_for_update().get_or_create(
                brand=brand,
                size=size,
                color=color,
                location=home,
                defaults={"qty": 0},
            )
            home_row.qty = int(home_row.qty or 0) + int(delta)
            home_row.save(update_fields=["qty"])
            InventoryMovement.objects.create(
                movement_type=InventoryMovement.ADJUST,
                brand=brand,
                size=size,
                color=color,
                location=home,
                delta=int(delta),
                reference=REFERENCE,
            )

        final_total = 0
        final_sizes = {}
        mismatches = []
        for size_name, expected_colors in EXPECTED.items():
            size = sizes[size_name]
            size_total = 0
            for color_name, target in expected_colors.items():
                color_ids = [c.id for c in colors_by_norm[norm(color_name)]]
                current = _combined_qty(brand, size, color_ids)
                size_total += current
                final_total += current
                if current != int(target):
                    mismatches.append(f"{size_name}/{color_name}: {current} != {target}")
            final_sizes[size_name] = size_total

        if mismatches:
            raise CommandError("Final cell verification failed: " + "; ".join(mismatches[:20]))
        if final_total != EXPECTED_QTY:
            raise CommandError(f"Final total={final_total}; expected={EXPECTED_QTY}")
        if final_sizes != EXPECTED_SIZE_TOTALS:
            raise CommandError(f"Final size totals={final_sizes}; expected={EXPECTED_SIZE_TOTALS}")

        self.stdout.write("")
        self.stdout.write("=== BASELINE COMPLETE ===")
        self.stdout.write(f"Darma combined total = {final_total}")
        for size_name in ("M", "L", "XL", "XXL", "3XL", "4XL"):
            self.stdout.write(f"  {size_name} = {final_sizes[size_name]}")
        self.stdout.write(f"Darma value @61,000 = {EXPECTED_VALUE:,}")
        self.stdout.write("KHORSHID rows preserved; only HOME deltas were applied.")
        self.stdout.write(self.style.SUCCESS("SUCCESS: DARMA INVENTORY SET TO 31 MORDAD V31"))
