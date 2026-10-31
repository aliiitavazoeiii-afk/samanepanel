from collections import defaultdict
from datetime import date

import jdatetime
from django.core.management.base import BaseCommand
from django.db.models import Sum

from core.business_tools_v22 import _invoice_value
from core.finance import sale_line_metrics
from core.finance_excel_v9 import sale_receivable_value
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.material_purchase_v14 import purchase_data_for_payment
from core.models import (
    Account,
    AccountEntry,
    BusinessPayment,
    ExcelManualRow,
    ExcelManualSetting,
    InventoryModelCost,
    InventoryMovement,
    SaleLine,
    StockBalance,
    TakvinCostRule,
)
from core.report_v5 import _raw_material_context
from core.takvin_pricing_v17 import takvin_cost_for

OPENING_CAPITAL = 5_471_152_736
EXPECTED_PROFIT = 72_012_896
OPENING_DIGIKALA = 872_647_000
EXPECTED_DIGIKALA_PACKS_FROM_UPLOADED_REPORTS = 773


def money(value):
    return f"{int(value or 0):,}"


def read_digikala_state():
    base = int(
        ExcelManualSetting.objects.filter(key="digikala_receivable")
        .values_list("value", flat=True)
        .first()
        or 0
    )
    account = Account.objects.filter(key=Account.DIGIKALA).first()
    ledger = 0
    if account:
        ledger = int(
            account.entries.filter(entry_type__in=["sale", "receipt"])
            .aggregate(v=Sum("delta"))["v"]
            or 0
        )
    return account, base, ledger, base + ledger


def capital_components(digikala_total):
    manual = ExcelManualRow.objects.filter(active=True)
    accounts = sum(
        int(row.amount or 0)
        for row in manual.filter(section__in=[ExcelManualRow.ACCOUNTS, ExcelManualRow.PERSONS])
    )
    assets = sum(
        int(row.amount or 0)
        for row in manual.filter(section=ExcelManualRow.ASSETS)
    )
    finished = int(finished_inventory_value_v17())
    materials = int(_raw_material_context()["materials_total"])
    debt = int(
        ExcelManualSetting.objects.filter(key="takvin_debt")
        .values_list("value", flat=True)
        .first()
        or 0
    )
    total = accounts + assets + finished + materials + int(digikala_total) - debt
    return {
        "accounts": accounts,
        "assets": assets,
        "finished": finished,
        "materials": materials,
        "digikala": int(digikala_total),
        "debt": debt,
        "total": total,
    }


def movement_unit_cost(movement):
    if movement.brand.name == "تکوین":
        return int(takvin_cost_for(movement.size.name, movement.created_at.date()))
    row = InventoryModelCost.objects.filter(
        brand_id=movement.brand_id,
        color_id=movement.color_id,
        size_id=movement.size_id,
    ).first()
    return int(row.unit_cost or 0) if row else 0


class Command(BaseCommand):
    help = "Strictly read-only Shahrivar capital reconciliation."

    def handle(self, *args, **options):
        start = jdatetime.date(1405, 6, 1).togregorian()
        end = date.today()
        expected_capital = OPENING_CAPITAL + EXPECTED_PROFIT

        digi_account, digi_base, digi_all_ledger, digi_total = read_digikala_state()
        comp = capital_components(digi_total)
        live_capital = comp["total"]

        self.stdout.write("=== CAPITAL AUDIT V29B — STRICTLY READ ONLY ===")
        self.stdout.write(f"period                  : {start} .. {end}")
        self.stdout.write(f"31 Mordad capital       : {money(OPENING_CAPITAL)}")
        self.stdout.write(f"user sale profit        : {money(EXPECTED_PROFIT)}")
        self.stdout.write(f"opening + sale profit   : {money(expected_capital)}")
        self.stdout.write(f"LIVE capital            : {money(live_capital)}")
        self.stdout.write(f"CAPITAL GAP             : {money(live_capital - expected_capital)}")

        self.stdout.write("\n=== LIVE COMPONENTS ===")
        self.stdout.write(f"accounts + persons      : {money(comp['accounts'])}")
        self.stdout.write(f"finished inventory      : {money(comp['finished'])}")
        self.stdout.write(f"raw materials           : {money(comp['materials'])}")
        self.stdout.write(f"Digikala receivable     : {money(comp['digikala'])}")
        self.stdout.write(f"assets                  : {money(comp['assets'])}")
        self.stdout.write(f"Takvin debt             : -{money(comp['debt'])}")

        lines = list(
            SaleLine.objects.filter(day__date__gte=start, day__date__lte=end, quantity__gt=0)
            .select_related(
                "day",
                "product_size__product__brand",
                "product_size__product",
                "product_size__size",
            )
            .order_by("day__date", "id")
        )
        total = defaultdict(int)
        by_day = defaultdict(lambda: defaultdict(int))
        by_brand = defaultdict(lambda: defaultdict(int))
        expected_sale_ledger = 0
        actual_sale_ledger = 0
        ledger_errors = []
        digikala_marketplace_packs = 0

        for line in lines:
            m = sale_line_metrics(line)
            brand = line.product_size.product.brand.name
            day_key = line.day.date.isoformat()
            for key in ("gross", "digikala_fee", "cogs", "profit", "shorts", "packs"):
                value = int(m[key] or 0)
                total[key] += value
                by_day[day_key][key] += value
                by_brand[brand][key] += value
            if brand in {"دارما", "تکوین"}:
                digikala_marketplace_packs += int(m["packs"] or 0)

            wanted = int(sale_receivable_value(line))
            expected_sale_ledger += wanted
            if digi_account:
                qs = AccountEntry.objects.filter(
                    account=digi_account,
                    reference=f"sale:{line.id}:digikala",
                    entry_type="sale",
                )
                got = int(qs.aggregate(v=Sum("delta"))["v"] or 0)
                actual_sale_ledger += got
                if qs.count() != (1 if wanted else 0) or got != wanted:
                    ledger_errors.append(
                        f"line={line.id} {day_key} {brand}/{line.product_size.product.code}/"
                        f"{line.product_size.size.name}: expected={wanted} count={qs.count()} got={got}"
                    )

        self.stdout.write("\n=== SHAHRIVAR SALES RECOMPUTED FROM SNAPSHOTS ===")
        self.stdout.write(f"profit                  : {money(total['profit'])}")
        self.stdout.write(f"user profit             : {money(EXPECTED_PROFIT)}")
        self.stdout.write(f"PROFIT GAP              : {money(total['profit'] - EXPECTED_PROFIT)}")
        self.stdout.write(f"gross                   : {money(total['gross'])}")
        self.stdout.write(f"Digikala fees           : {money(total['digikala_fee'])}")
        self.stdout.write(f"COGS                    : {money(total['cogs'])}")
        self.stdout.write(f"all packs / shorts      : {total['packs']} / {total['shorts']}")
        self.stdout.write(
            f"Darma+Takvin packs      : {digikala_marketplace_packs} "
            f"(uploaded reports raw total={EXPECTED_DIGIKALA_PACKS_FROM_UPLOADED_REPORTS})"
        )
        self.stdout.write(
            f"PACK COUNT GAP          : {digikala_marketplace_packs - EXPECTED_DIGIKALA_PACKS_FROM_UPLOADED_REPORTS}"
        )
        for brand in sorted(by_brand):
            b = by_brand[brand]
            self.stdout.write(
                f"  {brand}: profit={money(b['profit'])} gross={money(b['gross'])} "
                f"fee={money(b['digikala_fee'])} cogs={money(b['cogs'])} "
                f"packs={b['packs']} shorts={b['shorts']}"
            )
        self.stdout.write("-- DAY BY DAY --")
        for day_key in sorted(by_day):
            d = by_day[day_key]
            self.stdout.write(
                f"  {day_key}: profit={money(d['profit'])} gross={money(d['gross'])} "
                f"fee={money(d['digikala_fee'])} cogs={money(d['cogs'])} "
                f"packs={d['packs']} shorts={d['shorts']}"
            )

        before_month = month_sales = month_receipts = future = 0
        if digi_account:
            before_month = int(
                digi_account.entries.filter(date__lt=start, entry_type__in=["sale", "receipt"])
                .aggregate(v=Sum("delta"))["v"]
                or 0
            )
            month_sales = int(
                digi_account.entries.filter(date__gte=start, date__lte=end, entry_type="sale")
                .aggregate(v=Sum("delta"))["v"]
                or 0
            )
            month_receipts = int(
                digi_account.entries.filter(date__gte=start, date__lte=end, entry_type="receipt")
                .aggregate(v=Sum("delta"))["v"]
                or 0
            )
            future = int(
                digi_account.entries.filter(date__gt=end, entry_type__in=["sale", "receipt"])
                .aggregate(v=Sum("delta"))["v"]
                or 0
            )

        expected_digi = OPENING_DIGIKALA + month_sales + month_receipts
        digi_gap = digi_total - expected_digi

        self.stdout.write("\n=== DIGIKALA BRIDGE ===")
        self.stdout.write(f"31 Mordad opening      : {money(OPENING_DIGIKALA)}")
        self.stdout.write(f"STORED BASE SETTING    : {money(digi_base)}")
        self.stdout.write(f"base setting gap       : {money(digi_base - OPENING_DIGIKALA)}")
        self.stdout.write(f"ledger before Shahrivar: {money(before_month)}")
        self.stdout.write(f"Shahrivar sale ledger  : {money(month_sales)}")
        self.stdout.write(f"Shahrivar receipts     : {money(month_receipts)}")
        self.stdout.write(f"future-dated ledger    : {money(future)}")
        self.stdout.write(f"all auto ledger        : {money(digi_all_ledger)}")
        self.stdout.write(f"expected current Digi  : {money(expected_digi)}")
        self.stdout.write(f"LIVE current Digi      : {money(digi_total)}")
        self.stdout.write(f"DIGIKALA GAP           : {money(digi_gap)}")
        self.stdout.write(f"expected line ledger   : {money(expected_sale_ledger)}")
        self.stdout.write(f"actual line ledger     : {money(actual_sale_ledger)}")
        if ledger_errors:
            self.stdout.write(self.style.WARNING(f"BAD/MISSING SALE LEDGERS = {len(ledger_errors)}"))
            for item in ledger_errors[:40]:
                self.stdout.write("  " + item)
        else:
            self.stdout.write("sale ledger line check : OK")

        purchase_delta = 0
        self.stdout.write("\n=== MATERIAL PURCHASE CAPITAL DELTAS ===")
        for payment in BusinessPayment.objects.filter(
            date__gte=start,
            date__lte=end,
            payee__in=["fabric", "elastic"],
        ).order_by("date", "id"):
            data = purchase_data_for_payment(payment)
            if not data:
                continue
            stock_value = int(_invoice_value(data))
            paid = int(payment.amount or 0)
            delta = stock_value - paid
            purchase_delta += delta
            self.stdout.write(
                f"  payment #{payment.id} {payment.date}: stock={money(stock_value)} "
                f"cash={money(paid)} delta={money(delta)}"
            )
        self.stdout.write(f"TOTAL PURCHASE DELTA   : {money(purchase_delta)}")

        adjustment_delta = 0
        self.stdout.write("\n=== EXPLICIT FINISHED-INVENTORY ADJUSTMENTS ===")
        adjustments = list(
            InventoryMovement.objects.filter(
                created_at__date__gte=start,
                created_at__date__lte=end,
                movement_type=InventoryMovement.ADJUST,
            )
            .select_related("brand", "size", "color", "location")
            .order_by("created_at", "id")
        )
        for movement in adjustments:
            cost = movement_unit_cost(movement)
            delta = int(movement.delta or 0) * cost
            adjustment_delta += delta
            self.stdout.write(
                f"  #{movement.id} {movement.created_at.date()} {movement.brand.name}/"
                f"{movement.color.name}/{movement.size.name}/{movement.location.key}: "
                f"qty={movement.delta:+d} cost={money(cost)} value_delta={money(delta)} "
                f"ref={movement.reference!r}"
            )
        if not adjustments:
            self.stdout.write("  none")
        self.stdout.write(f"TOTAL ADJUSTMENT DELTA : {money(adjustment_delta)}")

        self.stdout.write("\n=== TAKVIN REVALUATION INDICATOR ===")
        stock_by_size = defaultdict(int)
        for row in (
            StockBalance.objects.filter(brand__name="تکوین")
            .values("size__name")
            .annotate(qty=Sum("qty"))
        ):
            stock_by_size[row["size__name"]] = int(row["qty"] or 0)
        takvin_revaluation = 0
        for size_name in ("M", "L", "XL", "XXL"):
            qty = stock_by_size[size_name]
            start_cost = int(takvin_cost_for(size_name, start))
            now_cost = int(takvin_cost_for(size_name, end))
            delta = qty * (now_cost - start_cost)
            takvin_revaluation += delta
            self.stdout.write(
                f"  {size_name}: qty={qty} cost_start={money(start_cost)} "
                f"cost_now={money(now_cost)} delta={money(delta)}"
            )
        rules = list(
            TakvinCostRule.objects.filter(effective_from__gte=start, effective_from__lte=end)
            .select_related("size")
            .order_by("effective_from", "size__sort_order", "id")
        )
        if rules:
            self.stdout.write("rules changed during Shahrivar:")
            for rule in rules:
                self.stdout.write(f"  {rule.effective_from} {rule.size.name} = {money(rule.unit_cost)}")
        else:
            self.stdout.write("no Takvin cost-rule changes during Shahrivar")
        self.stdout.write(f"TAKVIN REVALUE INDICATOR: {money(takvin_revaluation)}")

        self.stdout.write("\n=== CURRENT MANUAL ROWS ===")
        for section in (ExcelManualRow.ACCOUNTS, ExcelManualRow.PERSONS, ExcelManualRow.ASSETS):
            self.stdout.write(f"[{section}]")
            for row in ExcelManualRow.objects.filter(active=True, section=section).order_by("sort_order", "id"):
                self.stdout.write(f"  #{row.id} {row.title}: {money(row.amount)}")

        self.stdout.write("\n=== QUICK DIAGNOSIS ===")
        self.stdout.write(f"CAPITAL GAP           : {money(live_capital - expected_capital)}")
        self.stdout.write(f"PROFIT GAP            : {money(total['profit'] - EXPECTED_PROFIT)}")
        self.stdout.write(f"DIGIKALA GAP          : {money(digi_gap)}")
        self.stdout.write(f"PURCHASE DELTA        : {money(purchase_delta)}")
        self.stdout.write(f"ADJUSTMENT DELTA      : {money(adjustment_delta)}")
        self.stdout.write(f"TAKVIN REVALUE        : {money(takvin_revaluation)}")
        self.stdout.write(self.style.SUCCESS("CAPITAL AUDIT V29B COMPLETE — NO DATA CHANGED"))
