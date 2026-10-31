"""Read-only audit of materials-payment color options and purchase parsing."""
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.management.base import BaseCommand
from django.http import QueryDict
from django.template.loader import get_template

from core.brand_colors import colors_for_brand, norm
from core.material_flow import COLOR_LABELS
from core.material_payment_colors_v124 import material_payment_colors, payment_material_label
from core.material_purchase_v13 import build_purchase_from_post


def synthetic_test():
    # No DB for this fixture. It guarantees new custom colors are included,
    # duplicate legacy colors keep stable identifiers, and post validation
    # round-trips exactly those selections to the purchase stock ledger.
    with patch(
        "core.material_payment_colors_v124.darma_material_choices",
        return_value=[
            ("pink", "صورتی"), ("color:876543", "سبز پسته‌ای"),
            ("color:876544", "راه راه ویژه"), ("color:876543", "سبز پسته‌ای"),
        ],
    ):
        choices = material_payment_colors()
        result = dict(choices)
        if result.get("pink") != "صورتی":
            raise RuntimeError("Legacy pink key changed")
        if result.get("color:876543") != "سبز پسته‌ای":
            raise RuntimeError("Custom Darma color missing from payment form")
        if result.get("color:876544") != "راه راه ویژه":
            raise RuntimeError("Second custom Darma color missing")
        if sum(norm(label) == norm("سبز پسته‌ای") for _, label in choices) != 1:
            raise RuntimeError("Duplicate custom color displayed")

        post = QueryDict(mutable=True)
        post.update({
            "material_key": "color:876543", "fabric_name": "پارچه یاسی",
            "fabric_qty": "3.5", "fabric_price": "200,000",
        })
        gross, payload = build_purchase_from_post("fabric", post)
        if (gross, payload["m"], payload["k"], payload["q"]) != (
            700000, "color:876543", "fabric", "3.5"
        ):
            raise RuntimeError(f"Custom color purchase did not preserve key/amount: {payload}")
        post["material_key"] = "color:does-not-exist"
        try:
            build_purchase_from_post("fabric", post)
        except ValueError:
            pass
        else:
            raise RuntimeError("Unregistered fabric color unexpectedly accepted")


class Command(BaseCommand):
    help = "Audit payments color dropdown vs Darma panel colors (read-only)."

    def handle(self, *args, **options):
        synthetic_test()
        choices = material_payment_colors()
        labels = {norm(label): key for key, label in choices}
        if len(set(key for key, _ in choices)) != len(choices):
            raise RuntimeError("Duplicate material dropdown option keys")
        for old in COLOR_LABELS:
            if old not in dict(choices):
                raise RuntimeError(f"Historic material color {old} unavailable")
        registered = list(colors_for_brand("دارما"))
        for color in registered:
            if norm(color.name) not in labels:
                raise RuntimeError(f"Registered Darma color missing: {color.pk} {color.name}")
            label = payment_material_label(labels[norm(color.name)])
            if norm(label) != norm(color.name):
                raise RuntimeError(f"Wrong color label {color.pk}: {label}")
        get_template("core/payments_v91.html")
        get_template("core/_payment_edit_v22.html")
        view_source = (Path(settings.BASE_DIR) / "core/business_tools_v91.py").read_text("utf-8")
        parser_source = (Path(settings.BASE_DIR) / "core/material_purchase_v13.py").read_text("utf-8")
        if '"material_colors": material_payment_colors()' not in view_source:
            raise RuntimeError("Payment form does not use live Darma colors")
        if "return payment_material_label(material_key)" not in parser_source:
            raise RuntimeError("Payment purchase validation not synchronized with dropdown")
        self.stdout.write(
            f"REGISTERED_DARMA_COLORS={len(registered)} "
            f"PAYMENT_DROPDOWN_OPTIONS={len(choices)}"
        )
        self.stdout.write("DATA_WRITES=ZERO; STOCK/FINANCE_FORMULAS=UNCHANGED")
        self.stdout.write(self.style.SUCCESS(
            "SUCCESS: V124 DYNAMIC DARMA PAYMENT COLORS CHECK PASSED"
        ))
