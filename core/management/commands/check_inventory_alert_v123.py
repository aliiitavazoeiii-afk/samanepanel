"""Read-only regression: sparse, uniform warning levels for total and home inventory."""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from core.inventory_v20 import _home_alert_level, _total_alert_level, _inventory_alert_level


def synthetic_check():
    for qty, expected in (
        (-2, "orange"), (-1, "orange"), (0, "red"), (1, "orange"),
        (5, "orange"), (9, "orange"), (10, ""), (30, ""), (50, ""),
        (99, ""), (100, ""),
    ):
        for fn in (_home_alert_level, _total_alert_level, _inventory_alert_level):
            for exempt in (False, True):
                result = fn(qty, exempt=exempt)
                if result != expected:
                    raise AssertionError(
                        f"{fn.__name__}({qty}, exempt={exempt}): {result!r} expected {expected!r}"
                    )


class Command(BaseCommand):
    help = "Verify inventory total and home warning thresholds: 0 strong, 1..9 soft, 10+ normal."

    def handle(self, *args, **kwargs):
        synthetic_check()
        template = (Path(settings.BASE_DIR) / "templates/core/inventory_v19.html").read_text("utf-8")
        # Exact stock-cell palette sampled from the owner's reference screenshot.
        # Keep this check purely presentational, independent of quantities/valuation.
        for shade in (
            ".stock-alert-red-hot{background:#7f0c16!important",
            ".stock-alert-red{background:#3d1c28!important",
        ):
            if shade not in template:
                raise RuntimeError(f"Inventory screenshot red palette drift: {shade}")
        if template.count("stock-alert-red-hot") < 3:
            raise RuntimeError("Strong zero-only highlight missing from both inventory tables")
        required = [
            "{% if cell.home_alert == 'red' %}stock-alert-red-hot",
            "{% elif cell.home_alert == 'orange' %}stock-alert-red",
            "{% if cell.total_alert == 'red' %}stock-alert-red-hot",
            "{% elif cell.total_alert == 'orange' %}stock-alert-red",
        ]
        for marker in required:
            if marker not in template:
                raise RuntimeError(f"Inventory warning render drift: {marker}")
        self.stdout.write("WARNING COUNTS: 0=STRONG_RED; 1..9=SOFT_RED; >=10=NORMAL")
        self.stdout.write(self.style.SUCCESS("SUCCESS: V123 INVENTORY ALERT THRESHOLDS PASS"))
