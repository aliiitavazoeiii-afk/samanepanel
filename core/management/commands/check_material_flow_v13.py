from django.core.management.base import BaseCommand, CommandError
from django.urls import resolve, reverse

from core.material_cost_v13 import calculate_color_cost
from core.material_purchase_v13 import build_purchase_from_post, parse_purchase_note


class Command(BaseCommand):
    help = "Verify explicit material apply, costing, and purchase-payment flow v13."

    def handle(self, *args, **options):
        errors = []

        expected_modules = {
            "material_block_save": "core.material_report_v13",
            "material_block_apply": "core.material_report_v13",
            "material_block_unapply": "core.material_report_v13",
            "payment_add": "core.business_tools_v13",
        }
        for name, module in expected_modules.items():
            args = [1] if "material_block" in name else []
            url = reverse(name, args=args)
            actual = resolve(url).func.__module__
            if actual != module:
                errors.append(f"{name} -> {actual}, expected {module}")

        # Pure parser/calculator checks; no database mutation.
        amount, data = build_purchase_from_post(
            "fabric",
            {"material_key": "black", "fabric_qty": "10", "fabric_price": "100000", "fabric_name": "F1"},
        )
        if amount != 1000000 or data.get("k") != "fabric":
            errors.append("fabric purchase calculation is wrong")

        amount, data = build_purchase_from_post(
            "elastic",
            {
                "material_key": "black",
                "elastic16_qty": "2",
                "elastic16_price": "100000",
                "elastic25_qty": "3",
                "elastic25_price": "200000",
            },
        )
        if amount != 800000 or data.get("k") != "elastic":
            errors.append("elastic purchase calculation is wrong")

        if parse_purchase_note("normal note") is not None:
            errors.append("normal payment note detected as material purchase")

        # With no stock rows the material prices are zero, but labor must still divide correctly.
        result = calculate_color_cost("black", {"cut": "12"}, 110000)
        if result["unit_cost"] != 9167:
            errors.append(f"cost calculator labor-only result {result['unit_cost']} != 9167")

        if errors:
            for error in errors:
                self.stderr.write(self.style.ERROR(error))
            raise CommandError("Material flow v13 preflight failed")

        self.stdout.write(self.style.SUCCESS("MATERIAL FLOW V13 OK"))
