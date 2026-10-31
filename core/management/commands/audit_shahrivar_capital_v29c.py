from collections import defaultdict
from datetime import date

import jdatetime
from django.core.management.base import BaseCommand
from django.db.models import Sum

from core.business_tools_v22 import _invoice_value
from core.finance import sale_line_metrics
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.material_purchase_v14 import purchase_data_for_payment
from core.models import (
    Account,
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


def money(v):
    return f"{int(v or 0):,}"


def movement_cost(m):
    if m.brand.name == "تکوین":
        return int(takvin_cost_for(m.size.name, m.created_at.date()))
    row = InventoryModelCost.objects.filter(
        brand_id=m.brand_id,
        color_id=m.color_id,
        size_id=m.size_id,
    ).first()
    return int(row.unit_cost or 0) if row else 0


class Command(BaseCommand):
    help = "Compact strictly read-only Shahrivar capital audit; groups adjustment movements instead of printing every row."

    def handle(self, *args, **options):
        start = jdatetime.date(1405, 6, 1).togregorian()
        end = date.today()

        manual = ExcelManualRow.objects.filter(active=True)
        accounts = sum(
            int(r.amount or 0)
            for r in manual.filter(section__in=[ExcelManualRow.ACCOUNTS, ExcelManualRow.PERSONS])
        )
        assets = sum(int(r.amount or 0) for r in manual.filter(section=ExcelManualRow.ASSETS))
        finished = int(finished_inventory_value_v17())
        materials = int(_raw_material_context()["materials_total"])
        debt = int(
            ExcelManualSetting.objects.filter(key="takvin_debt").values_list("value", flat=True).first() or 0
        )

        digi_base = int(
            ExcelManualSetting.objects.filter(key="digikala_receivable").values_list("value", flat=True).first() or 0
        )
        digi_account = Account.objects.filter(key=Account.DIGIKALA).first()
        if digi_account:
            digi_all_ledger = int(
                digi_account.entries.filter(entry_type__in=["sale", "receipt"]).aggregate(v=Sum("delta"))["v"] or 0
            )
            digi_month_sales = int(
                digi_account.entries.filter(date__gte=start, date__lte=end, entry_type="sale").aggregate(v=Sum("delta"))["v"] or 0
            )
            digi_month_receipts = int(
                digi_account.entries.filter(date__gte=start, date__lte=end, entry_type="receipt").aggregate(v=Sum("delta"))["v"] or 0
            )
        else:
            digi_all_ledger = digi_month_sales = digi_month_receipts = 0
        digi_total = digi_base + digi_all_ledger

        live_capital = accounts + assets + finished + materials + digi_total - debt
        expected_sales_only = OPENING_CAPITAL + EXPECTED_PROFIT

        lines = list(
            SaleLine.objects.filter(day__date__gte=start, day__date__lte=end, quantity__gt=0)
            .select_related("product_size__product__brand", "product_size__product", "product_size__size")
        )
        recomputed_profit = sum(int(sale_line_metrics(line)["profit"] or 0) for line in lines)
        packs = sum(int(line.quantity or 0) for line in lines if line.product_size.product.brand.name in {"دارما", "تکوین"})

        purchase_delta = 0
        purchase_rows = []
        for payment in BusinessPayment.objects.filter(
            date__gte=start, date__lte=end, payee__in=["fabric", "elastic"]
        ).order_by("date", "id"):
            data = purchase_data_for_payment(payment)
            if not data:
                continue
            stock_value = int(_invoice_value(data))
            paid = int(payment.amount or 0)
            delta = stock_value - paid
            purchase_delta += delta
            purchase_rows.append((payment.id, payment.date, stock_value, paid, delta))

        grouped = defaultdict(lambda: {"count": 0, "qty": 0, "value": 0})
        sale_recalc = {"count": 0, "qty": 0, "value": 0}
        for m in (
            InventoryMovement.objects.filter(
                created_at__date__gte=start,
                created_at__date__lte=end,
                movement_type=InventoryMovement.ADJUST,
            )
            .select_related("brand", "size", "color", "location")
            .order_by("id")
        ):
            cost = movement_cost(m)
            value = int(m.delta or 0) * cost
            ref = str(m.reference or "(blank)")
            if ref.startswith("sale:") and ref.endswith(":recalc"):
                sale_recalc["count"] += 1
                sale_recalc["qty"] += int(m.delta or 0)
                sale_recalc["value"] += value
                continue
            g = grouped[ref]
            g["count"] += 1
            g["qty"] += int(m.delta or 0)
            g["value"] += value

        true_adjustment_total = sum(v["value"] for v in grouped.values())

        takvin_revalue = 0
        stock_by_size = defaultdict(int)
        for row in StockBalance.objects.filter(brand__name="تکوین").values("size__name").annotate(qty=Sum("qty")):
            stock_by_size[row["size__name"]] = int(row["qty"] or 0)
        takvin_rows = []
        for size_name in ("M", "L", "XL", "XXL"):
            qty = stock_by_size[size_name]
            c0 = int(takvin_cost_for(size_name, start))
            c1 = int(takvin_cost_for(size_name, end))
            delta = qty * (c1 - c0)
            takvin_revalue += delta
            takvin_rows.append((size_name, qty, c0, c1, delta))

        expected_with_detected = expected_sales_only + purchase_delta + true_adjustment_total + takvin_revalue

        self.stdout.write("=== CAPITAL AUDIT V29C — COMPACT / STRICTLY READ ONLY ===")
        self.stdout.write(f"31 Mordad capital              : {money(OPENING_CAPITAL)}")
        self.stdout.write(f"Shahrivar recomputed profit    : {money(recomputed_profit)}")
        self.stdout.write(f"user expected profit           : {money(EXPECTED_PROFIT)}")
        self.stdout.write(f"profit gap                     : {money(recomputed_profit - EXPECTED_PROFIT)}")
        self.stdout.write(f"sales-only expected capital    : {money(expected_sales_only)}")
        self.stdout.write(f"LIVE capital                   : {money(live_capital)}")
        self.stdout.write(f"LIVE - sales-only expected     : {money(live_capital - expected_sales_only)}")
        self.stdout.write(f"Darma+Takvin packs in DB       : {packs}")

        self.stdout.write("\n=== CURRENT CAPITAL COMPONENTS ===")
        self.stdout.write(f"accounts + persons             : {money(accounts)}")
        self.stdout.write(f"finished inventory             : {money(finished)}")
        self.stdout.write(f"raw materials                  : {money(materials)}")
        self.stdout.write(f"Digikala receivable            : {money(digi_total)}")
        self.stdout.write(f"assets                         : {money(assets)}")
        self.stdout.write(f"Takvin debt                    : -{money(debt)}")

        self.stdout.write("\n=== DIGIKALA ===")
        expected_digi = OPENING_DIGIKALA + digi_month_sales + digi_month_receipts
        self.stdout.write(f"31 Mordad opening              : {money(OPENING_DIGIKALA)}")
        self.stdout.write(f"stored base                    : {money(digi_base)}")
        self.stdout.write(f"Shahrivar sales ledger         : {money(digi_month_sales)}")
        self.stdout.write(f"Shahrivar receipts ledger      : {money(digi_month_receipts)}")
        self.stdout.write(f"expected current Digi          : {money(expected_digi)}")
        self.stdout.write(f"LIVE current Digi              : {money(digi_total)}")
        self.stdout.write(f"Digi gap                       : {money(digi_total - expected_digi)}")

        self.stdout.write("\n=== MATERIAL PURCHASE DELTAS ===")
        for pid, pdate, stock_value, paid, delta in purchase_rows:
            self.stdout.write(
                f"payment #{pid} {pdate}: stock={money(stock_value)} cash={money(paid)} delta={money(delta)}"
            )
        self.stdout.write(f"TOTAL purchase delta           : {money(purchase_delta)}")

        self.stdout.write("\n=== TRUE ADJUSTMENTS GROUPED BY REFERENCE ===")
        if grouped:
            for ref, g in sorted(grouped.items(), key=lambda item: item[0]):
                self.stdout.write(
                    f"{ref}: rows={g['count']} net_qty={g['qty']:+d} net_value={money(g['value'])}"
                )
        else:
            self.stdout.write("none")
        self.stdout.write(f"TOTAL true adjustment value    : {money(true_adjustment_total)}")
        self.stdout.write(
            f"sale:*:recalc noise excluded   : rows={sale_recalc['count']} "
            f"net_qty={sale_recalc['qty']:+d} net_value={money(sale_recalc['value'])}"
        )

        self.stdout.write("\n=== TAKVIN REVALUATION ===")
        for size_name, qty, c0, c1, delta in takvin_rows:
            self.stdout.write(
                f"{size_name}: qty={qty} start_cost={money(c0)} now_cost={money(c1)} delta={money(delta)}"
            )
        rules = list(
            TakvinCostRule.objects.filter(effective_from__gte=start, effective_from__lte=end)
            .select_related("size")
            .order_by("effective_from", "size__sort_order", "id")
        )
        if rules:
            for rule in rules:
                self.stdout.write(f"rule: {rule.effective_from} {rule.size.name} -> {money(rule.unit_cost)}")
        else:
            self.stdout.write("no cost-rule change during Shahrivar")
        self.stdout.write(f"TOTAL Takvin revaluation       : {money(takvin_revalue)}")

        self.stdout.write("\n=== BRIDGE ===")
        self.stdout.write(f"opening capital                : {money(OPENING_CAPITAL)}")
        self.stdout.write(f"+ sale profit                  : {money(EXPECTED_PROFIT)}")
        self.stdout.write(f"+ purchase value/cash delta    : {money(purchase_delta)}")
        self.stdout.write(f"+ true inventory adjustments   : {money(true_adjustment_total)}")
        self.stdout.write(f"+ Takvin current revaluation   : {money(takvin_revalue)}")
        self.stdout.write(f"= detected-event expectation   : {money(expected_with_detected)}")
        self.stdout.write(f"LIVE capital                   : {money(live_capital)}")
        self.stdout.write(f"UNEXPLAINED RESIDUAL           : {money(live_capital - expected_with_detected)}")

        self.stdout.write("\n=== CURRENT MANUAL ROWS ===")
        for section in (ExcelManualRow.ACCOUNTS, ExcelManualRow.PERSONS, ExcelManualRow.ASSETS):
            self.stdout.write(f"[{section}]")
            for row in ExcelManualRow.objects.filter(active=True, section=section).order_by("sort_order", "id"):
                self.stdout.write(f"  {row.title}: {money(row.amount)}")

        self.stdout.write(self.style.SUCCESS("CAPITAL AUDIT V29C COMPLETE — NO DATA CHANGED"))