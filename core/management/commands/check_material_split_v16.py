from types import SimpleNamespace

from django.core.management.base import BaseCommand, CommandError
from django.urls import resolve, reverse

from core.material_receipt_sync import desired_consumption
from core.models import MaterialReportOutputApplied


class Command(BaseCommand):
    help = "Verify split material-consumption and cumulative production-output flow v16."

    def handle(self, *args, **options):
        errors = []
        expected = {
            "material_report": "core.material_report_v16",
            "material_block_save": "core.material_report_v16",
            "material_block_apply": "core.material_report_v16",
            "material_block_apply_output": "core.material_report_v16",
            "material_block_unapply": "core.material_report_v16",
        }
        for name, module in expected.items():
            args = [1] if name.startswith("material_block_") else []
            try:
                actual = resolve(reverse(name, args=args)).func.__module__
                if actual != module:
                    errors.append(f"{name}: {actual} != {module}")
                else:
                    self.stdout.write(f"route OK: {name} -> {actual}")
            except Exception as exc:
                errors.append(f"route {name}: {exc}")

        # Material consumption must be independent from any finished receipt.
        fake = SimpleNamespace(
            input_data={
                "black": {
                    "weight": "10",
                    "elastic16": "2",
                    "elastic25": "3",
                    "remain16": "0.5",
                    "remain25": "1",
                }
            },
            output_data={},
        )
        desired = desired_consumption(fake)
        if not desired:
            errors.append("desired_consumption still depends on finished output")
        if str(desired.get(("fabric", "black", ""), "")) != "10":
            errors.append(f"fabric desired consumption wrong: {desired}")
        if str(desired.get(("elastic", "black", "16"), "")) != "1.5":
            errors.append(f"elastic16 desired consumption wrong: {desired}")
        if str(desired.get(("elastic", "black", "25"), "")) != "2":
            errors.append(f"elastic25 desired consumption wrong: {desired}")

        # Model/table access proves migration/model wiring after migrate.
        try:
            MaterialReportOutputApplied.objects.count()
            self.stdout.write("MaterialReportOutputApplied model OK")
        except Exception as exc:
            errors.append(f"MaterialReportOutputApplied model: {exc}")

        if errors:
            for error in errors:
                self.stderr.write(self.style.ERROR(error))
            raise CommandError("MATERIAL SPLIT V16 FAILED")

        self.stdout.write(self.style.SUCCESS("MATERIAL SPLIT V16 OK"))
