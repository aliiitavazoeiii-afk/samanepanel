from collections import defaultdict
from datetime import date
from decimal import Decimal

import jdatetime
from django.core.management.base import BaseCommand
from django.db.models import Sum

from core.business_tools_v22 import _invoice_value
from core.finance import sale_line_metrics
from core.finance_excel_v9 import (
    digikala_base_receivable,
    digikala_ledger_total,
    digikala_receivable_total,
    sale_receivable_value,
)
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


DEFAULT_OPENING_CAPITAL = 5_471_152_736
DEFAULT_EXPECTED_PROFIT = 72_012_896
DEFAULT_OPENING_DIGIKALA = 872_647_000


def money(value):
    return f"{int(value or 0):,}"


def _capital_components():
    manual = ExcelManualRow.objects.filter(active=True)
    accounts = int(
        sum(
            int(row.amount or 0)
            for row in manual.filter(section__in=[ExcelManualRow.ACCOUNTS, ExcelManualRow.PERSONS])
        )
    )
    assets = int(sum(int(row.amount or 0) for row in manual.filter(section=ExcelManualRow.ASSETS)))
    finished = int(finished_inventory_value_v17())
    materials = int(_raw_material_context()["materials_total"])
    digikala = int(digikala_receivable_total())
    debt = ExcelManualSetting.objects.filter(key="takvin_debt").values_list("value", flat=True).first() or 0
    debt = int(debt)
    total = accounts + assets + finished + materials + digikala - debt
    return {
        "accounts": accounts,
        "assets": assets,
        "finished": finished,
        "materials": materials,
        "digikala": digikala,
        "takvin_debt": debt,
        "capital": total,
    }


def _movement_unit_cost(movement):
    if movement.brand.name == "تکوین":
        return int(takvin_cost_for(movement.size.name, movement.created_at.date()))
    row = InventoryModelCost.objects.filter(
        brand_id=movement.brand_id,
        color_id=movement.color_id,
        size_id=movement.size_id,
    ).first()
    return int(row.unit_cost or 0) if row else 0


class Command(BaseCommand):
    help = "Read-only bridge between 31 Mordad opening capital and current Shahrivar capital."

    def add_arguments(self, parser):
        parser.add_argument("--opening-capital", type=int, default=DEFAULT_OPENING_CAPITAL)
        parser.add_argument("--expected-profit", type=int, default=DEFAULT_EXPECTED_PROFIT)
        parser.add_argument("--opening-digikala", type=int, default=DEFAULT_OPENING_DIGIKALA)

    def handle(self, *args, **options):
        opening_capital = int(options["opening_capital"])
        expected_profit = int(options["expected_profit"])
        opening_digikala = int(options["opening_digikala"])

        start = jdatetime.date(1405, 6, 1).togregorian()
        end = date.today()
        expected_capital = opening_capital + expected_profit
        components = _capital_components()
        current_capital = components["capital"]
        capital_gap = current_capital - expected_capital

        self.stdout.write("=== SHAHRIVAR CAPITAL AUDIT V29 — READ ONLY ===")
        self.stdout.write(f"period              : {start} .. {end}")
        self.stdout.write(f"opening capital     : {money(opening_capital)}")
        self.stdout.write(f"expected sale profit: {money(expected_profit)}")
        self.stdout.write(f"expected capital    : {money(expected_capital)}")
        self.stdout.write(f"LIVE capital        : {money(current_capital)}")
        self.stdout.write(f"LIVE - expected     : {money(capital_gap)}")

        self.stdout.write("\n=== LIVE CAPITAL COMPONENTS ===")
        self.stdout.write(f"accounts + persons  : {money(components['accounts'])}")
        self.stdout.write(f"finished inventory  : {money(components['finished'])}")
        self.stdout.write(f"raw materials       : {money(components['materials'])}")
        self.stdout.write(f"Digikala receivable : {money(components['digikala'])}")
        self.stdout.write(f"assets              : {money(components['assets'])}")
        self.stdout.write(f"Takvin debt         : -{money(components['takvin_debt'])}")

        # Sales: recompute exactly from the same SaleSnapshot-aware metrics used by reports.
        lines = list(
            SaleLine.objects.filter(day__date__gte=start, day__date__lte=end, quantity__gt=0)
            .select_related("day", "product_size__product__brand", "product_size__product", "product_size__size")
            .order_by("day__date", "id")
        )
        totals = defaultdict(int)
        by_brand = defaultdict(lambda: defaultdict(int))
        by_day = defaultdict(lambda: defaultdict(int))
        expected_receivable_from_lines = 0
        receivable_ledger_from_lines = 0
        missing_or_bad_sale_ledger = []
        digi_account = Account.objects.filter(key=Account.DIGIKALA).first()

        for line in lines:
            metrics = sale_line_metrics(line)
            brand = line.product_size.product.brand.name
            day_key = line.day.date.isoformat()
            for key in ("gross", "digikala_fee", "cogs", "profit", "shorts", "packs"):
                value = int(metrics[key] or 0)
                totals[key] += value
                by_brand[brand][key] += value
                by_day[day_key][key] += value

            expected_rec = int(sale_receivable_value(line))
            expected_receivable_from_lines += expected_rec
            if digi_account:
                rows = AccountEntry.objects.filter(
                    account=digi_account,
                    reference=f"sale:{line.id}:digikala",
                    entry_type="sale",
                )
                actual = int(rows.aggregate(v=Sum("delta"))["v"] or 0)
                receivable_ledger_from_lines += actual
                if rows.count() != (1 if expected_rec else 0) or actual != expected_rec:
                    missing_or_bad_sale_ledger.append(
                        f"line={line.id} {day_key} {brand}/{line.product_size.product.code}/{line.product_size.size.name} "
                        f"expected={expected_rec} ledger_count={rows.count()} ledger={actual}"
                    )

        self.stdout.write("\n=== SHAHRIVAR SALES — SAME METRICS AS SITE ===")
        self.stdout.write(f"sale lines           : {len(lines)}")
        self.stdout.write(f"gross sales          : {money(totals['gross'])}")
        self.stdout.write(f"Digikala fees        : {money(totals['digikala_fee'])}")
        self.stdout.write(f"COGS                 : {money(totals['cogs'])}")
        self.stdout.write(f"RECOMPUTED PROFIT    : {money(totals['profit'])}")
        self.stdout.write(f"user expected profit : {money(expected_profit)}")
        self.stdout.write(f"profit difference    : {money(totals['profit'] - expected_profit)}")
        self.stdout.write(f"packs / shorts       : {totals['packs']} / {totals['shorts']}")
        for brand in sorted(by_brand):
            b = by_brand[brand]
            self.stdout.write(
                f"  BRAND {brand}: profit={money(b['profit'])} gross={money(b['gross'])} "
                f"fee={money(b['digikala_fee'])} cogs={money(b['cogs'])} packs={b['packs']} shorts={b['shorts']}"
            )
        self.stdout.write("-- by day --")
        for day_key in sorted(by_day):
            d = by_day[day_key]
            self.stdout.write(
                f"  {day_key}: profit={money(d['profit'])} gross={money(d['gross'])} "
                f"fee={money(d['digikala_fee'])} cogs={money(d['cogs'])} packs={d['packs']} shorts={d['shorts']}"
            )

        # Digikala bridge. Opening amount is explicitly the end-of-31-Mordad receivable.
        digi_base = int(digikala_base_receivable())
        digi_ledger_all = int(digikala_ledger_total())
        if digi_account:
            before_month = int(
                digi_account.entries.filter(
                    date__lt=start, entry_type__in=["sale", "receipt"]
                ).aggregate(v=Sum("delta"))["v"] or 0
            )
            month_sales_ledger = int(
                digi_account.entries.filter(
                    date__gte=start, date__lte=end, entry_type="sale"
                ).aggregate(v=Sum("delta"))["v"] or 0
            )
            month_receipts_ledger = int(
                digi_account.entries.filter(
                    date__gte=start, date__lte=end, entry_type="receipt"
                ).aggregate(v=Sum("delta"))["v"] or 0
            )
            after_today = int(
                digi_account.entries.filter(
                    date__gt=end, entry_type__in=["sale", "receipt"]
                ).aggregate(v=Sum("delta"))["v"] or 0
            )
        else:
            before_month = month_sales_ledger = month_receipts_ledger = after_today = 0

        expected_digi_now = opening_digikala + month_sales_ledger + month_receipts_ledger
        actual_digi_now = int(digikala_receivable_total())
        self.stdout.write("\n=== DIGIKALA RECEIVABLE BRIDGE ===")
        self.stdout.write(f"31 Mordad opening receivable : {money(opening_digikala)}")
        self.stdout.write(f"STORED site base setting      : {money(digi_base)}")
        self.stdout.write(f"stored base - expected base   : {money(digi_base - opening_digikala)}")
        self.stdout.write(f"ledger BEFORE Shahrivar       : {money(before_month)}")
        self.stdout.write(f"Shahrivar sale ledger         : {money(month_sales_ledger)}")
        self.stdout.write(f"Shahrivar receipt ledger      : {money(month_receipts_ledger)}")
        self.stdout.write(f"ledger after today            : {money(after_today)}")
        self.stdout.write(f"ALL auto ledger               : {money(digi_ledger_all)}")
        self.stdout.write(f"expected current receivable   : {money(expected_digi_now)}")
        self.stdout.write(f"LIVE current receivable       : {money(actual_digi_now)}")
        self.stdout.write(f"DIGIKALA GAP                  : {money(actual_digi_now - expected_digi_now)}")
        self.stdout.write(f"sale-line expected ledger     : {money(expected_receivable_from_lines)}")
        self.stdout.write(f"sale-line actual ledger       : {money(receivable_ledger_from_lines)}")
        if missing_or_bad_sale_ledger:
            self.stdout.write(self.style.WARNING(f"BAD/MISSING SALE LEDGERS: {len(missing_or_bad_sale_ledger)}"))
            for item in missing_or_bad_sale_ledger[:30]:
                self.stdout.write("  " + item)
        else:
            self.stdout.write("sale ledger per-line check    : OK")

        # Material purchases can create a real capital delta when invoice value != actual cash paid.
        purchase_gain = 0
        self.stdout.write("\n=== MATERIAL PURCHASE VALUE-vs-CASH DELTAS ===")
        material_payments = BusinessPayment.objects.filter(
            date__gte=start, date__lte=end, payee__in=["fabric", "elastic"]
        ).order_by("date", "id")
        found_purchase = False
        for payment in material_payments:
            data = purchase_data_for_payment(payment)
            if not data:
                continue
            found_purchase = True
            invoice = int(_invoice_value(data))
            paid = int(payment.amount or 0)
            delta = invoice - paid
            purchase_gain += delta
            self.stdout.write(
                f"  payment #{payment.id} {payment.date} {payment.payee}: "
                f"stock_value={money(invoice)} cash_paid={money(paid)} capital_delta={money(delta)}"
            )
        if not found_purchase:
            self.stdout.write("  none")
        self.stdout.write(f"TOTAL purchase valuation delta: {money(purchase_gain)}")

        # Explicit stock adjustments are another non-sale capital source (e.g. physical reconcile).
        adjust_value = 0
        adjustments = list(
            InventoryMovement.objects.filter(
                created_at__date__gte=start,
                created_at__date__lte=end,
                movement_type=InventoryMovement.ADJUST,
            ).select_related("brand", "size", "color", "location").order_by("created_at", "id")
        )
        self.stdout.write("\n=== EXPLICIT FINISHED-STOCK ADJUSTMENTS ===")
        for movement in adjustments:
            unit_cost = _movement_unit_cost(movement)
            value = int(movement.delta or 0) * unit_cost
            adjust_value += value
            self.stdout.write(
                f"  movement #{movement.id} {movement.created_at.date()} "
                f"{movement.brand.name}/{movement.color.name}/{movement.size.name}/{movement.location.key} "
                f"qty={movement.delta:+d} unit_cost={money(unit_cost)} value_delta={money(value)} "
                f"ref={movement.reference!r}"
            )
        if not adjustments:
            self.stdout.write("  none")
        self.stdout.write(f"TOTAL explicit adjustment value: {money(adjust_value)}")

        # Takvin inventory is valued by TODAY'S dated cost rule, unlike historical sale snapshots.
        self.stdout.write("\n=== TAKVIN CURRENT-STOCK REVALUATION CHECK ===")
        takvin_qty = defaultdict(int)
        for row in StockBalance.objects.filter(brand__name="تکوین").values("size__name").annotate(qty=Sum("qty")):
            takvin_qty[row["size__name"]] += int(row["qty"] or 0)
        takvin_revaluation_on_current_stock = 0
        for size_name in ("M", "L", "XL", "XXL"):
            qty = takvin_qty[size_name]
            start_cost = int(takvin_cost_for(size_name, start))
            today_cost = int(takvin_cost_for(size_name, end))
            delta = qty * (today_cost - start_cost)
            takvin_revaluation_on_current_stock += delta
            self.stdout.write(
                f"  {size_name}: qty={qty} cost@1405/06/01={money(start_cost)} "
                f"cost@today={money(today_cost)} current-stock revaluation={money(delta)}"
            )
        rules = TakvinCostRule.objects.filter(effective_from__gte=start, effective_from__lte=end).select_related("size").order_by("effective_from", "size__sort_order", "id")
        if rules.exists():
            self.stdout.write("  rules changed during period:")
            for rule in rules:
                self.stdout.write(
                    f"    {rule.effective_from} {rule.size.name} -> {money(rule.unit_cost)}"
                )
        else:
            self.stdout.write("  no Takvin cost-rule changes during Shahrivar")
        self.stdout.write(
            f"CURRENT-stock rule revaluation indicator: {money(takvin_revaluation_on_current_stock)}"
        )

        # Manual account rows are printed so unexplained current assets can be inspected against the 31-Mordad Excel.
        self.stdout.write("\n=== CURRENT MANUAL ACCOUNTS / PERSONS / ASSETS ===")
        for section in (ExcelManualRow.ACCOUNTS, ExcelManualRow.PERSONS, ExcelManualRow.ASSETS):
            self.stdout.write(f"[{section}]")
            for row in ExcelManualRow.objects.filter(active=True, section=section).order_by("sort_order", "id"):
                self.stdout.write(f"  #{row.id} {row.title}: {money(row.amount)}")

        self.stdout.write("\n=== QUICK DIAGNOSIS NUMBERS ===")
        self.stdout.write(f"capital gap vs opening+profit : {money(capital_gap)}")
        self.stdout.write(f"Digikala gap                  : {money(actual_digi_now - expected_digi_now)}")
        self.stdout.write(f"site-profit vs user-profit gap: {money(totals['profit'] - expected_profit)}")
        self.stdout.write(f"material purchase delta       : {money(purchase_gain)}")
        self.stdout.write(f"explicit stock adjustments    : {money(adjust_value)}")
        self.stdout.write(f"Takvin revaluation indicator  : {money(takvin_revaluation_on_current_stock)}")
        self.stdout.write(self.style.SUCCESS("SHAHRIVAR CAPITAL AUDIT V29 COMPLETE — NO DATA CHANGED"))
