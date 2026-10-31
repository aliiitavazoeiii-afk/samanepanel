from collections import defaultdict
from decimal import Decimal

import jdatetime
from django.core.management.base import BaseCommand
from django.db.models import Sum

from core.excel_views import OUTPUT_MODELS, OUTPUT_SIZES
from core.models import (
    InventoryMovement,
    MaterialReportBlock,
    SaleLine,
    StockBalance,
)

FIXED_DARMA_COST = 61000


def _greg(jy, jm, jd):
    return jdatetime.date(int(jy), int(jm), int(jd)).togregorian()


def _line_pack_qty(line):
    try:
        snap = line.snapshot
    except Exception:
        snap = None
    return int((getattr(snap, "pack_qty", 0) if snap else 0) or line.product_size.product.pack_qty or 0)


def _output_total(block):
    total = 0
    by_color = []
    labels = dict(OUTPUT_MODELS)
    for model_key, label in OUTPUT_MODELS:
        values = (block.output_data or {}).get(model_key, {}) or {}
        subtotal = 0
        for size_key, _size_name in OUTPUT_SIZES:
            try:
                subtotal += max(0, int(float(str(values.get(size_key) or 0).replace("٬", "").replace(",", ""))))
            except Exception:
                pass
        if subtotal:
            by_color.append((label, subtotal))
            total += subtotal
    return total, by_color


class Command(BaseCommand):
    help = "Read-only audit of Darma SaleLine allocations, stock balances, negatives and material-report outputs."

    def add_arguments(self, parser):
        parser.add_argument("--from-j", default="1405/06/01")
        parser.add_argument("--to-j", default="1405/06/03")
        parser.add_argument("--opening-value", type=int, default=863211000)

    def handle(self, *args, **opts):
        from_j = opts["from_j"]
        to_j = opts["to_j"]
        fy, fm, fd = map(int, from_j.split("/"))
        ty, tm, td = map(int, to_j.split("/"))
        start = _greg(fy, fm, fd)
        end = _greg(ty, tm, td)
        opening_value = int(opts["opening_value"] or 0)

        lines = list(
            SaleLine.objects.filter(
                day__date__gte=start,
                day__date__lte=end,
                product_size__product__brand__name="دارما",
                quantity__gt=0,
            )
            .select_related("day", "product_size__product", "product_size__size")
            .prefetch_related("allocations", "snapshot")
            .order_by("day__date", "id")
        )

        print("=== DARMA SALES / STOCK AUDIT V15 (READ ONLY) ===")
        print(f"RANGE = {from_j} .. {to_j}")
        print(f"OPENING VALUE @61000 = {opening_value}")
        if opening_value % FIXED_DARMA_COST == 0:
            print(f"OPENING QTY @61000   = {opening_value // FIXED_DARMA_COST}")
        else:
            print("OPENING QTY @61000   = NON-INTEGER VALUE")
        print("")

        per_day = defaultdict(lambda: {"expected": 0, "alloc": 0, "applied": 0, "lines": 0})
        total_expected = 0
        total_alloc = 0
        total_applied = 0
        mismatch_count = 0

        for line in lines:
            pack = _line_pack_qty(line)
            expected = int(line.quantity or 0) * pack
            alloc = int(line.allocations.aggregate(v=Sum("qty"))["v"] or 0)
            applied = int(line.inventory_applied_quantity or 0) * pack
            day_key = jdatetime.date.fromgregorian(date=line.day.date).strftime("%Y/%m/%d")
            per_day[day_key]["expected"] += expected
            per_day[day_key]["alloc"] += alloc
            per_day[day_key]["applied"] += applied
            per_day[day_key]["lines"] += 1
            total_expected += expected
            total_alloc += alloc
            total_applied += applied

            if expected != alloc or expected != applied:
                mismatch_count += 1
                print(
                    "LINE MISMATCH:",
                    f"day={day_key}",
                    f"line={line.id}",
                    f"code={line.product_size.product.code}",
                    f"size={line.product_size.size.name}",
                    f"packs={line.quantity}",
                    f"pack_qty={pack}",
                    f"expected_shorts={expected}",
                    f"allocations={alloc}",
                    f"applied_shorts={applied}",
                )

        print("--- PER DAY CURRENT SALE STATE ---")
        for day_key in sorted(per_day):
            row = per_day[day_key]
            print(
                f"DAY {day_key}: lines={row['lines']} expected_shorts={row['expected']} "
                f"allocations={row['alloc']} applied_shorts={row['applied']} "
                f"cogs@61000={row['expected'] * FIXED_DARMA_COST}"
            )
        print(f"TOTAL EXPECTED SOLD SHORTS = {total_expected}")
        print(f"TOTAL CURRENT ALLOCATIONS  = {total_alloc}")
        print(f"TOTAL APPLIED SHORTS       = {total_applied}")
        print(f"TOTAL EXPECTED COGS@61000  = {total_expected * FIXED_DARMA_COST}")
        print(f"SALE LINE MISMATCHES       = {mismatch_count}")
        print("")

        balances = list(
            StockBalance.objects.filter(brand__name="دارما")
            .select_related("color", "size", "location")
            .order_by("location__key", "color__name", "size__sort_order", "size__id")
        )
        total_qty = sum(int(row.qty or 0) for row in balances)
        by_location = defaultdict(int)
        by_color = defaultdict(int)
        negatives = []
        for row in balances:
            qty = int(row.qty or 0)
            by_location[row.location.key] += qty
            by_color[row.color.name] += qty
            if qty < 0:
                negatives.append(row)

        print("--- CURRENT DARMA STOCKBALANCE ---")
        print(f"CURRENT NET QTY            = {total_qty}")
        print(f"CURRENT VALUE @61000       = {total_qty * FIXED_DARMA_COST}")
        for key, qty in sorted(by_location.items()):
            print(f"LOCATION {key}: qty={qty} value@61000={qty * FIXED_DARMA_COST}")
        print(f"NEGATIVE STOCK ROWS        = {len(negatives)}")
        for row in negatives:
            print(
                "NEGATIVE:",
                f"location={row.location.key}",
                f"color={row.color.name}",
                f"size={row.size.name}",
                f"qty={row.qty}",
                f"value@61000={int(row.qty) * FIXED_DARMA_COST}",
            )
        print("")

        expected_after_sales = opening_value - total_expected * FIXED_DARMA_COST
        unexplained_value = total_qty * FIXED_DARMA_COST - expected_after_sales
        print("--- OPENING -> SALES RECONCILIATION ---")
        print(f"OPENING VALUE              = {opening_value}")
        print(f"LESS SALES COGS@61000      = {total_expected * FIXED_DARMA_COST}")
        print(f"EXPECTED AFTER SALES       = {expected_after_sales}")
        print(f"ACTUAL CURRENT @61000      = {total_qty * FIXED_DARMA_COST}")
        print(f"UNEXPLAINED NET DIFFERENCE = {unexplained_value}")
        if unexplained_value % FIXED_DARMA_COST == 0:
            print(f"UNEXPLAINED NET QTY        = {unexplained_value // FIXED_DARMA_COST}")
        print("")

        print("--- MATERIAL REPORT OUTPUTS (ALL BLOCKS WITH OUTPUT) ---")
        report_total = 0
        for block in MaterialReportBlock.objects.order_by("id"):
            out_total, colors = _output_total(block)
            if not out_total:
                continue
            report_total += out_total
            day_key = jdatetime.date.fromgregorian(date=block.date).strftime("%Y/%m/%d")
            applied = block.stock_consumptions.exists()
            color_text = ", ".join(f"{name}:{qty}" for name, qty in colors)
            print(
                f"BLOCK id={block.id} date={day_key} title={block.title or '-'} "
                f"output={out_total} materials_applied={applied} colors=[{color_text}]"
            )
        print(f"TOTAL ENTERED MATERIAL-REPORT OUTPUTS = {report_total}")
        print("")

        print("--- SALE INVENTORY MOVEMENT HISTORY (DIAGNOSTIC ONLY) ---")
        # InventoryMovement is an append-only history and includes recalc/transfer rows;
        # current allocations above are the authoritative applied state. We still print
        # sale-only deltas per day to reveal duplicate/missing writes.
        for day_key in sorted(per_day):
            jy, jm, jd = map(int, day_key.split("/"))
            gday = _greg(jy, jm, jd)
            ids = [line.id for line in lines if line.day.date == gday]
            sale_delta = 0
            movement_count = 0
            for line_id in ids:
                qs = InventoryMovement.objects.filter(
                    brand__name="دارما",
                    movement_type=InventoryMovement.SALE,
                    reference__startswith=f"sale:{line_id}",
                )
                sale_delta += int(qs.aggregate(v=Sum("delta"))["v"] or 0)
                movement_count += qs.count()
            print(
                f"DAY {day_key}: historical_sale_delta={sale_delta} movement_rows={movement_count} "
                f"(history may include recalculations)"
            )

        print("=== END AUDIT V15 ===")
