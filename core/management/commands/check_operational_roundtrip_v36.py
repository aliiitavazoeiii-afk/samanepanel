from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum
from django.urls import resolve

from core import business_tools_v21 as v21
from core import business_tools_v22 as v22
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import (
    AccountEntry,
    BusinessPayment,
    DigikalaSettlement,
    ExcelManualRow,
    MoneyMovement,
    RawMaterialStock,
    SaleLine,
    StockBalance,
)
from core.report_v5 import _raw_material_context


class Command(BaseCommand):
    help = "Read/rollback operational endpoint and accounting round-trip guard for v36 UI phase."

    ROUTES = {
        "/payments/": ("core.business_tools_v22", "payments"),
        "/payments/add/": ("core.business_tools_v22", "payment_add"),
        "/payments/1/edit/": ("core.business_tools_v22", "payment_update"),
        "/payments/1/delete/": ("core.business_tools_v22", "payment_delete"),
        "/payments/mellat/set/": ("core.business_tools_v21", "mellat_set"),
        "/payments/receipts/add/": ("core.business_tools_v21", "receipt_add"),
        "/payments/receipts/1/edit/": ("core.business_tools_v21", "receipt_update"),
        "/payments/receipts/1/delete/": ("core.business_tools_v21", "receipt_delete"),
        "/report/": ("core.report_v9", "report"),
        "/report/manual/": ("core.report_v9", "manual_report_action"),
        "/material-report/": ("core.material_report_v22", "material_report"),
        "/material-report/1/save/": ("core.material_report_v22", "material_block_save"),
        "/material-report/1/apply/": ("core.material_report_v22", "material_block_apply_materials"),
        "/material-report/1/apply-output/": ("core.material_report_v22", "material_block_apply_output"),
        "/material-report/1/unapply/": ("core.material_report_v20", "material_block_unapply_materials"),
        "/sales/1/report/": ("core.daily_report_v8", "daily_report"),
        "/sales/report-line/1/price/": ("core.daily_report_actions_v21", "sale_price_update"),
        "/sales/report-line/1/delete/": ("core.daily_report_actions_v21", "sale_line_delete"),
        "/sales/1/return/": ("core.daily_returns_v36", "daily_return_add"),
        "/inventory/": ("core.inventory_v20", "inventory"),
        "/inventory/operations/": ("core.inventory_operations_v15", "inventory_operations"),
    }

    def _row_amount(self, fn):
        row = fn(create=True)
        return int(row.amount or 0)

    def _snapshot(self):
        return {
            "mellat": self._row_amount(v21._mellat_row),
            "tailor": self._row_amount(v21._tailor_row),
            "digi": int(digikala_receivable_total()),
            "finished": int(finished_inventory_value_v17()),
            "raw": int(_raw_material_context()["materials_total"]),
            "stock_qty": int(StockBalance.objects.aggregate(v=Sum("qty"))["v"] or 0),
            "raw_qty_rows": RawMaterialStock.objects.count(),
            "raw_qty_sum": str(RawMaterialStock.objects.aggregate(v=Sum("quantity"))["v"] or 0),
            "payments": BusinessPayment.objects.count(),
            "receipts": DigikalaSettlement.objects.count(),
            "account_entries": AccountEntry.objects.count(),
            "money_movements": MoneyMovement.objects.count(),
            "manual_rows": ExcelManualRow.objects.count(),
            "sales": SaleLine.objects.count(),
        }

    def _check_routes(self):
        for path, (module, name) in self.ROUTES.items():
            func = resolve(path).func
            if func.__module__ != module or func.__name__ != name:
                raise CommandError(
                    f"route drift: {path} -> {func.__module__}.{func.__name__}; "
                    f"expected {module}.{name}"
                )

    def handle(self, *args, **options):
        self._check_routes()

        # Stabilize required manual account rows before the reference snapshot.
        v21._mellat_row(create=True)
        v21._tailor_row(create=True)
        before = self._snapshot()

        with transaction.atomic():
            # 1) Tailor payment: Mellat goes down, tailor account goes up, then exact reverse.
            amount = 12000
            p = BusinessPayment.objects.create(
                date=date.today(), payee="tailor", amount=amount, note="__V36_ROUNDTRIP_TAILOR__"
            )
            parsed = {"purchase": None, "prepayment_title": None}
            v22._apply_full(p, parsed)
            if self._row_amount(v21._mellat_row) != before["mellat"] - amount:
                raise CommandError("tailor payment did not reduce Mellat exactly")
            if self._row_amount(v21._tailor_row) != before["tailor"] + amount:
                raise CommandError("tailor payment did not increase tailor account exactly")
            v22._reverse_full(p)
            if self._row_amount(v21._mellat_row) != before["mellat"]:
                raise CommandError("tailor payment reverse did not restore Mellat")
            if self._row_amount(v21._tailor_row) != before["tailor"]:
                raise CommandError("tailor payment reverse did not restore tailor account")
            p.delete()

            # 2) Material prepayment: cash becomes supplier-account asset, then exact reverse.
            amount = 17000
            p = BusinessPayment.objects.create(
                date=date.today(), payee="fabric", amount=amount, note="__V36_ROUNDTRIP_PREPAY__"
            )
            supplier_title = f"__V36_ROUNDTRIP_SUPPLIER_{p.id}__"
            parsed = {"purchase": None, "prepayment_title": supplier_title}
            v22._apply_full(p, parsed)
            supplier = v21._supplier_account_row(supplier_title, create=False)
            if supplier is None or int(supplier.amount or 0) != amount:
                raise CommandError("material prepayment did not create/increase supplier account exactly")
            if self._row_amount(v21._mellat_row) != before["mellat"] - amount:
                raise CommandError("material prepayment did not reduce Mellat exactly")
            v22._reverse_full(p)
            supplier.refresh_from_db()
            if int(supplier.amount or 0) != 0:
                raise CommandError("material prepayment reverse did not restore supplier account")
            if self._row_amount(v21._mellat_row) != before["mellat"]:
                raise CommandError("material prepayment reverse did not restore Mellat")
            p.delete()

            # 3) Digikala receipt: if receivable exists, transfer 1 toman Digi -> Mellat and reverse it.
            receipt_checked = False
            if before["digi"] > 0:
                amount = 1
                r = DigikalaSettlement.objects.create(date=date.today(), amount=amount, note="__V36_ROUNDTRIP_RECEIPT__")
                mellat = v21._mellat_row(create=True)
                mellat.amount = int(mellat.amount or 0) + amount
                mellat.save(update_fields=["amount", "updated_at"])
                v21._sync_receipt_ledger(r)
                if self._row_amount(v21._mellat_row) != before["mellat"] + amount:
                    raise CommandError("Digikala receipt did not increase Mellat exactly")
                if int(digikala_receivable_total()) != before["digi"] - amount:
                    raise CommandError("Digikala receipt did not reduce receivable exactly")

                mellat = v21._mellat_row(create=True)
                mellat.amount = int(mellat.amount or 0) - amount
                mellat.save(update_fields=["amount", "updated_at"])
                account = v21._digikala_account()
                deleted, _ = AccountEntry.objects.filter(
                    account=account,
                    reference=f"receipt:{r.id}:digikala",
                    entry_type="receipt",
                ).delete()
                if not deleted:
                    raise CommandError("Digikala receipt reverse ledger was not found")
                r.delete()
                if self._row_amount(v21._mellat_row) != before["mellat"]:
                    raise CommandError("Digikala receipt reverse did not restore Mellat")
                if int(digikala_receivable_total()) != before["digi"]:
                    raise CommandError("Digikala receipt reverse did not restore receivable")
                receipt_checked = True

            inside = self._snapshot()
            # The prepayment test leaves a zero-valued supplier row until outer rollback;
            # all economic/accounting values and operational record counts otherwise must match.
            for key in (
                "mellat", "tailor", "digi", "finished", "raw", "stock_qty",
                "raw_qty_rows", "raw_qty_sum", "payments", "receipts", "account_entries",
                "money_movements", "sales",
            ):
                if inside[key] != before[key]:
                    raise CommandError(f"round-trip residual in {key}: before={before[key]} after={inside[key]}")

            transaction.set_rollback(True)

        after = self._snapshot()
        if after != before:
            raise CommandError(f"outer rollback left data changed: before={before} after={after}")

        self.stdout.write("OPERATIONAL ROUNDTRIP V36 CHECK OK")
        self.stdout.write("Payment add/edit/delete routes -> business_tools_v22")
        self.stdout.write("Receipt add/edit/delete routes -> business_tools_v21")
        self.stdout.write("Material/report/sale/inventory routes preserved")
        self.stdout.write("Tailor payment: Mellat -X / tailor +X / reverse exact")
        self.stdout.write("Material prepayment: Mellat -X / supplier +X / reverse exact")
        if before["digi"] > 0:
            self.stdout.write("Digikala receipt: receivable -X / Mellat +X / reverse exact")
        else:
            self.stdout.write("Digikala receipt route checked; value roundtrip skipped because receivable is zero")
        self.stdout.write("FINAL SNAPSHOT: exact match; no business data changed")
