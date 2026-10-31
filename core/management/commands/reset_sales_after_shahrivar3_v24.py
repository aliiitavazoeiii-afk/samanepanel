from copy import deepcopy
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

from core.brand_colors import norm
from core.dateutils import parse_jalali_date
from core.finance_excel_v9 import sync_sale_receivable
from core.management.commands.reconcile_darma_physical_v18 import HOME as V18_HOME, KHORSHID as V18_KHORSHID
from core.models import (
    AccountEntry,
    AppSetting,
    Brand,
    Color,
    InventoryMovement,
    ProductComposition,
    ProductCode,
    SaleAllocation,
    SaleDay,
    SaleLine,
    Size,
    StockBalance,
    StockLocation,
)
from core.sale_inventory_v19 import sync_sale_inventory_v19


BASELINE_JALALI = "1405/06/03"
BASELINE_DATE = parse_jalali_date(BASELINE_JALALI)
RESET_REFERENCE = "diagnostic-reset-after-1405-06-03-v24"
SIZES = ("M", "L", "XL", "XXL", "3XL", "4XL")

# V18 is the physical EOD baseline after 3 Shahrivar sales. The user later
# corrected one Khorshid entry: red XXL 140 was actually cream XXL +140.
HOME = deepcopy(V18_HOME)
KHORSHID = deepcopy(V18_KHORSHID)
KHORSHID["قرمز"]["XXL"] = 0
KHORSHID["کرم"]["XXL"] = 400
TARGETS = {StockLocation.HOME: HOME, StockLocation.KHORSHID: KHORSHID}

EXPECTED_HOME = 4585
EXPECTED_KHORSHID = 8890
EXPECTED_TOTAL = 13475


def _sum_table(table):
    return sum(int(qty) for sizes in table.values() for qty in sizes.values())


def _color(brand, name):
    wanted = norm(name)
    matches = list(
        Color.objects.filter(stockbalance__brand=brand).distinct().order_by("id")
    )
    matches = [row for row in matches if norm(row.name) == wanted]
    if len(matches) != 1:
        raise CommandError(f"رنگ دارما «{name}» یکتا پیدا نشد: {[f'{c.id}:{c.name}' for c in matches]}")
    return matches[0]


def _catalog(brand):
    sizes = {row.name: row for row in Size.objects.filter(name__in=SIZES)}
    if set(sizes) != set(SIZES):
        raise CommandError("سایزهای مرجع کامل نیستند: " + ", ".join(sorted(set(SIZES) - set(sizes))))
    colors = {name: _color(brand, name) for name in HOME}
    locations = {
        StockLocation.HOME: StockLocation.objects.get(key=StockLocation.HOME),
        StockLocation.KHORSHID: StockLocation.objects.get(key=StockLocation.KHORSHID),
    }
    return sizes, colors, locations


def _target_map(sizes, colors, locations):
    result = {}
    for location_key, table in TARGETS.items():
        location = locations[location_key]
        for color_name, size_map in table.items():
            color = colors[color_name]
            for size_name, qty in size_map.items():
                result[(location.id, color.id, sizes[size_name].id)] = int(qty)
    return result


def _darma_totals(brand):
    rows = (
        StockBalance.objects.filter(
            brand=brand,
            location__key__in=[StockLocation.HOME, StockLocation.KHORSHID],
        )
        .values("location__key")
        .annotate(qty=Sum("qty"))
    )
    by_location = {row["location__key"]: int(row["qty"] or 0) for row in rows}
    return (
        int(by_location.get(StockLocation.HOME, 0)),
        int(by_location.get(StockLocation.KHORSHID, 0)),
    )


def _stock_qty(brand, color_name, size_name, location_key=None):
    qs = StockBalance.objects.filter(
        brand=brand,
        color__name=color_name,
        size__name=size_name,
    )
    if location_key:
        qs = qs.filter(location__key=location_key)
    return int(qs.aggregate(v=Sum("qty"))["v"] or 0)


def _negative_rows(brand):
    return list(
        StockBalance.objects.filter(brand=brand, qty__lt=0)
        .select_related("color", "size", "location")
        .order_by("color__name", "size__sort_order", "location__key")
    )


def _post_lines():
    return list(
        SaleLine.objects.filter(day__date__gt=BASELINE_DATE)
        .select_related("day", "product_size__product__brand", "product_size__product", "product_size__size")
        .order_by("day__date", "id")
    )


def _allocation_groups():
    groups = defaultdict(int)
    rows = (
        SaleAllocation.objects.filter(sale_line__day__date__gt=BASELINE_DATE)
        .select_related(
            "sale_line__day",
            "sale_line__product_size__product__brand",
            "sale_line__product_size__product",
            "sale_line__product_size__size",
            "color",
        )
        .order_by("sale_line__day__date", "sale_line_id", "id")
    )
    for alloc in rows:
        line = alloc.sale_line
        key = (
            line.day.date,
            line.product_size.product.brand.name,
            line.product_size.product.code,
            line.product_size.size.name,
            alloc.color.name,
            bool(alloc.is_replacement),
        )
        groups[key] += int(alloc.qty or 0)
    return groups


def _code06_state(darma):
    product = ProductCode.objects.filter(brand=darma, code="06").first()
    if not product:
        raise CommandError("کد 06 دارما در کاتالوگ پیدا نشد.")
    comps = list(product.composition.select_related("color").order_by("color__name"))
    return product, comps


def _fix_code06_if_needed(darma):
    product, comps = _code06_state(darma)
    red = next((row for row in comps if norm(row.color.name) == norm("قرمز")), None)
    cream = next((row for row in comps if norm(row.color.name) == norm("کرم")), None)
    changed = False
    if red:
        cream_color = _color(darma, "کرم")
        if cream:
            cream.qty = int(cream.qty or 0) + int(red.qty or 0)
            cream.save(update_fields=["qty"])
        else:
            ProductComposition.objects.create(product=product, color=cream_color, qty=int(red.qty or 0))
        red.delete()
        changed = True
    product.refresh_from_db()
    comps = list(product.composition.select_related("color").order_by("color__name"))
    if any(norm(row.color.name) == norm("قرمز") for row in comps):
        raise CommandError("اصلاح 06 ناموفق بود؛ قرمز هنوز در ترکیب وجود دارد.")
    if not any(norm(row.color.name) == norm("کرم") for row in comps):
        raise CommandError("ترکیب 06 کرم ندارد؛ عملیات متوقف شد.")
    comp_total = sum(int(row.qty or 0) for row in comps)
    if comp_total != int(product.pack_qty or 0):
        raise CommandError(
            f"جمع ترکیب 06 برابر {comp_total} است ولی pack_qty={product.pack_qty}. "
            "قبل از ورود دوباره سفارش‌ها این ناسازگاری باید بررسی شود."
        )
    return changed, product, comps


def _set_darma_reference(darma, target_map):
    deltas = []
    existing = {
        (row.location_id, row.color_id, row.size_id): row
        for row in StockBalance.objects.select_for_update().filter(
            brand=darma,
            location__key__in=[StockLocation.HOME, StockLocation.KHORSHID],
        ).select_related("location", "color", "size")
    }
    all_keys = set(existing) | set(target_map)
    for key in sorted(all_keys):
        target = int(target_map.get(key, 0))
        row = existing.get(key)
        if row is None:
            location_id, color_id, size_id = key
            row = StockBalance.objects.create(
                brand=darma,
                location_id=location_id,
                color_id=color_id,
                size_id=size_id,
                qty=0,
            )
            row = StockBalance.objects.select_for_update().select_related("location", "color", "size").get(pk=row.pk)
        current = int(row.qty or 0)
        if current == target:
            continue
        delta = target - current
        row.qty = target
        row.save(update_fields=["qty"])
        InventoryMovement.objects.create(
            movement_type=InventoryMovement.ADJUST,
            brand=darma,
            size=row.size,
            color=row.color,
            location=row.location,
            delta=delta,
            reference=RESET_REFERENCE,
        )
        deltas.append((row.location.title, row.color.name, row.size.name, current, target, delta))
    return deltas


def _verify_reference(darma, target_map):
    actual = {
        (row.location_id, row.color_id, row.size_id): int(row.qty or 0)
        for row in StockBalance.objects.filter(
            brand=darma,
            location__key__in=[StockLocation.HOME, StockLocation.KHORSHID],
        )
    }
    mismatches = []
    for key in set(actual) | set(target_map):
        current = int(actual.get(key, 0))
        target = int(target_map.get(key, 0))
        if current != target:
            mismatches.append((key, current, target))
    if mismatches:
        raise CommandError(f"موجودی دارما به مرجع نرسید؛ {len(mismatches)} سلول اختلاف دارد.")
    home, kh = _darma_totals(darma)
    if home != EXPECTED_HOME or kh != EXPECTED_KHORSHID or home + kh != EXPECTED_TOTAL:
        raise CommandError(
            f"جمع مرجع غلط است: HOME={home}, KHORSHID={kh}, TOTAL={home + kh}"
        )


class Command(BaseCommand):
    help = "Diagnose post-3-Shahrivar sales, then optionally remove them and restore exact Darma reference stock."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Actually perform the reset. Default is read-only plan.")

    def _write_diagnostics(self, darma):
        lines = _post_lines()
        groups = _allocation_groups()
        self.stdout.write("=== POST-BASELINE SALE DAYS ===")
        days = defaultdict(lambda: {"lines": 0, "packs": 0, "shorts": 0})
        for line in lines:
            d = days[line.day.date]
            d["lines"] += 1
            d["packs"] += int(line.quantity or 0)
            d["shorts"] += int(line.quantity or 0) * int(line.product_size.product.pack_qty or 0)
        if not days:
            self.stdout.write("none")
        for day, data in sorted(days.items()):
            self.stdout.write(
                f"{day}: lines={data['lines']} packs={data['packs']} shorts={data['shorts']}"
            )

        self.stdout.write("\n=== CODE 06 ALLOCATIONS AFTER 3 SHAHRIVAR ===")
        found = False
        for key, qty in sorted(groups.items()):
            day, brand, code, size, color, repl = key
            if brand == "دارما" and code == "06":
                found = True
                self.stdout.write(f"{day} | 06 / {size} | {color} | qty={qty} | replacement={repl}")
        if not found:
            self.stdout.write("none")

        self.stdout.write("\n=== RED ALLOCATIONS AFTER 3 SHAHRIVAR ===")
        found = False
        for key, qty in sorted(groups.items()):
            day, brand, code, size, color, repl = key
            if brand in {"دارما", "انبارش"} and norm(color) == norm("قرمز"):
                found = True
                self.stdout.write(f"{day} | {brand} {code} / {size} | red qty={qty} | replacement={repl}")
        if not found:
            self.stdout.write("none")

        self.stdout.write("\n=== GREY 4XL ALLOCATIONS AFTER 3 SHAHRIVAR ===")
        found = False
        for key, qty in sorted(groups.items()):
            day, brand, code, size, color, repl = key
            if brand in {"دارما", "انبارش"} and size == "4XL" and norm(color) == norm("طوسی"):
                found = True
                self.stdout.write(f"{day} | {brand} {code} / 4XL | grey qty={qty} | replacement={repl}")
        if not found:
            self.stdout.write("none")

        self.stdout.write("\n=== CREAM 3XL ALLOCATIONS AFTER 3 SHAHRIVAR ===")
        found = False
        for key, qty in sorted(groups.items()):
            day, brand, code, size, color, repl = key
            if brand in {"دارما", "انبارش"} and size == "3XL" and norm(color) == norm("کرم"):
                found = True
                self.stdout.write(f"{day} | {brand} {code} / 3XL | cream qty={qty} | replacement={repl}")
        if not found:
            self.stdout.write("none")

        self.stdout.write("\n=== CURRENT NEGATIVE DARMA CELLS ===")
        negatives = _negative_rows(darma)
        if not negatives:
            self.stdout.write("none")
        for row in negatives:
            self.stdout.write(f"{row.location.title} | {row.color.name} / {row.size.name} = {row.qty}")

        self.stdout.write("\n=== CURRENT KEY CELLS ===")
        self.stdout.write(f"cream 3XL total = {_stock_qty(darma, 'کرم', '3XL')} (reference after 3 Shahrivar = 77)")
        self.stdout.write(f"grey 4XL total = {_stock_qty(darma, 'طوسی', '4XL')} (reference = 0)")
        self.stdout.write(f"red XXL total = {_stock_qty(darma, 'قرمز', 'XXL')} (corrected reference = 0)")

        product, comps = _code06_state(darma)
        comp_text = ", ".join(f"{row.color.name}×{row.qty}" for row in comps) or "EMPTY"
        self.stdout.write("\n=== CURRENT DARMA 06 COMPOSITION ===")
        self.stdout.write(f"pack_qty={product.pack_qty} | {comp_text}")

    def handle(self, *args, **options):
        if _sum_table(HOME) != EXPECTED_HOME or _sum_table(KHORSHID) != EXPECTED_KHORSHID:
            raise CommandError("ثابت‌های مرجع V24 جمع صحیح ندارند.")
        if EXPECTED_HOME + EXPECTED_KHORSHID != EXPECTED_TOTAL:
            raise CommandError("جمع کل مرجع V24 ناسازگار است.")

        darma = Brand.objects.get(name="دارما")
        sizes, colors, locations = _catalog(darma)
        target_map = _target_map(sizes, colors, locations)

        if not SaleDay.objects.filter(date=BASELINE_DATE).exists():
            raise CommandError(f"صورت مرجع {BASELINE_JALALI} وجود ندارد؛ Reset متوقف شد.")

        self.stdout.write(f"REFERENCE DAY KEPT = {BASELINE_JALALI} ({BASELINE_DATE})")
        self.stdout.write("All SaleDays strictly AFTER this date are the reset target. Payments/receipts/material reports are NOT touched.\n")
        self._write_diagnostics(darma)

        if not options["apply"]:
            self.stdout.write(self.style.WARNING("\nPLAN ONLY: no database changes were made. Use --apply to execute."))
            return

        post_ids = list(
            SaleLine.objects.filter(day__date__gt=BASELINE_DATE).order_by("day__date", "id").values_list("id", flat=True)
        )
        day_count = SaleDay.objects.filter(date__gt=BASELINE_DATE).count()

        with transaction.atomic():
            # Lock target sale rows/days before changing inventory or finance.
            list(SaleDay.objects.select_for_update().filter(date__gt=BASELINE_DATE).values_list("id", flat=True))
            lines = list(
                SaleLine.objects.select_for_update()
                .filter(id__in=post_ids)
                .select_related("day", "product_size__product__brand", "product_size__size")
                .order_by("-day__date", "-id")
            )

            for line in lines:
                line_id = line.id
                line.quantity = 0
                line.save(update_fields=["quantity"])
                sync_sale_inventory_v19(line)
                sync_sale_receivable(line)
                AccountEntry.objects.filter(reference__startswith=f"sale:{line_id}:").delete()
                line.delete()

            SaleDay.objects.filter(date__gt=BASELINE_DATE).delete()

            # Re-entering historical days must be able to fire its after-sale Telegram alert again.
            for marker in AppSetting.objects.filter(key__startswith="telegram_stock_alert:after_sale:"):
                raw_date = marker.key.rsplit(":", 1)[-1]
                try:
                    marker_date = BASELINE_DATE.__class__.fromisoformat(raw_date)
                except Exception:
                    continue
                if marker_date > BASELINE_DATE:
                    marker.delete()

            code06_changed, product06, comps06 = _fix_code06_if_needed(darma)
            deltas = _set_darma_reference(darma, target_map)
            _verify_reference(darma, target_map)

            if SaleLine.objects.filter(day__date__gt=BASELINE_DATE).exists():
                raise CommandError("بعد از Reset هنوز SaleLine بعد از 3 شهریور وجود دارد.")
            if SaleDay.objects.filter(date__gt=BASELINE_DATE).exists():
                raise CommandError("بعد از Reset هنوز SaleDay بعد از 3 شهریور وجود دارد.")

            if _stock_qty(darma, "کرم", "3XL") != 77:
                raise CommandError("کرم 3XL به مرجع 77 نرسید.")
            if _stock_qty(darma, "طوسی", "4XL") != 0:
                raise CommandError("طوسی 4XL به مرجع صفر نرسید.")
            if _stock_qty(darma, "قرمز", "XXL") != 0:
                raise CommandError("قرمز XXL به مرجع صفر نرسید.")

        home, kh = _darma_totals(darma)
        comp_text = ", ".join(f"{row.color.name}×{row.qty}" for row in comps06)
        self.stdout.write(self.style.SUCCESS("\n=== RESET COMPLETE ==="))
        self.stdout.write(f"deleted post-baseline SaleDays = {day_count}")
        self.stdout.write(f"deleted post-baseline SaleLines = {len(post_ids)}")
        self.stdout.write(f"Darma reference adjustments = {len(deltas)} cells")
        self.stdout.write(f"Darma HOME = {home}")
        self.stdout.write(f"Darma KHORSHID = {kh}")
        self.stdout.write(f"Darma TOTAL = {home + kh}")
        self.stdout.write(f"cream 3XL = {_stock_qty(darma, 'کرم', '3XL')}")
        self.stdout.write(f"grey 4XL = {_stock_qty(darma, 'طوسی', '4XL')}")
        self.stdout.write(f"red XXL = {_stock_qty(darma, 'قرمز', 'XXL')}")
        self.stdout.write(f"code 06 fixed during reset = {code06_changed}")
        self.stdout.write(f"code 06 composition = {comp_text}")
        self.stdout.write("3 Shahrivar SaleDay was preserved. Now re-import 4 Shahrivar onward ONE DAY AT A TIME.")