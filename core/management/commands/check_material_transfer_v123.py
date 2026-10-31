"""Read-only V123 audit: current open material counts, prior archive, color routing and stock directions."""
from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.urls import reverse

from core import material_report_v92 as report
from core.management.commands.check_material_net_v122 import sheet
from core.models import MaterialReportBlock


def synthetic_check():
    today = date(2026, 10, 18)
    pending1 = sheet(1, today, cut=750, delivered=998, applied=900,
                     raw_applied=False)
    pending2 = sheet(2, today, cut=750, delivered=540, applied=333,
                     raw_applied=False)
    applied = sheet(3, today, cut=1500, delivered=1500, applied=1500,
                    raw_applied=True)
    summary, base, average = report._current_unapplied_material_metrics(
        [pending1, pending2, applied]
    )
    assert (summary["minimum_delivery"], summary["delivered"],
            summary["pending"], summary["surplus"]) == (1500, 1538, 0, 38)
    assert (base["pink"]["expected"], base["pink"]["delivered"],
            base["pink"]["pending"], base["pink"]["surplus"]) == (1500, 1538, 0, 38)
    assert average["average_cut"] == 750

    # An older-month sheet must NOT appear in the current month's dashboard,
    # whether or not its materials have been applied. Date scoping is in view.
    old = sheet(4, date(2026, 9, 1), cut=1000, delivered=0,
                raw_applied=False)
    month = report._jalali_month_context(today)
    current = [
        x for x in [pending1, pending2, applied, old]
        if month["start"] <= x.date < month["next"]
    ]
    assert [x.pk for x in current] == [1, 2, 3]
    monthly, _, _ = report._current_unapplied_material_metrics(current)
    assert monthly["minimum_delivery"] == 1500


class Command(BaseCommand):
    help = "Verify V123 read-only month/color scoping, application routes and transfer UI."

    def handle(self, *args, **kwargs):
        synthetic_check()
        root = Path(settings.BASE_DIR)
        summary = (root / "templates/core/material_report_v92.html").read_text(encoding="utf-8")
        material = (root / "templates/core/material_report_v36.html").read_text(encoding="utf-8")
        inventory = (root / "templates/core/inventory_operations.html").read_text(encoding="utf-8")
        for needle in ("material-month-archive", "keyToNumber(key) >= currentNumber"):
            if needle not in summary:
                raise RuntimeError(f"Archived months did not remain collapsed: {needle}")
        for forbidden in ("materialCarryoverIds", "بازمانده ماه قبل"):
            if forbidden in summary:
                raise RuntimeError(f"Prior month incorrectly carried into view: {forbidden}")
        for needle in ("material_color_key", "material_block_apply_color",
                       "اعمال فقط {{ model.label }}"):
            if needle not in material:
                raise RuntimeError(f"Per-color apply button missing: {needle}")
        for needle in ('name="direction"', 'value="warehouse_to_home"',
                       'value="home_to_warehouse"', 'id="stock-transfer-form"',
                       "new FormData(transferForm)", "stock_snapshot"):
            if needle not in inventory:
                raise RuntimeError(f"Bidirectional AJAX stock transfer missing: {needle}")
        if reverse("material_block_apply_color", args=(123,)) != "/material-report/123/apply-color/":
            raise RuntimeError("Wrong per-color material route")
        if reverse("inventory_transfer_direction_v123") != "/inventory/operations/transfer-direction/":
            raise RuntimeError("Wrong two-way inventory route")
        # Read existing production records only. Never mutate company data.
        month = report._jalali_month_context()
        blocks = list(MaterialReportBlock.objects.select_related("brand").prefetch_related(
            "stock_consumptions", "output_applications"
        ).filter(date__gte=month["start"], date__lt=month["next"]))
        summary_data, cards, _ = report._current_unapplied_material_metrics(blocks)
        self.stdout.write(
            f"CURRENT_MONTH={month['label']} RAW_UNAPPLIED_ROLLS={summary_data['roll_count']} "
            f"CUT={summary_data['minimum_delivery']} "
            f"REGISTERED_DELIVERY={summary_data['delivered']} "
            f"STOCK_APPLIED={summary_data['applied']} "
            f"PENDING_NET={summary_data['pending']} SURPLUS_NET={summary_data['surplus']}"
        )
        for color, data in cards.items():
            self.stdout.write(f"{color}: rolls={data['roll_count']} cut={data['expected']} "
                              f"received={data['delivered']} pending={data['pending']} surplus={data['surplus']}")
        self.stdout.write(self.style.SUCCESS(
            "SUCCESS: V123 CURRENT UNAPPLIED MATERIALS + COLOR APPLY / STOCK DIRECTION AUDIT PASSED"
        ))
