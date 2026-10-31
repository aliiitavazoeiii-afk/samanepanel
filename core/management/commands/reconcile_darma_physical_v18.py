import hashlib

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

from core.brand_colors import norm
from core.dateutils import parse_jalali_date
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import (
    AccountEntry,
    Brand,
    Color,
    ExcelManualRow,
    ExcelManualSetting,
    InventoryModelCost,
    InventoryMovement,
    SaleAllocation,
    SaleLine,
    SaleSnapshot,
    Size,
    StockBalance,
    StockLocation,
)
from core.report_v5 import _raw_material_context


BASELINE_JALALI = "1405/06/03"
REFERENCE = "physical-baseline-1405-06-03-v18"

SIZES = ("M", "L", "XL", "XXL", "3XL", "4XL")

HOME = {
    "مشکی": {"M": 54, "L": 190, "XL": 134, "XXL": 134, "3XL": 48, "4XL": 78},
    "سفید": {"M": 150, "L": 168, "XL": 101, "XXL": 86, "3XL": 93, "4XL": 79},
    "سرمه ای": {"M": 36, "L": 149, "XL": 157, "XXL": 115, "3XL": 110, "4XL": 87},
    "صورتی": {"M": 97, "L": 225, "XL": 68, "XXL": 153, "3XL": 33, "4XL": 81},
    "کرم": {"M": 169, "L": 245, "XL": 245, "XXL": 212, "3XL": 77, "4XL": 79},
    "قرمز": {"M": 150, "L": 0, "XL": 0, "XXL": 0, "3XL": 0, "4XL": 0},
    "زرد": {"M": 0, "L": 80, "XL": 0, "XXL": 0, "3XL": 0, "4XL": 0},
    "طوسی": {"M": 42, "L": 17, "XL": 43, "XXL": 0, "3XL": 0, "4XL": 0},
    "راه راه": {"M": 41, "L": 15, "XL": 22, "XXL": 90, "3XL": 36, "4XL": 0},
    "راه راه طوسی": {"M": 15, "L": 6, "XL": 48, "XXL": 29, "3XL": 31, "4XL": 0},
    "برعکس مشکی": {"M": 18, "L": 12, "XL": 16, "XXL": 25, "3XL": 14, "4XL": 0},
    "برعکس سفید": {"M": 16, "L": 9, "XL": 24, "XXL": 23, "3XL": 5, "4XL": 0},
    "برعکس سرمه ای": {"M": 0, "L": 11, "XL": 51, "XXL": 29, "3XL": 14, "4XL": 0},
}

KHORSHID = {
    "مشکی": {"M": 180, "L": 460, "XL": 350, "XXL": 620, "3XL": 0, "4XL": 0},
    "سفید": {"M": 120, "L": 70, "XL": 0, "XXL": 200, "3XL": 10, "4XL": 0},
    "سرمه ای": {"M": 0, "L": 400, "XL": 500, "XXL": 730, "3XL": 150, "4XL": 0},
    "صورتی": {"M": 120, "L": 450, "XL": 0, "XXL": 250, "3XL": 0, "4XL": 0},
    "کرم": {"M": 110, "L": 600, "XL": 300, "XXL": 260, "3XL": 0, "4XL": 0},
    "قرمز": {"M": 160, "L": 0, "XL": 0, "XXL": 140, "3XL": 0, "4XL": 0},
    "زرد": {"M": 0, "L": 30, "XL": 0, "XXL": 0, "3XL": 0, "4XL": 0},
    "طوسی": {"M": 40, "L": 70, "XL": 0, "XXL": 0, "3XL": 0, "4XL": 0},
    "راه راه": {"M": 170, "L": 90, "XL": 0, "XXL": 0, "3XL": 0, "4XL": 0},
    "راه راه طوسی": {"M": 200, "L": 310, "XL": 400, "XXL": 410, "3XL": 250, "4XL": 0},
    "برعکس مشکی": {"M": 30, "L": 70, "XL": 60, "XXL": 60, "3XL": 70, "4XL": 0},
    "برعکس سفید": {"M": 30, "L": 70, "XL": 10, "XXL": 90, "3XL": 70, "4XL": 0},
    "برعکس سرمه ای": {"M": 0, "L": 60, "XL": 0, "XXL": 60, "3XL": 60, "4XL": 0},
}

TARGETS = {
    StockLocation.HOME: HOME,
    StockLocation.KHORSHID: KHORSHID,
}

EXPECTED_HOME_QTY = 4585
EXPECTED_KHORSHID_QTY = 8890
EXPECTED_TOTAL_QTY = 13475


def _sum_target(table):
    return sum(int(qty) for sizes in table.values() for qty in sizes.values())


def _capital_snapshot():
    accounts = list(ExcelManualRow.objects.filter(active=True, section=ExcelManualRow.ACCOUNTS))
    persons = list(ExcelManualRow.objects.filter(active=True, section=ExcelManualRow.PERSONS))
    assets = list(ExcelManualRow.objects.filter(active=True, section=ExcelManualRow.ASSETS))
    accounts_total = sum(int(row.amount or 0) for row in accounts) + sum(int(row.amount or 0) for row in persons)
    assets_total = sum(int(row.amount or 0) for row in assets)
    finished = int(finished_inventory_value_v17())
    raw = int(_raw_material_context()["materials_total"])
    inventory = finished + raw
    takvin_obj = ExcelManualSetting.objects.filter(key="takvin_debt").first()
    takvin_debt = int(takvin_obj.value or 0) if takvin_obj else 0
    digikala = int(digikala_receivable_total())
    capital = accounts_total + inventory + digikala - takvin_debt + assets_total
    return {
        "accounts": accounts_total,
        "finished": finished,
        "raw": raw,
        "inventory": inventory,
        "digikala": digikala,
        "takvin_debt": takvin_debt,
        "assets": assets_total,
        "capital": capital,
    }


def _write_snapshot(command, label, values):
    command.stdout.write(f"=== {label} ===")
    command.stdout.write(f"ACCOUNTS + PERSONS = {values['accounts']}")
    command.stdout.write(f"FINISHED INVENTORY = {values['finished']}")
    command.stdout.write(f"RAW MATERIALS = {values['raw']}")
    command.stdout.write(f"INVENTORY TOTAL = {values['inventory']}")
    command.stdout.write(f"DIGIKALA TOTAL = {values['digikala']}")
    command.stdout.write(f"TAKVIN DEBT = {values['takvin_debt']}")
    command.stdout.write(f"ASSETS = {values['assets']}")
    command.stdout.write(f"CAPITAL TOTAL = {values['capital']}")


def _sales_digest():
    h = hashlib.sha256()
    sources = (
        SaleLine.objects.order_by("id").values_list(
            "id", "day_id", "product_size_id", "quantity", "inventory_applied_quantity", "sale_price"
        ),
        SaleSnapshot.objects.order_by("sale_line_id").values_list(
            "sale_line_id", "unit_cost", "pack_qty", "digikala_fee_unit"
        ),
        SaleAllocation.objects.order_by("id").values_list(
            "id", "sale_line_id", "color_id", "location_id", "qty", "is_replacement"
        ),
        AccountEntry.objects.filter(reference__startswith="sale:").order_by("id").values_list(
            "id", "date", "account_id", "delta", "reference"
        ),
    )
    for rows in sources:
        for row in rows.iterator(chunk_size=1000):
            h.update(repr(tuple(row)).encode("utf-8"))
            h.update(b"\n")
    return h.hexdigest()


def _day3_summary():
    day = parse_jalali_date(BASELINE_JALALI)
    rows = SaleLine.objects.filter(day__date=day)
    return {
        "lines": rows.count(),
        "packs": int(rows.aggregate(v=Sum("quantity"))["v"] or 0),
        "applied_packs": int(rows.aggregate(v=Sum("inventory_applied_quantity"))["v"] or 0),
        "shorts": sum(int(line.quantity or 0) * int(line.product_size.product.pack_qty or 0)
                      for line in rows.select_related("product_size__product")),
    }


def _catalog(brand):
    sizes = {row.name: row for row in Size.objects.filter(name__in=SIZES)}
    if set(sizes) != set(SIZES):
        missing = sorted(set(SIZES) - set(sizes))
        raise CommandError("Missing sizes: " + ", ".join(missing))

    all_colors = list(Color.objects.filter(stockbalance__brand=brand).distinct().order_by("id"))
    by_norm = {}
    for color in all_colors:
        by_norm.setdefault(norm(color.name), []).append(color)

    target_colors = {}
    for color_name in HOME:
        matches = by_norm.get(norm(color_name), [])
        if not matches:
            raise CommandError(f"Missing Darma color: {color_name}")
        if len(matches) > 1:
            names = ", ".join(f"{c.id}:{c.name}" for c in matches)
            raise CommandError(f"Ambiguous normalized color {color_name}: {names}")
        target_colors[color_name] = matches[0]

    locations = {
        StockLocation.HOME: StockLocation.objects.get(key=StockLocation.HOME),
        StockLocation.KHORSHID: StockLocation.objects.get(key=StockLocation.KHORSHID),
    }
    return sizes, target_colors, locations


def _cost_map(brand):
    return {
        (row.color_id, row.size_id): int(row.unit_cost or 0)
        for row in InventoryModelCost.objects.filter(brand=brand)
    }


def _darma_value(brand, costs):
    total = 0
    rows = (
        StockBalance.objects.filter(brand=brand)
        .values("color_id", "size_id")
        .annotate(qty=Sum("qty"))
    )
    for row in rows:
        total += int(row["qty"] or 0) * int(costs.get((row["color_id"], row["size_id"]), 0))
    return int(total)


def _target_value(brand, sizes, target_colors, costs):
    total = 0
    missing_costs = []
    for location_key, table in TARGETS.items():
        for color_name, size_map in table.items():
            color = target_colors[color_name]
            for size_name, qty in size_map.items():
                qty = int(qty)
                size = sizes[size_name]
                unit_cost = int(costs.get((color.id, size.id), 0))
                if qty > 0 and unit_cost <= 0:
                    missing_costs.append(f"{color_name}/{size_name}")
                total += qty * unit_cost
    if missing_costs:
        raise CommandError(
            "Target has positive stock with zero/missing InventoryModelCost: "
            + ", ".join(sorted(set(missing_costs)))
        )
    return int(total)


def _build_target_map(sizes, target_colors):
    result = {}
    for location_key, table in TARGETS.items():
        for color_name, size_map in table.items():
            color = target_colors[color_name]
            for size_name, qty in size_map.items():
                size = sizes[size_name]
                result[(location_key, color.id, size.id)] = int(qty)
    return result


def _current_rows(brand):
    return list(
        StockBalance.objects.filter(
            brand=brand,
            location__key__in=[StockLocation.HOME, StockLocation.KHORSHID],
        ).select_related("color", "size", "location").order_by(
            "location__key", "color__id", "size__sort_order", "size__id"
        )
    )


def _plan(brand, target_map, costs):
    plan = []
    seen = set()
    for row in _current_rows(brand):
        key = (row.location.key, row.color_id, row.size_id)
        target = int(target_map.get(key, 0))
        current = int(row.qty or 0)
        seen.add(key)
        if current != target:
            cost = int(costs.get((row.color_id, row.size_id), 0))
            plan.append({
                "row": row,
                "location_key": row.location.key,
                "location_title": row.location.title,
                "color": row.color,
                "size": row.size,
                "current": current,
                "target": target,
                "delta": target - current,
                "unit_cost": cost,
                "value_delta": (target - current) * cost,
            })

    for key, target in target_map.items():
        if key in seen or int(target) == 0:
            continue
        location_key, color_id, size_id = key
        color = Color.objects.get(pk=color_id)
        size = Size.objects.get(pk=size_id)
        location = StockLocation.objects.get(key=location_key)
        cost = int(costs.get((color_id, size_id), 0))
        plan.append({
            "row": None,
            "location_key": location_key,
            "location_title": location.title,
            "color": color,
            "size": size,
            "current": 0,
            "target": int(target),
            "delta": int(target),
            "unit_cost": cost,
            "value_delta": int(target) * cost,
        })
    return plan


def _verify_target(brand, target_map):
    rows = _current_rows(brand)
    actual = {(row.location.key, row.color_id, row.size_id): int(row.qty or 0) for row in rows}

    mismatches = []
    for key, target in target_map.items():
        current = int(actual.get(key, 0))
        if current != int(target):
            mismatches.append((key, current, int(target)))

    extras = [(key, qty) for key, qty in actual.items() if key not in target_map and int(qty) != 0]
    if mismatches or extras:
        raise CommandError(
            f"Physical target verification failed: mismatches={len(mismatches)} extras={len(extras)}"
        )

    home_qty = sum(
        qty for (location_key, _color_id, _size_id), qty in actual.items()
        if location_key == StockLocation.HOME
    )
    kh_qty = sum(
        qty for (location_key, _color_id, _size_id), qty in actual.items()
        if location_key == StockLocation.KHORSHID
    )
    total_qty = home_qty + kh_qty

    if home_qty != EXPECTED_HOME_QTY or kh_qty != EXPECTED_KHORSHID_QTY or total_qty != EXPECTED_TOTAL_QTY:
        raise CommandError(
            f"Target quantity verification failed: HOME={home_qty}, KHORSHID={kh_qty}, TOTAL={total_qty}"
        )

    negatives = StockBalance.objects.filter(
        brand=brand,
        location__key__in=[StockLocation.HOME, StockLocation.KHORSHID],
        qty__lt=0,
    ).count()
    if negatives:
        raise CommandError(f"Negative Darma balance remained after physical baseline: {negatives}")

    return home_qty, kh_qty, total_qty


class Command(BaseCommand):
    help = (
        "Dry-run/apply authoritative Darma HOME+KHORSHID physical stock baseline "
        "counted after sales on 1405/06/03. Sale rows/snapshots/allocations are never changed."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Apply exact physical target after dry-run review.")

    def handle(self, *args, **options):
        if _sum_target(HOME) != EXPECTED_HOME_QTY:
            raise CommandError("Embedded HOME target total is invalid.")
        if _sum_target(KHORSHID) != EXPECTED_KHORSHID_QTY:
            raise CommandError("Embedded KHORSHID target total is invalid.")
        if EXPECTED_HOME_QTY + EXPECTED_KHORSHID_QTY != EXPECTED_TOTAL_QTY:
            raise CommandError("Embedded combined target total is invalid.")

        apply_changes = bool(options["apply"])
        brand = Brand.objects.get(name="دارما")
        sizes, target_colors, locations = _catalog(brand)
        costs = _cost_map(brand)
        target_map = _build_target_map(sizes, target_colors)

        before = _capital_snapshot()
        current_darma_value = _darma_value(brand, costs)
        target_darma_value = _target_value(brand, sizes, target_colors, costs)
        value_delta = target_darma_value - current_darma_value
        expected_after = dict(before)
        expected_after["finished"] = before["finished"] + value_delta
        expected_after["inventory"] = before["inventory"] + value_delta
        expected_after["capital"] = before["capital"] + value_delta

        sales_digest_before = _sales_digest()
        day3_before = _day3_summary()
        plan = _plan(brand, target_map, costs)

        self.stdout.write("=== DARMA PHYSICAL BASELINE V18 ===")
        self.stdout.write(
            "Authoritative baseline: after all sales on 1405/06/03. "
            "SaleLine/SaleSnapshot/SaleAllocation/sale finance are read-only."
        )
        self.stdout.write(f"TARGET HOME QTY = {EXPECTED_HOME_QTY}")
        self.stdout.write(f"TARGET KHORSHID QTY = {EXPECTED_KHORSHID_QTY}")
        self.stdout.write(f"TARGET TOTAL QTY = {EXPECTED_TOTAL_QTY}")
        self.stdout.write(
            f"DAY3 SALES = lines:{day3_before['lines']} packs:{day3_before['packs']} "
            f"applied_packs:{day3_before['applied_packs']} shorts:{day3_before['shorts']}"
        )
        self.stdout.write(f"SALES DIGEST BEFORE = {sales_digest_before}")
        _write_snapshot(self, "CAPITAL BEFORE", before)
        self.stdout.write(f"DARMA CURRENT VALUE = {current_darma_value}")
        self.stdout.write(f"DARMA TARGET VALUE = {target_darma_value}")
        self.stdout.write(f"DARMA VALUE DELTA = {value_delta:+d}")
        self.stdout.write(f"EXPECTED FINISHED AFTER = {expected_after['finished']}")
        self.stdout.write(f"EXPECTED INVENTORY AFTER = {expected_after['inventory']}")
        self.stdout.write(f"EXPECTED CAPITAL AFTER = {expected_after['capital']}")
        self.stdout.write(f"CHANGED CELLS = {len(plan)}")

        for item in plan:
            self.stdout.write(
                f"{item['location_key']:8} | {item['color'].name:18} | {item['size'].name:4} | "
                f"current={item['current']:6} target={item['target']:6} delta={item['delta']:+6} | "
                f"cost={item['unit_cost']:9} value_delta={item['value_delta']:+12}"
            )

        if not apply_changes:
            self.stdout.write(self.style.WARNING("DRY RUN ONLY — no stock, sale, finance, or accounting row was changed."))
            return

        with transaction.atomic():
            list(
                StockBalance.objects.select_for_update().filter(
                    brand=brand,
                    location__key__in=[StockLocation.HOME, StockLocation.KHORSHID],
                )
            )

            if _sales_digest() != sales_digest_before:
                raise CommandError("Sales changed during reconcile preparation. Transaction aborted; rerun.")

            for item in plan:
                row = item["row"]
                if row is None:
                    row, _ = StockBalance.objects.get_or_create(
                        brand=brand,
                        color=item["color"],
                        size=item["size"],
                        location=locations[item["location_key"]],
                        defaults={"qty": 0},
                    )
                    row = StockBalance.objects.select_for_update().get(pk=row.pk)
                else:
                    row = StockBalance.objects.select_for_update().get(pk=row.pk)

                current = int(row.qty or 0)
                target = int(item["target"])
                delta = target - current
                if delta == 0:
                    continue
                row.qty = target
                row.save(update_fields=["qty"])
                InventoryMovement.objects.create(
                    movement_type=InventoryMovement.ADJUST,
                    brand=brand,
                    color=item["color"],
                    size=item["size"],
                    location=locations[item["location_key"]],
                    delta=delta,
                    reference=REFERENCE,
                )

            home_qty, kh_qty, total_qty = _verify_target(brand, target_map)

            sales_digest_after = _sales_digest()
            if sales_digest_after != sales_digest_before:
                raise CommandError("Sale data changed during stock reconcile. Entire transaction rolled back.")

            day3_after = _day3_summary()
            if day3_after != day3_before:
                raise CommandError("1405/06/03 sales summary changed. Entire transaction rolled back.")

            after = _capital_snapshot()
            stable_keys = ("accounts", "raw", "digikala", "takvin_debt", "assets")
            changed_stable = [key for key in stable_keys if after[key] != before[key]]
            if changed_stable:
                raise CommandError(
                    "Non-inventory capital components changed unexpectedly: " + ", ".join(changed_stable)
                )

            for key in ("finished", "inventory", "capital"):
                if after[key] != expected_after[key]:
                    raise CommandError(
                        f"{key} mismatch after reconcile: actual={after[key]} expected={expected_after[key]}"
                    )

            final_darma_value = _darma_value(brand, costs)
            if final_darma_value != target_darma_value:
                raise CommandError(
                    f"Darma valuation mismatch after reconcile: actual={final_darma_value} target={target_darma_value}"
                )

        self.stdout.write(self.style.SUCCESS("DARMA PHYSICAL BASELINE V18 APPLIED"))
        self.stdout.write(f"FINAL HOME QTY = {home_qty}")
        self.stdout.write(f"FINAL KHORSHID QTY = {kh_qty}")
        self.stdout.write(f"FINAL TOTAL QTY = {total_qty}")
        self.stdout.write(f"SALES DIGEST AFTER = {sales_digest_after}")
        _write_snapshot(self, "CAPITAL AFTER", after)
        self.stdout.write(f"DARMA FINAL VALUE = {final_darma_value}")
        self.stdout.write(
            "SUCCESS: physical end-of-day 1405/06/03 stock is now authoritative. "
            "No sale or historical SaleSnapshot was rewritten."
        )
