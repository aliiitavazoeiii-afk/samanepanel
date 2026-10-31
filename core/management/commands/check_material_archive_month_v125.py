"""V125 read-only regressions: selected Jalali archive months and unfilled deliveries."""
from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.management.base import BaseCommand

from core import material_report_v92 as report
from core.management.commands.check_material_net_v122 import sheet
from core.models import MaterialReportBlock


def synthetic_check():
    november = report._jalali_month_context(date(2026, 10, 25))
    october = report._jalali_month_context(date(2026, 10, 10))
    assert november["key"] == "1405/08", november
    assert october["key"] == "1405/07", october

    blocks_metadata = [
        {"month_key": "1405/06"}, {"month_key": "1405/07"},
        {"month_key": "1405/08"}, {"month_key": "1405/09"},
    ]
    selected = report._selected_month_context("1405/07", november, blocks_metadata)
    assert selected["key"] == "1405/07"
    for value in ("1405/09", "1405/05", "not-a-month", "../../", ""):
        assert report._selected_month_context(value, november, blocks_metadata)["key"] == "1405/08"

    # Two rolls: +248 and -210 must net to +38 for pink.
    # One is ALREADY fabric-applied but delivery remains pending.
    pink_applied = sheet(
        1, date(2026, 10, 10),
        color="pink", cut=750, delivered=540, applied=540,
        raw_applied=True,
    )
    pink_unapplied = sheet(
        2, date(2026, 10, 12),
        color="pink", cut=750, delivered=998, applied=0,
        raw_applied=False,
    )
    black_applied_pending = sheet(
        3, date(2026, 10, 13),
        color="black", cut=600, delivered=300, applied=300,
        raw_applied=True,
    )
    previous_month = sheet(
        4, date(2026, 9, 20),
        color="white", cut=700, delivered=0, applied=0,
        raw_applied=False,
    )
    current = sheet(
        5, date(2026, 10, 25),
        color="white", cut=90, delivered=0, applied=0,
        raw_applied=False,
    )
    all_blocks = [pink_applied, pink_unapplied, black_applied_pending,
                  previous_month, current]

    current_month_blocks = [
        block for block in all_blocks if november["start"] <= block.date < november["next"]
    ]
    summary_now, _, _ = report._current_unapplied_material_metrics(current_month_blocks)
    assert (summary_now["minimum_delivery"], summary_now["pending"]) == (90, 90)

    october_blocks = [
        block for block in all_blocks if selected["start"] <= block.date < selected["next"]
    ]
    assert [block.pk for block in october_blocks] == [1, 2, 3]
    summary_old, by_color, _ = report._current_unapplied_material_metrics(october_blocks)
    # Existing top KPIs continue ONLY showing material-unapplied rows.
    assert summary_old["minimum_delivery"] == 750
    assert summary_old["delivered"] == 998
    assert by_color["pink"]["surplus"] == 248

    # A second, separate full archive breakdown MUST retain output still owed
    # even when raw fabric was applied. No cross-color surplus cancellation.
    full = report._all_month_color_delivery_metrics(october_blocks)
    expected = (2100, 1838, 840, 300, 38)
    actual = (full["expected"], full["delivered"], full["applied"],
              full["pending"], full["surplus"])
    if actual != expected:
        raise RuntimeError(f"Archive full delivery reconciliation drift: {actual} vs {expected}")
    by_key = {row["key"]: row for row in full["rows"]}
    assert (by_key["pink"]["expected"], by_key["pink"]["delivered"],
            by_key["pink"]["pending"], by_key["pink"]["surplus"]) == (1500, 1538, 0, 38)
    assert (by_key["black"]["expected"], by_key["black"]["delivered"],
            by_key["black"]["pending"], by_key["black"]["surplus"]) == (600, 300, 300, 0)

    # Configured non-base colors with registered cuts must also show in the
    # historic outstanding table. No legacy base-color-only truncation.
    dynamic_color = sheet(
        6, date(2026, 10, 12),
        color="color:99", cut=75, delivered=25, applied=25,
        raw_applied=True,
    )
    with patch.object(report.v23, "_material_label", return_value="مدل اختصاصی"):
        dynamic = report._all_month_color_delivery_metrics(
            october_blocks + [dynamic_color]
        )
    custom = [row for row in dynamic["rows"] if row["key"] == "color:99"]
    assert len(custom) == 1 and custom[0]["pending"] == 50
    assert dynamic["pending"] == 350
    return november, selected


class Command(BaseCommand):
    help = "Verify that opening an archived Jalali month restores its live KPIs and ALL undelivered color balances without affecting the current month."

    def handle(self, *args, **kwargs):
        current, archived = synthetic_check()
        root = Path(settings.BASE_DIR)
        source = (root / "templates/core/material_report_v92.html").read_text(encoding="utf-8")
        report_source = (root / "core/material_report_v92.py").read_text(encoding="utf-8")
        for marker in (
            'data-selected-month="{{ material_selected_month_key }}"',
            "url.searchParams.set('report_month', key)",
            "archive.open = true",
            "material-month-archive",
            "material-month-full-delivery",
            "material_archive_deliveries.rows",
            "بازگشت به {{ material_current_month_label }}",
        ):
            if marker not in source:
                raise RuntimeError(f"Archive-month UI regression: missing {marker}")
        if "_selected_month_context(" not in report_source:
            raise RuntimeError("Backend period selector missing")
        if "if month[\"start\"] <= obj.date < month[\"next\"]" not in report_source:
            raise RuntimeError("Month-only report scope was removed")

        month_rows = list(
            MaterialReportBlock.objects.filter(
                date__gte=archived["start"], date__lt=archived["next"]
            ).select_related("brand").prefetch_related(
                "output_applications", "stock_consumptions"
            )
        )
        monthly, _, _ = report._current_unapplied_material_metrics(month_rows)
        full = report._all_month_color_delivery_metrics(month_rows)
        self.stdout.write(
            f"ARCHIVE={archived['label']} SHEETS={len(month_rows)} "
            f"UNAPPLIED_CUT={monthly['minimum_delivery']} "
            f"ALL_CUT={full['expected']} ALL_REGISTERED={full['delivered']} "
            f"OUTSTANDING={full['pending']} SURPLUS={full['surplus']}"
        )
        for row in full["rows"]:
            self.stdout.write(
                f"  COLOR={row['label']} CUT={row['expected']} "
                f"RECEIVED={row['delivered']} PENDING={row['pending']} "
                f"APPLIED_STOCK={row['applied']}"
            )
        self.stdout.write(
            f"CURRENT={current['label']} ARCHIVE_REPORT_CHANGES_DB=NEVER"
        )
        self.stdout.write(self.style.SUCCESS(
            "SUCCESS: V125 JALALI ARCHIVE MONTH MATERIAL REPORT PASSED"
        ))
