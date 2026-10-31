import re

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum
from django.urls import resolve, reverse

from core.business_tools_v22 import _decode_json_ledger, _invoice_value, _settlement_ledger
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.material_purchase_v14 import ledger_for_payment, purchase_data_for_payment
from core.models import (
    AccountEntry, AppSetting, BusinessPayment, DigikalaSettlement, ExcelManualRow,
    ExcelManualSetting, MaterialReportBlock, MoneyMovement, RawMaterialStock,
)
from core.report_v5 import _raw_material_context

PURCHASE_NOTE_RE = re.compile(r"خرید از پرداخت\s*#(\d+)")
PREPAYMENT_PREFIX = "material-prepayment:"


class Command(BaseCommand):
    help = "Audit capital equation and verify all internal-transfer invariants."

    def handle(self, *args, **options):
        errors = []
        warnings = []
        route_checks = {
            "payments": {"core.business_tools_v22"},
            "payment_add": {"core.business_tools_v22"},
            "receipt_add": {"core.business_tools_v21"},
            "material_report": {"core.material_report_v19"},
            "material_block_save": {"core.material_report_v19"},
            "material_block_apply": {"core.material_report_v19"},
            "material_block_apply_output": {"core.material_report_v19"},
            "material_block_unapply": {"core.material_report_v19"},
        }
        for name, allowed_modules in route_checks.items():
            args = [1] if "material_block_" in name else []
            actual = resolve(reverse(name, args=args)).func.__module__
            if actual not in allowed_modules:
                errors.append(f"{name}: {actual} not in {sorted(allowed_modules)}")
            else:
                self.stdout.write(f"route OK: {name} -> {actual}")

        parameter_routes = {
            "payment_update": ({"core.business_tools_v22"}, [1]),
            "payment_delete": ({"core.business_tools_v22"}, [1]),
            "receipt_update": ({"core.business_tools_v21"}, [1]),
            "receipt_delete": ({"core.business_tools_v21"}, [1]),
        }
        for name, (allowed_modules, args) in parameter_routes.items():
            actual = resolve(reverse(name, args=args)).func.__module__
            if actual not in allowed_modules:
                errors.append(f"{name}: {actual} not in {sorted(allowed_modules)}")
            else:
                self.stdout.write(f"route OK: {name} -> {actual}")

        manual = ExcelManualRow.objects.filter(active=True)
        accounts_total = int(sum(row.amount for row in manual.filter(section__in=[ExcelManualRow.ACCOUNTS, ExcelManualRow.PERSONS])))
        assets_total = int(sum(row.amount for row in manual.filter(section=ExcelManualRow.ASSETS)))
        finished = int(finished_inventory_value_v17())
        raw = _raw_material_context()
        materials = int(raw["materials_total"])
        digikala = int(digikala_receivable_total())
        debt_obj = ExcelManualSetting.objects.filter(key="takvin_debt").first()
        takvin_debt = int(debt_obj.value or 0) if debt_obj else 0
        capital = accounts_total + finished + materials + digikala + assets_total - takvin_debt

        self.stdout.write("=== CAPITAL EQUATION V22 ===")
        self.stdout.write(f"ACCOUNTS + PERSONS = {accounts_total}")
        self.stdout.write(f"FINISHED INVENTORY  = {finished}")
        self.stdout.write(f"RAW MATERIALS       = {materials}")
        self.stdout.write(f"ASSETS              = {assets_total}")
        self.stdout.write(f"DIGIKALA RECEIVABLE = {digikala}")
        self.stdout.write(f"TAKVIN DEBT         = {takvin_debt}")
        self.stdout.write(f"CAPITAL TOTAL       = {capital}")
        self.stdout.write("============================")

        for receipt in DigikalaSettlement.objects.all():
            rows = AccountEntry.objects.filter(reference=f"receipt:{receipt.id}:digikala", entry_type="receipt")
            total = int(rows.aggregate(v=Sum("delta"))["v"] or 0)
            if rows.count() != 1 or total != -int(receipt.amount or 0):
                errors.append(f"receipt {receipt.id}: amount={receipt.amount}, ledger_count={rows.count()}, ledger_total={total}")

        for payment in BusinessPayment.objects.filter(payee__in=["fabric", "elastic"]):
            data = purchase_data_for_payment(payment)
            purchase_ledger = ledger_for_payment(payment)
            legacy_prepayment = MoneyMovement.objects.filter(
                kind=MoneyMovement.TRANSFER,
                title=f"{PREPAYMENT_PREFIX}{payment.id}",
            ).order_by("-id").first()
            settlement = _settlement_ledger(payment)

            if legacy_prepayment and settlement:
                errors.append(f"material payment {payment.id}: has both legacy and v22 prepayment ledgers")
                continue

            if data:
                invoice = _invoice_value(data)
                if not purchase_ledger:
                    warnings.append(f"material payment {payment.id}: legacy purchase note only; run v14 repair/backfill")
                elif int(purchase_ledger.amount or 0) != int(payment.amount or 0):
                    errors.append(f"material purchase {payment.id}: payment={payment.amount}, ledger={purchase_ledger.amount}")
                if legacy_prepayment or settlement:
                    errors.append(f"material purchase {payment.id}: received-goods purchase must not have a supplier prepayment ledger")
                self.stdout.write(
                    f"material purchase {payment.id}: invoice_value={invoice} actual_paid={int(payment.amount or 0)}"
                )
            elif settlement:
                payload = _decode_json_ledger(settlement) or {}
                expected_delta = int(payment.amount or 0)
                actual_delta = int(payload.get("delta") or 0)
                if actual_delta != expected_delta:
                    errors.append(f"material prepayment {payment.id}: settlement delta={actual_delta}, expected={expected_delta}")
                if int(settlement.amount or 0) != expected_delta:
                    errors.append(f"material prepayment {payment.id}: settlement amount mismatch")
            elif legacy_prepayment:
                if int(legacy_prepayment.amount or 0) != int(payment.amount or 0):
                    errors.append(f"legacy material prepayment {payment.id}: payment={payment.amount}, ledger={legacy_prepayment.amount}")
            else:
                warnings.append(f"material payment {payment.id}: no purchase/prepayment ledger; edit/delete is blocked")

        orphan_purchase_value = 0
        for stock in RawMaterialStock.objects.filter(active=True).exclude(note=""):
            match = PURCHASE_NOTE_RE.search(stock.note or "")
            if not match:
                continue
            payment_id = int(match.group(1))
            if BusinessPayment.objects.filter(id=payment_id).exists():
                continue
            value = int(stock.total_value or 0)
            orphan_purchase_value += value
            warnings.append(f"orphan material stock row={stock.id} kind={stock.kind} title={stock.title} qty={stock.quantity} value={value} references deleted payment #{payment_id}")
        self.stdout.write(f"ORPHAN MATERIAL VALUE FROM DELETED PAYMENTS = {orphan_purchase_value}")

        legacy_repair_done = AppSetting.objects.filter(key="capital_v14_legacy_repair_done", value="1").exists()
        if not legacy_repair_done:
            warnings.append("legacy v13 orphan-output repair marker is not set")

        applied = 0
        unapplied_with_output = 0
        for block in MaterialReportBlock.objects.select_related("brand").all():
            if not block.brand_id:
                errors.append(f"material report {block.id}: brand is missing")
            if block.stock_consumptions.exists():
                applied += 1
            else:
                has_output = False
                for values in (block.output_data or {}).values():
                    values = values or {}
                    for key, value in values.items():
                        if key == "delivery_date":
                            continue
                        try:
                            if int(float(str(value or 0).replace("٬", "").replace(",", ""))) > 0:
                                has_output = True
                                break
                        except Exception:
                            pass
                    if has_output:
                        break
                if has_output:
                    unapplied_with_output += 1
        self.stdout.write(f"APPLIED MATERIAL REPORTS = {applied}")
        self.stdout.write(f"UNAPPLIED REPORTS WITH ENTERED OUTPUT = {unapplied_with_output}")

        for warning in warnings:
            self.stdout.write(self.style.WARNING("WARNING: " + warning))
        if errors:
            for error in errors:
                self.stderr.write(self.style.ERROR("ERROR: " + error))
            raise CommandError("CAPITAL INTEGRITY V22 FAILED")
        self.stdout.write(self.style.SUCCESS("CAPITAL INTEGRITY V22 OK"))