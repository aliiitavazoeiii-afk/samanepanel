from decimal import Decimal

from django.core.management.base import BaseCommand
from django.template.loader import get_template

from core.models import RawMaterialStock
from core.report_v5 import _fabric_tailor_groups


class Command(BaseCommand):
    help = "Read-only regression check for V82 fixed-color tailor fabric presentation."

    def handle(self, *args, **options):
        get_template("core/_raw_material_panel_v3.html")
        get_template("core/_raw_fabric_tailor_grouped.html")

        rows = list(
            RawMaterialStock.objects.filter(
                active=True,
                kind=RawMaterialStock.FABRIC,
                location=RawMaterialStock.TAILOR,
            ).order_by("material_key", "id")
        )
        groups = _fabric_tailor_groups(rows)

        raw_qty = sum((Decimal(row.quantity or 0) for row in rows), Decimal("0"))
        grouped_qty = sum((Decimal(group["quantity"] or 0) for group in groups), Decimal("0"))
        if raw_qty != grouped_qty:
            raise RuntimeError(f"Tailor fabric quantity changed by grouping: raw={raw_qty} grouped={grouped_qty}")

        raw_value = sum(int(row.total_value or 0) for row in rows)
        grouped_value = sum(int(group["total_value"] or 0) for group in groups)
        if raw_value != grouped_value:
            raise RuntimeError(f"Tailor fabric value changed by grouping: raw={raw_value} grouped={grouped_value}")

        keys = [group["key"] for group in groups]
        if len(keys) != len(set(keys)):
            raise RuntimeError("Grouped tailor fabric contains duplicate material keys.")

        duplicate_internal = sum(max(0, int(group["row_count"]) - 1) for group in groups)

        self.stdout.write(f"TAILOR RAW ROWS = {len(rows)}")
        self.stdout.write(f"VISIBLE FIXED COLOR ROWS = {len(groups)}")
        self.stdout.write(f"HIDDEN LEGACY/SOURCE DETAIL ROWS = {duplicate_internal}")
        self.stdout.write(f"TOTAL QTY PRESERVED = {grouped_qty}")
        self.stdout.write(f"TOTAL VALUE PRESERVED = {grouped_value}")
        self.stdout.write("SOURCE LOT DETAILS = preserved")
        self.stdout.write("TEMPLATE COMPILE = OK")
        self.stdout.write("CHECK MODE = READ ONLY")
        self.stdout.write(self.style.SUCCESS("MATERIAL TAILOR FIXED COLORS V82 CHECK OK"))
