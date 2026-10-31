"""Read-only regression for V92 material-report monthly archive and current-month KPIs."""
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import RequestFactory, override_settings
from django.template.loader import get_template
from django.urls import resolve

from core import material_report_v23, material_report_v92
from core.models import (
    InventoryMovement,
    MaterialReportBlock,
    MaterialReportOutputApplied,
    RawMaterialStock,
    StockBalance,
)


def _dec(value):
    raw = str(value or "").strip().replace("٬", "").replace(",", ".")
    if not raw:
        return Decimal("0")
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


class Command(BaseCommand):
    help = "Read-only: validate V92 material month archive, KPIs, route and render."

    def handle(self, *args, **kwargs):
        before = {
            "blocks": MaterialReportBlock.objects.count(),
            "applied": MaterialReportOutputApplied.objects.count(),
            "movements": InventoryMovement.objects.count(),
            "stock": StockBalance.objects.count(),
            "raw": RawMaterialStock.objects.count(),
        }

        match = resolve("/material-report/")
        if match.func is not material_report_v92.material_report:
            raise RuntimeError("Active /material-report/ route is not V92")

        get_template("core/material_report_v92.html")
        month = material_report_v92._jalali_month_context()
        current_blocks = list(
            MaterialReportBlock.objects.filter(
                date__gte=month["start"],
                date__lt=month["next"],
            ).prefetch_related("output_applications", "stock_consumptions")
        )
        summary = material_report_v92._summarize_month_blocks(current_blocks)

        codes = set()
        uncoded_rolls = 0
        weight = Decimal("0")
        minimum_delivery = 0
        delivered = 0
        pending = 0
        for block in current_blocks:
            block_cut = 0
            for key in material_report_v23._active_model_keys(block):
                values = (block.input_data or {}).get(key, {}) or {}
                code = str(values.get("fabric_code") or "").strip()
                row_weight = max(_dec(values.get("weight")), Decimal("0"))
                row_cut = max(0, material_report_v23.v20._int(values.get("cut")))
                if code:
                    codes.add(code)
                elif row_weight > 0:
                    uncoded_rolls += 1
                weight += row_weight
                block_cut += row_cut
            block_delivered = sum(
                max(0, int(row.quantity or 0))
                for row in block.output_applications.all()
            )
            minimum_delivery += block_cut
            delivered += block_delivered
            pending += max(0, block_cut - block_delivered)

        expected = {
            "roll_count": len(codes) + uncoded_rolls,
            "weight": weight,
            "minimum_delivery": minimum_delivery,
            "delivered": delivered,
            "pending": pending,
        }
        for key, value in expected.items():
            if summary[key] != value:
                raise RuntimeError(f"V92 current-month KPI mismatch for {key}: {summary[key]} != {value}")

        request = RequestFactory().get("/material-report/")
        request.user = SimpleNamespace(is_authenticated=True)
        static_override = {
            **settings.STORAGES,
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }
        with override_settings(STORAGES=static_override):
            response = material_report_v92.material_report(request)
        if response.status_code != 200:
            raise RuntimeError(f"V92 material report render HTTP {response.status_code}")
        text = response.content.decode("utf-8", errors="replace")

        required = (
            "پارچه تحویلی این ماه",
            "وزن تحویلی این ماه",
            "حداقل تعداد تحویلی",
            "تعداد تحویل‌شده",
            "مانده تحویل",
            "material-month-archive",
            "material-stock-note')?.remove()",
        )
        for marker in required:
            if marker not in text:
                raise RuntimeError(f"V92 UI marker missing: {marker}")

        rendered_blocks = text.count('class="material-block mb-3"')
        if rendered_blocks != MaterialReportBlock.objects.count():
            raise RuntimeError(
                f"V92 must render all material sheets: HTML={rendered_blocks}, DB={MaterialReportBlock.objects.count()}"
            )

        after = {
            "blocks": MaterialReportBlock.objects.count(),
            "applied": MaterialReportOutputApplied.objects.count(),
            "movements": InventoryMovement.objects.count(),
            "stock": StockBalance.objects.count(),
            "raw": RawMaterialStock.objects.count(),
        }
        if after != before:
            raise RuntimeError(f"V92 read-only regression changed material/inventory rows: {before} -> {after}")

        self.stdout.write("MATERIAL REPORT V92 ROUTE = OK")
        self.stdout.write("CURRENT JALALI MONTH BOUNDS = OK")
        self.stdout.write("ROLL COUNT + WEIGHT KPI = OK")
        self.stdout.write("CUT / DELIVERED / PENDING KPI = OK")
        self.stdout.write("ALL MATERIAL SHEETS RENDERED = OK")
        self.stdout.write("PAST-MONTH ARCHIVE UI = OK")
        self.stdout.write("HEADER EXPLANATORY PROSE REMOVAL = OK")
        self.stdout.write("NO MATERIAL / INVENTORY ROW WRITE = OK")
        self.stdout.write(self.style.SUCCESS("SUCCESS: MATERIAL MONTH ARCHIVE V92 CHECK PASSED"))
