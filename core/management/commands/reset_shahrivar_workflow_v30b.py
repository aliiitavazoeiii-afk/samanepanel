from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

from core import business_tools_v21 as v21
from core.dateutils import parse_jalali_date
from core.finance_excel_v9 import digikala_receivable_total
from core.models import (
    Account,
    AccountEntry,
    AppSetting,
    BusinessPayment,
    DigikalaSettlement,
    MoneyMovement,
    RawMaterialStock,
    SaleDay,
    SaleLine,
)
from core.report_v5 import _raw_material_context
from core.sale_inventory_v19 import sync_sale_inventory_v19


START_JALALI = "1405/06/01"
BASELINE_NOTE = "موجودی پایه پس از پاکسازی تاریخچه پرداخت‌های شهریور V30B"


def _mellat_amount():
    row = v21._mellat_row(create=False)
    return int(row.amount or 0) if row else 0


def _counts(start):
    sale_days = SaleDay.objects.filter(date__gte=start)
    sale_lines = SaleLine.objects.filter(day__date__gte=start)
    payments = BusinessPayment.objects.filter(date__gte=start)
    receipts = DigikalaSettlement.objects.filter(date__gte=start)
    return {
        "sale_days": sale_days.count(),
        "sale_lines": sale_lines.count(),
        "sale_packs": int(sale_lines.aggregate(v=Sum("quantity"))["v"] or 0),
        "payments": payments.count(),
        "payment_amount": int(payments.aggregate(v=Sum("amount"))["v"] or 0),
        "receipts": receipts.count(),
        "receipt_amount": int(receipts.aggregate(v=Sum("amount"))["v"] or 0),
    }


def _payment_ledger_titles(payment_id):
    pid = int(payment_id)
    return [
        f"material-purchase:{pid}",
        f"material-settlement:{pid}",
        f"material-prepayment:{pid}",
    ]


class Command(BaseCommand):
    help = (
        "Reset Shahrivar sales/receipts and clear Shahrivar payment history while preserving "
        "the current balance-sheet effects of those payments. Default is read-only."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        start = parse_jalali_date(START_JALALI)
        before = _counts(start)
        raw_before = int(_raw_material_context()["materials_total"])
        mellat_before = _mellat_amount()
        digi_before = int(digikala_receivable_total())

        self.stdout.write("=== SHAHRIVAR WORKFLOW RESET V30B ===")
        self.stdout.write(f"boundary: {START_JALALI} ({start})")
        self.stdout.write("31 Mordad and earlier are PRESERVED.")
        self.stdout.write("Physical/manual inventory adjustments are PRESERVED.")
        self.stdout.write("Outgoing payments are REBASED: their rows/ledgers are removed, but their current economic effects are preserved.")
        self.stdout.write("Therefore old outgoing payments MUST NOT be re-entered after this reset.")
        self.stdout.write("")
        self.stdout.write(f"SaleDays to remove       : {before['sale_days']}")
        self.stdout.write(f"SaleLines to reverse     : {before['sale_lines']}")
        self.stdout.write(f"Sale packs to reverse    : {before['sale_packs']}")
        self.stdout.write(f"Payments to rebase/remove: {before['payments']} / {before['payment_amount']:,}")
        self.stdout.write(f"Digi receipts to reverse : {before['receipts']} / {before['receipt_amount']:,}")
        self.stdout.write(f"Mellat before            : {mellat_before:,}")
        self.stdout.write(f"Digikala before          : {digi_before:,}")
        self.stdout.write(f"Raw materials before     : {raw_before:,}")

        if not options["apply"]:
            self.stdout.write("")
            self.stdout.write("READ ONLY. Run again with --apply after database backup.")
            return

        try:
            with transaction.atomic():
                # 1) Rebase outgoing payments. We intentionally do NOT reverse their balance-sheet
                # effects because the user confirmed current raw-material balances are the wanted
                # baseline and some purchased fabric has already moved/been consumed.
                payments = list(
                    BusinessPayment.objects.select_for_update()
                    .filter(date__gte=start)
                    .order_by("-date", "-id")
                )
                payment_ids = [p.id for p in payments]
                for payment in payments:
                    self.stdout.write(
                        f"rebase payment #{payment.id} {payment.date} {payment.payee} amount={int(payment.amount or 0):,}"
                    )
                    MoneyMovement.objects.filter(title__in=_payment_ledger_titles(payment.id)).delete()
                    payment.delete()

                # Any aggregate raw-material row whose note points to one of the deleted payment
                # records becomes an explicit baseline row. Quantity and unit price are untouched.
                baseline_rows = 0
                for pid in payment_ids:
                    qs = RawMaterialStock.objects.select_for_update().filter(active=True).filter(
                        note__in=[
                            f"خرید از پرداخت #{pid}",
                            f"مانده پس از حذف خرید #{pid}",
                        ]
                    )
                    baseline_rows += qs.update(note=BASELINE_NOTE)
                self.stdout.write(f"raw-material rows relabeled as baseline: {baseline_rows}")

                raw_after_payment_rebase = int(_raw_material_context()["materials_total"])
                if raw_after_payment_rebase != raw_before:
                    raise CommandError(
                        f"raw-material value changed during payment rebase: before={raw_before}, after={raw_after_payment_rebase}"
                    )
                if _mellat_amount() != mellat_before:
                    raise CommandError(
                        f"Mellat changed during payment rebase: before={mellat_before}, after={_mellat_amount()}"
                    )

                # 2) Reverse Digikala receipts. These are pure internal transfers and can be
                # reversed exactly: Mellat decreases and receivable returns by the same amount.
                receipts = list(
                    DigikalaSettlement.objects.select_for_update()
                    .filter(date__gte=start)
                    .order_by("-date", "-id")
                )
                digi_account = Account.objects.filter(key=Account.DIGIKALA).first()
                if receipts and digi_account is None:
                    raise CommandError("Digikala Account row is missing; cannot reverse receipts safely.")
                for receipt in receipts:
                    amount = int(receipt.amount or 0)
                    mellat = v21._mellat_row(create=True)
                    mellat.amount = int(mellat.amount or 0) - amount
                    mellat.save(update_fields=["amount", "updated_at"])
                    deleted, _ = AccountEntry.objects.filter(
                        account=digi_account,
                        reference=f"receipt:{receipt.id}:digikala",
                        entry_type="receipt",
                    ).delete()
                    if not deleted:
                        raise CommandError(
                            f"receipt #{receipt.id}: Digikala ledger missing; full reset rolled back."
                        )
                    self.stdout.write(f"reverse receipt #{receipt.id} {receipt.date} amount={amount:,}")
                    receipt.delete()

                # 3) Reverse every sale allocation before deleting SaleLines. Existing allocation
                # rows are authoritative for the exact colors previously deducted.
                lines = list(
                    SaleLine.objects.select_for_update()
                    .filter(day__date__gte=start)
                    .select_related(
                        "day",
                        "product_size__product__brand",
                        "product_size__product",
                        "product_size__size",
                    )
                    .order_by("-day__date", "-id")
                )
                for line in lines:
                    old_qty = int(line.quantity or 0)
                    line.quantity = 0
                    line.save(update_fields=["quantity"])
                    sync_sale_inventory_v19(line)
                    AccountEntry.objects.filter(reference=f"sale:{line.id}:digikala").delete()
                    self.stdout.write(
                        f"reverse sale line #{line.id} {line.day.date} "
                        f"{line.product_size.product.brand.name}/{line.product_size.product.code}/"
                        f"{line.product_size.size.name} packs={old_qty}"
                    )
                    line.delete()

                SaleDay.objects.filter(date__gte=start).delete()

                # Telegram after-sale markers must not suppress alerts when days are re-entered.
                AppSetting.objects.filter(key__startswith="telegram_stock_alert:after_sale:").delete()

                after = _counts(start)
                if any(after[key] for key in ("sale_days", "sale_lines", "payments", "receipts")):
                    raise CommandError(f"post-reset workflow rows remain: {after}")

                raw_final = int(_raw_material_context()["materials_total"])
                if raw_final != raw_before:
                    raise CommandError(
                        f"raw-material value changed during reset: before={raw_before}, after={raw_final}"
                    )

        except Exception as exc:
            if isinstance(exc, CommandError):
                raise
            raise CommandError(f"RESET FAILED; database transaction rolled back: {exc}") from exc

        self.stdout.write("")
        self.stdout.write("=== RESET COMPLETE V30B ===")
        self.stdout.write("SaleDays from 1 Shahrivar onward = 0")
        self.stdout.write("SaleLines from 1 Shahrivar onward = 0")
        self.stdout.write("Payment rows from 1 Shahrivar onward = 0 (effects preserved as baseline)")
        self.stdout.write("Digikala receipts from 1 Shahrivar onward = 0 (effects reversed)")
        self.stdout.write(f"Mellat after          = {_mellat_amount():,}")
        self.stdout.write(f"Digikala after        = {int(digikala_receivable_total()):,}")
        self.stdout.write(f"Raw materials after   = {int(_raw_material_context()['materials_total']):,}")
        self.stdout.write("31 Mordad and earlier preserved.")
        self.stdout.write("Physical/manual stock adjustments preserved.")
        self.stdout.write("IMPORTANT: do NOT re-enter the deleted outgoing payments; only re-enter daily sales.")
        self.stdout.write("Next: enter ONLY 1, 2 and 3 Shahrivar sales; then restore/check the exact physical day-3 inventory baseline.")
