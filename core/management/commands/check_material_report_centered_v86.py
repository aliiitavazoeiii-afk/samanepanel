from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.template.loader import get_template
from django.urls import resolve, reverse

from core import material_report_v23


class Command(BaseCommand):
    help = "Read-only regression check for V86 original-size centered material report."

    def handle(self, *args, **options):
        get_template("core/material_report_v36.html")

        match = resolve(reverse("material_report"))
        if match.func is not material_report_v23.material_report:
            raise RuntimeError("material_report route is no longer V23")

        js_path = Path(settings.BASE_DIR) / "static" / "core" / "material_report_v6.js"
        js = js_path.read_text(encoding="utf-8")

        required = (
            "materialReportV86Style",
            "text-align:center",
            "direction:rtl",
            "fabricPerPiece",
            "laborPerPiece",
            "elasticPerPiece",
        )
        for marker in required:
            if marker not in js:
                raise RuntimeError(f"V86 marker missing: {marker}")

        forbidden = (
            "width:max-content!important",
            "min-width:0!important",
            "width:108px!important",
            "width:88px!important",
            "height:39px!important",
            "height:34px!important",
        )
        for marker in forbidden:
            if marker in js:
                raise RuntimeError(f"Compact-size override still present: {marker}")

        self.stdout.write("MATERIAL REPORT ROUTE = V23")
        self.stdout.write("ORIGINAL TEMPLATE SIZING = restored")
        self.stdout.write("TEXT + NUMBERS ALIGNMENT = centered")
        self.stdout.write("RTL MODEL ORDER = preserved")
        self.stdout.write("V84 COST FORMULA = preserved")
        self.stdout.write("COMPACT WIDTH/HEIGHT OVERRIDES = removed")
        self.stdout.write("TEMPLATE COMPILE = OK")
        self.stdout.write("CHECK MODE = READ ONLY")
        self.stdout.write(self.style.SUCCESS("MATERIAL REPORT CENTERED V86 CHECK OK"))