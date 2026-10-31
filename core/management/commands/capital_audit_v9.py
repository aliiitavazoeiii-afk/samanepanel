from django.core.management.base import BaseCommand

from core.finance_excel_v9 import digikala_base_receivable, digikala_ledger_total, digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import ExcelManualRow, ExcelManualSetting
from core.report_v5 import _raw_material_context


class Command(BaseCommand):
    help = "Print the exact Excel-Web capital components for finance diagnostics."

    def handle(self, *args, **options):
        accounts = list(ExcelManualRow.objects.filter(active=True, section=ExcelManualRow.ACCOUNTS))
        persons = list(ExcelManualRow.objects.filter(active=True, section=ExcelManualRow.PERSONS))
        assets = list(ExcelManualRow.objects.filter(active=True, section=ExcelManualRow.ASSETS))
        accounts_total = sum(int(row.amount or 0) for row in accounts) + sum(int(row.amount or 0) for row in persons)
        assets_total = sum(int(row.amount or 0) for row in assets)
        finished = int(finished_inventory_value_v17())
        raw = _raw_material_context()
        materials = int(raw["materials_total"])
        inventory = finished + materials
        takvin_obj = ExcelManualSetting.objects.filter(key="takvin_debt").first()
        takvin_debt = int(takvin_obj.value or 0) if takvin_obj else 0
        digi_base = int(digikala_base_receivable())
        digi_ledger = int(digikala_ledger_total())
        digi_total = int(digikala_receivable_total())
        capital = accounts_total + inventory + digi_total - takvin_debt + assets_total

        self.stdout.write("=== CAPITAL AUDIT V17 ===")
        self.stdout.write(f"ACCOUNTS + PERSONS = {accounts_total}")
        self.stdout.write(f"FINISHED INVENTORY  = {finished}")
        self.stdout.write(f"RAW MATERIALS       = {materials}")
        self.stdout.write(f"ASSETS              = {assets_total}")
        self.stdout.write(f"DIGIKALA BASE       = {digi_base}")
        self.stdout.write(f"DIGIKALA AUTO LEDGER= {digi_ledger}")
        self.stdout.write(f"DIGIKALA TOTAL      = {digi_total}")
        self.stdout.write(f"TAKVIN DEBT         = {takvin_debt}")
        self.stdout.write(f"CAPITAL TOTAL       = {capital}")
        self.stdout.write("========================")
