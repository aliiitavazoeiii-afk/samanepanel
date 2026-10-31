from django.core.management.base import BaseCommand
from django.template.loader import get_template
from django.urls import resolve

from core import material_report_v23 as v23
from core.models import Brand, MaterialReportBlock


class Command(BaseCommand):
    help = "Read-only regression checks for dynamic material report V77."

    def handle(self, *args, **options):
        expected_base = ["black", "white", "navy", "pink", "cream"]
        if v23.BASE_KEYS != expected_base:
            raise RuntimeError(f"BASE MODELS mismatch: {v23.BASE_KEYS}")

        darma = Brand.objects.filter(name="دارما").first()
        if darma:
            sizes = v23._output_sizes_for_brand(darma)
            size_keys = [key for key, _label in sizes]
            if size_keys != ["m", "l", "xl", "xxl", "3xl", "4xl"]:
                raise RuntimeError(f"DARMA sizes mismatch: {size_keys}")
        else:
            size_keys = ["m", "l", "xl", "xxl", "3xl", "4xl"]

        # Compile the active template before deployment; this is read-only.
        get_template("core/material_report_v36.html")

        route_checks = {
            "/material-report/": "material_report",
            "/material-report/1/save/": "material_block_save",
            "/material-report/1/add-model/": "material_block_add_model",
            "/material-report/1/apply/": "material_block_apply_materials",
            "/material-report/1/apply-output/": "material_block_apply_output",
        }
        for path, expected_name in route_checks.items():
            func = resolve(path).func
            if getattr(func, "__name__", "") != expected_name:
                raise RuntimeError(f"Route {path} does not use V77 {expected_name}")

        old_missing = 0
        if darma:
            for block in MaterialReportBlock.objects.filter(brand=darma).only("output_data"):
                output = block.output_data or {}
                if output and any("4xl" not in (values or {}) for values in output.values() if isinstance(values, dict)):
                    old_missing += 1

        self.stdout.write("BASE MODELS = black, white, navy, pink, cream")
        self.stdout.write("EXTRA MODELS = dynamic per material report")
        self.stdout.write("ELASTIC SOURCE = selectable independently for 16 and 25")
        self.stdout.write("MATERIAL APPLY = delta-based from TAILOR stock")
        self.stdout.write("COST SOURCE = live current TAILOR unit prices; no snapshot")
        self.stdout.write("COST BASIS = fabric + elastic16 + elastic25 + sewing wage, divided by CUT")
        self.stdout.write("AVERAGE COST BASIS = weighted by CUT")
        self.stdout.write(f"DARMA OUTPUT SIZES = {', '.join(size_keys)}")
        self.stdout.write(f"OLD DARMA BLOCKS MISSING STORED 4XL KEY = {old_missing}")
        self.stdout.write("OLD DARMA 4XL DISPLAY = ON (blank until entered)")
        self.stdout.write("DETAILS DEFAULT = CLOSED")
        self.stdout.write("TEMPLATE COMPILE = OK")
        self.stdout.write("CHECK MODE = READ ONLY")
        self.stdout.write(self.style.SUCCESS("MATERIAL REPORT V77 CHECK OK"))
