from collections import defaultdict
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q, Sum

from core.business_tools_v22 import _reverse_full
from core.finance import sale_line_metrics
from core.models import (
    Account,
    AccountEntry,
    AppSetting,
    BusinessPayment,
    DigikalaSettlement,
    ExcelManualRow,
    ExcelManualSetting,
    InventoryMovement,
    MoneyMovement,
    RawMaterialStock,
    SaleDay,
    SaleLine,
    StockBalance,
)
from core.sale_inventory_v19 import sync_sale_inventory_v19


OPENING_DIGIKALA = 872_647_000


def money(value):
    return f"{int(value or 0):,}"


def dec(value):
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal("0")


def stock_totals():
    return {
        row["brand__name"]: int(row["qty"] or 0)
        for row in StockBalance.objects.values("brand__name").annotate(qty=Sum("qty"))
    }


def raw_value():
    total = Decimal("0")
    for row in RawMaterialStock.objects.filter(active=True):
        total += dec(row.quantity) * Decimal(int(row.unit_price or 0))
    return int(total.quantize(Decimal("1")))


def mellat_value():
    row = (
        ExcelManualRow.objects.filter(active=True, section=ExcelManualRow.ACCOUNTS)
        .filter(Q(title__icontains="ملت") | Q(title__iexact="حساب ملت"))
        .order_by("id")
        .first()
    )
    return int(row.amount or 0) if row else 0


def digi_state():
    base = int(
        ExcelManualSetting.objects.filter(key="digikala_receivable")
        .values_list("value", flat=True)
        .first()
        or 0
    )
    account = Account.objects.filter(key=Account.DIGIKALA).first()
    ledger = 0
    sales = 0
    receipts = 0
    if account:
        sales = int(
            account.entries.filter(entry_type="sale").aggregate(v=Sum("delta"))["v"] or 0
        )
        receipts = int(
            account.entries.filter(entry_type="receipt").aggregate(v=Sum("delta"))["v"] or 0
        )
        ledger = int(
            account.entries.filter(entry_type__in=["sale", "receipt"]).aggregate(v=Sum("delta"))["v"] or 0
        )
    return {"base": base, "sales": sales, "receipts": receipts, "ledger": ledger, "total": base + ledger}


def sale_inventory_mismatches(lines):
    errors = []
    for line in lines:
        if int(line.quantity or 0) <= 0:
            continue
        expected = int(sale_line_metrics(line)["shorts"] or 0)
        allocated = int(line.allocations.aggregate(v=Sum("qty"))["v"] or 0)
        if allocated != expected:
            errors.append(
                f"line={line.id} day={line.day.date} "
                f"{line.product_size.product.brand.name}/{line.product_size.product.code}/{line.product_size.size.name} "
                f"qty={line.quantity} expected_shorts={expected} allocations={allocated}"
            )
    return errors


def sale_movement_filter(line_id):
    return (
        Q(reference=f"sale:{line_id}")
        | Q(reference__startswith=f"sale:{line_id}:")
        | Q(reference=f"anbaresh-sale:{line_id}")
        | Q(reference__startswith=f"anbaresh-sale:{line_id}:")
    )


def reverse_and_delete_sales():
    line_ids = list(SaleLine.objects.order_by("-day__date", "-id").values_list("id", flat=True))
    lines = list(
        SaleLine.objects.select_for_update()
        .filter(id__in=line_ids)
        .select_related(
            "day",
            "product_size__product__brand",
            "product_size__product",
            "product_size__size",
        )
        .prefetch_related("allocations")
        .order_by("-day__date", "-id")
    )
    for line in lines:
        line_id = line.id
        line.quantity = 0
        line.save(update_fields=["quantity"])
        # Quantity zero is deliberately used: the service restores the exact historical
        # SaleAllocation rows first, then stops before consulting today's composition.
        sync_sale_inventory_v19(line)
        AccountEntry.objects.filter(
            Q(reference=f"sale:{line_id}:digikala")
            | Q(reference__startswith=f"sale:{line_id}:")
        ).delete()
        InventoryMovement.objects.filter(sale_movement_filter(line_id)).delete()
        line.delete()

    SaleDay.objects.all().delete()

    # Clean historical ghosts from earlier re-import/reset attempts. They are audit rows,
    # not the current stock state, and would make the next day-by-day diagnosis noisy.
    InventoryMovement.objects.filter(
        Q(reference__startswith="sale:") | Q(reference__startswith="anbaresh-sale:")
    ).delete()
    AccountEntry.objects.filter(reference__startswith="sale:").delete()
    AppSetting.objects.filter(key__startswith="telegram_stock_alert:after_sale:").delete()
    return len(line_ids)


def reverse_and_delete_payments():
    ids = list(BusinessPayment.objects.order_by("-date", "-id").values_list("id", flat=True))
    rows = list(BusinessPayment.objects.select_for_update().filter(id__in=ids).order_by("-date", "-id"))
    for payment in rows:
        payment_id = payment.id
        _reverse_full(payment)
        leftovers = MoneyMovement.objects.filter(
            Q(title=f"material-purchase:{payment_id}")
            | Q(title=f"material-settlement:{payment_id}")
            | Q(title=f"material-prepayment:{payment_id}")
        )
        if leftovers.exists():
            raise CommandError(
                f"بعد از Reverse پرداخت #{payment_id} هنوز Ledger وابسته باقی مانده؛ کل Reset rollback شد."
            )
        payment.delete()
    return len(ids)


class Command(BaseCommand):
    help = "Safely reverse and delete ALL SaleDays/SaleLines and ALL BusinessPayments. Digikala receipts are preserved."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Apply the reset. Default is read-only plan.")

    def handle(self, *args, **options):
        apply = bool(options["apply"])

        days = list(SaleDay.objects.order_by("date").values_list("date", flat=True))
        lines = list(
            SaleLine.objects.select_related(
                "day", "product_size__product__brand", "product_size__product", "product_size__size"
            ).prefetch_related("allocations").order_by("day__date", "id")
        )
        payments = list(BusinessPayment.objects.order_by("date", "id"))
        receipts = list(DigikalaSettlement.objects.order_by("date", "id"))

        sale_totals = defaultdict(int)
        for line in lines:
            if int(line.quantity or 0) <= 0:
                continue
            metrics = sale_line_metrics(line)
            sale_totals["packs"] += int(metrics["packs"] or 0)
            sale_totals["shorts"] += int(metrics["shorts"] or 0)
            sale_totals["profit"] += int(metrics["profit"] or 0)

        payment_total = sum(int(row.amount or 0) for row in payments)
        payment_by_payee = defaultdict(lambda: {"count": 0, "amount": 0})
        for row in payments:
            payment_by_payee[row.payee]["count"] += 1
            payment_by_payee[row.payee]["amount"] += int(row.amount or 0)

        receipt_total = sum(int(row.amount or 0) for row in receipts)
        before_stock = stock_totals()
        before_raw = raw_value()
        before_mellat = mellat_value()
        before_digi = digi_state()

        self.stdout.write("=== FULL SALES + PAYMENTS RESET V30 ===")
        self.stdout.write("Mode: " + ("APPLY" if apply else "READ-ONLY PLAN"))
        self.stdout.write("\n--- SALES TO DELETE ---")
        self.stdout.write(f"SaleDays: {len(days)}")
        if days:
            self.stdout.write(f"date range: {days[0]} .. {days[-1]}")
        self.stdout.write(f"SaleLines: {len(lines)}")
        self.stdout.write(f"packs / shorts: {sale_totals['packs']} / {sale_totals['shorts']}")
        self.stdout.write(f"sale profit represented: {money(sale_totals['profit'])}")

        mismatches = sale_inventory_mismatches(lines)
        self.stdout.write(f"allocation mismatches: {len(mismatches)}")
        for item in mismatches[:20]:
            self.stdout.write("  " + item)
        if mismatches:
            raise CommandError(
                "فروش‌هایی وجود دارند که Allocation آنها با تعداد شورت فروش برابر نیست. "
                "برای جلوگیری از خراب‌شدن موجودی Reset متوقف شد."
            )

        self.stdout.write("\n--- PAYMENTS TO DELETE ---")
        self.stdout.write(f"BusinessPayments: {len(payments)} | total cash={money(payment_total)}")
        for payee in sorted(payment_by_payee):
            row = payment_by_payee[payee]
            self.stdout.write(f"  {payee}: count={row['count']} amount={money(row['amount'])}")

        self.stdout.write("\n--- PRESERVED ---")
        self.stdout.write(f"Digikala receipts: {len(receipts)} | total={money(receipt_total)} | WILL NOT BE DELETED")
        self.stdout.write("Material reports, manual accounts, assets, catalog and physical adjustment movements are preserved.")

        self.stdout.write("\n--- BEFORE STATE ---")
        self.stdout.write("stock totals: " + ", ".join(f"{k}={v}" for k, v in sorted(before_stock.items())))
        self.stdout.write(f"raw materials value: {money(before_raw)}")
        self.stdout.write(f"Mellat: {money(before_mellat)}")
        self.stdout.write(
            f"Digikala: base={money(before_digi['base'])} sales={money(before_digi['sales'])} "
            f"receipts={money(before_digi['receipts'])} total={money(before_digi['total'])}"
        )

        if not apply:
            # Prove payment reversal is possible without committing any change.
            try:
                with transaction.atomic():
                    sim_rows = list(
                        BusinessPayment.objects.select_for_update().all().order_by("-date", "-id")
                    )
                    for payment in sim_rows:
                        _reverse_full(payment)
                    transaction.set_rollback(True)
            except Exception as exc:
                raise CommandError(f"Payment reverse preflight failed: {exc}") from exc
            self.stdout.write("payment reverse simulation: OK (rolled back)")
            self.stdout.write("\nREAD-ONLY PLAN COMPLETE — NO DATA CHANGED")
            self.stdout.write("Run again with --apply only after a database backup exists.")
            return

        with transaction.atomic():
            # Lock high-level rows up front so this is a single coherent reset.
            list(SaleDay.objects.select_for_update().values_list("id", flat=True))
            list(BusinessPayment.objects.select_for_update().values_list("id", flat=True))

            deleted_lines = reverse_and_delete_sales()
            deleted_payments = reverse_and_delete_payments()

            digi_setting, _ = ExcelManualSetting.objects.select_for_update().get_or_create(
                key="digikala_receivable",
                defaults={"label": "طلب پایه دیجی‌کالا", "value": OPENING_DIGIKALA},
            )
            digi_setting.value = OPENING_DIGIKALA
            digi_setting.label = "طلب پایه دیجی‌کالا"
            digi_setting.save(update_fields=["value", "label", "updated_at"])

            if SaleDay.objects.exists() or SaleLine.objects.exists():
                raise CommandError("بعد از Reset هنوز صورت روزانه/SaleLine وجود دارد؛ rollback شد.")
            if BusinessPayment.objects.exists():
                raise CommandError("بعد از Reset هنوز BusinessPayment وجود دارد؛ rollback شد.")
            if AccountEntry.objects.filter(reference__startswith="sale:").exists():
                raise CommandError("بعد از Reset هنوز sale AccountEntry باقی مانده؛ rollback شد.")
            if InventoryMovement.objects.filter(
                Q(reference__startswith="sale:") | Q(reference__startswith="anbaresh-sale:")
            ).exists():
                raise CommandError("بعد از Reset هنوز sale InventoryMovement باقی مانده؛ rollback شد.")

        after_stock = stock_totals()
        after_raw = raw_value()
        after_mellat = mellat_value()
        after_digi = digi_state()

        self.stdout.write(self.style.SUCCESS("\n=== RESET COMPLETE ==="))
        self.stdout.write(f"deleted SaleLines: {deleted_lines}")
        self.stdout.write(f"deleted SaleDays: {len(days)}")
        self.stdout.write(f"deleted BusinessPayments: {deleted_payments}")
        self.stdout.write(f"preserved Digikala receipts: {len(receipts)}")
        self.stdout.write("sale/account/inventory audit ghosts: CLEARED")
        self.stdout.write(f"Digikala opening base forced to: {money(OPENING_DIGIKALA)}")
        self.stdout.write("\n--- AFTER STATE ---")
        self.stdout.write("stock totals: " + ", ".join(f"{k}={v}" for k, v in sorted(after_stock.items())))
        self.stdout.write(f"raw materials value: {money(after_raw)}")
        self.stdout.write(f"Mellat: {money(after_mellat)}")
        self.stdout.write(
            f"Digikala: base={money(after_digi['base'])} sales={money(after_digi['sales'])} "
            f"receipts={money(after_digi['receipts'])} total={money(after_digi['total'])}"
        )
        self.stdout.write("\nNEXT: re-enter ONLY 1405/06/01, then 1405/06/02, then 1405/06/03. Do not enter later days yet.")
        self.stdout.write("After day 3, set the physical inventory reference; then continue one day at a time.")
