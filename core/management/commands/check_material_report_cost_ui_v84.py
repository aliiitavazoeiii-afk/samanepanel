from inspect import getsource
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.management.base import BaseCommand
from django.template.loader import get_template
from django.urls import resolve, reverse

from core import material_cost_v23 as cost
from core import material_report_v23


class Command(BaseCommand):
    help = "Read-only regression check for V84 material-report costing; V86 owns current sizing/UI."

    def handle(self, *args, **options):
        # Template must still be the established V23/V77 material-report surface.
        get_template("core/material_report_v36.html")
        match = resolve(reverse("material_report"))
        if match.func is not material_report_v23.material_report:
            raise RuntimeError("material_report route is no longer V23")

        # Verify the exact requested unit-cost formula without touching the DB.
        values = {
            "weight": "10",
            "cut": "100",
            "elastic16": "2",
            "remain16": "0.5",
            "elastic25": "1",
            "remain25": "0",
            "elastic16_key": "white",
            "elastic25_key": "white",
        }

        def fake_elastic_price(_key, variant):
            return 100000 if str(variant) == "16" else 120000

        with patch.object(cost, "fabric_price", return_value=200000), patch.object(
            cost, "elastic_price", side_effect=fake_elastic_price
        ):
            result = cost.calculate_model_cost("white", values, 1000000)

        expected = 32700
        if result["unit_cost"] != expected:
            raise RuntimeError(
                f"V84 formula mismatch: expected={expected} actual={result['unit_cost']}"
            )
        if result["fabric_unit_cost"] != 20000:
            raise RuntimeError("fabric-per-piece formula mismatch")
        if result["labor_unit_cost"] != 10000:
            raise RuntimeError("labor-per-piece formula mismatch")
        if result["elastic_unit_cost"] != 2700:
            raise RuntimeError("elastic-per-piece formula mismatch")

        wrapped = getattr(cost.fabric_price, "__wrapped__", cost.fabric_price)
        fabric_source = getsource(wrapped)
        if "location=TAILOR" not in fabric_source or "location=WAREHOUSE" not in fabric_source:
            raise RuntimeError("fabric price no longer uses tailor -> warehouse fallback")

        js_path = Path(settings.BASE_DIR) / "static" / "core" / "material_report_v6.js"
        js = js_path.read_text(encoding="utf-8")
        for marker in (
            "fabricPerPiece",
            "laborPerPiece",
            "elasticPerPiece",
            "direction:rtl",
            "text-align:center",
        ):
            if marker not in js:
                raise RuntimeError(f"V84 cost/browser marker missing: {marker}")

        self.stdout.write("MATERIAL REPORT ROUTE = V23")
        self.stdout.write("FORMULA = fabric/cut + tailor-wage/cut + used-elastic/cut")
        self.stdout.write("FABRIC PRICE SOURCE = tailor, fallback warehouse")
        self.stdout.write("ELASTIC PRICE SOURCE = tailor")
        self.stdout.write("ELASTIC USED = delivered - remain")
        self.stdout.write("GRID ALIGNMENT = centered")
        self.stdout.write("MODEL COLUMN GROWTH = RTL / new models extend left")
        self.stdout.write("TEMPLATE COMPILE = OK")
        self.stdout.write("CHECK MODE = READ ONLY")
        self.stdout.write("CURRENT SIZE/UI CONTRACT = checked by V86 command")
        self.stdout.write(self.style.SUCCESS("MATERIAL REPORT COST V84 CHECK OK"))
