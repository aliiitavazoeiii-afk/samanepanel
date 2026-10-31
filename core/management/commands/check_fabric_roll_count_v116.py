"""Read-only audit for color-wise unapplied coded fabric rolls and lifetime weights."""
from decimal import Decimal
from types import SimpleNamespace

from django.core.management.base import BaseCommand

from core import material_report_v92 as report
from core.models import MaterialReportBlock


class FakeRelated:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def all(self):
        return self.rows


def _synthetic_white_pink_test():
    """Pure Python objects, no persistence: finished goods != materials applied."""
    def sheet(color, code="", cut=0, weight="", output_applied=0,
              material_applied_for=None, brand="دارما"):
        consumption = (
            [SimpleNamespace(
                kind=report.v23.FABRIC,
                material_key=material_applied_for,
                quantity=Decimal("1"),
            )]
            if material_applied_for else []
        )
        return SimpleNamespace(
            brand=SimpleNamespace(name=brand),
            input_data={color: {
                "fabric_code": code, "cut": str(cut), "weight": str(weight),
            }},
            output_applications=FakeRelated(
                [SimpleNamespace(model_key=color, quantity=output_applied)]
                if output_applied else []
            ),
            stock_consumptions=FakeRelated(consumption),
        )

    data = [
        sheet("white", "W-A", cut=8, weight="10.5", output_applied=8),
        sheet("white", "W-B", cut=10, weight="7", output_applied=4,
              material_applied_for="white"),  # exclude even with pending output
        sheet("white", "W-C", weight="2.125"),
        sheet("white", "W-D", cut=2),
        sheet("white", "W-C", weight="1"),  # duplicate eligible code
        sheet("white", "", cut=3, weight="3"),  # no code: never a roll
        sheet("white", "W-E", weight="4", material_applied_for="white"),
        sheet("white", "W-F", weight="2", material_applied_for="pink"),
        # Applying another color within the same sheet does not apply white.
        sheet("white", "W-OTHER", weight="99", brand="Novani"),
        sheet("pink", "P-A", cut=7, weight="4", output_applied=7),
        sheet("pink", "P-B", cut=5, weight="3.5", material_applied_for="pink"),
        sheet("pink", "P-C", cut=2, weight="1.25"),
        sheet("pink", "P-D"),
        sheet("pink", "P-C", weight="1"),  # duplicate eligible code
        sheet("pink", "", weight="2"),
    ]
    rows = {row["key"]: row for row in report._summarize_open_base_colors(data)}
    white, pink = rows["white"], rows["pink"]
    if (white["roll_count"], white["rolls_without_code"],
            white["total_weight_display"]) != (4, 1, "29.625"):
        raise RuntimeError(f"White eligible rolls/lifetime weight drift: {white!r}")
    if (white["expected"], white["delivered"], white["pending"]) != (15, 4, 11):
        raise RuntimeError(f"White sewing-delivery metrics changed: {white!r}")
    if (pink["roll_count"], pink["rolls_without_code"],
            pink["total_weight_display"]) != (3, 1, "11.75"):
        raise RuntimeError(f"Pink eligible rolls/lifetime weight drift: {pink!r}")
    if (pink["expected"], pink["delivered"], pink["pending"]) != (7, 0, 7):
        # P-A completed; P-B cut=5 open; P-C cut=2 open
        raise RuntimeError(f"Pink sewing-delivery metrics changed: {pink!r}")
    if any(rows[key]["roll_count"] for key in ("black", "navy", "cream")):
        raise RuntimeError("Fabric code leaked into unrelated colors")


class Command(BaseCommand):
    help = "Audit unapplied coded Darma fabric rolls and total delivered weight per color."

    def handle(self, *args, **kwargs):
        _synthetic_white_pink_test()
        self.stdout.write("SYNTHETIC WHITE/PINK = UNAPPLIED CODES + ALL-TIME WEIGHTS PASS")

        blocks = list(
            MaterialReportBlock.objects.select_related("brand")
            .prefetch_related("output_applications", "stock_consumptions").all()
        )
        for row in report._summarize_open_base_colors(blocks):
            eligible = {}
            consumed = {}
            missing_code = []
            weight_sum = Decimal("0")
            for block in blocks:
                if block.brand.name != "دارما":
                    continue
                values = ((block.input_data or {}).get(row["key"]) or {})
                code = str(values.get("fabric_code") or "").strip()
                cut = max(0, report.v23.v20._int(values.get("cut")))
                weight = max(report._decimal(values.get("weight")), Decimal("0"))
                weight_sum += weight
                applied = any(
                    c.kind == report.v23.FABRIC
                    and c.material_key == row["key"]
                    and report._decimal(c.quantity) > 0
                    for c in block.stock_consumptions.all()
                )
                if applied:
                    if code:
                        consumed.setdefault(code, []).append(block.pk)
                    continue
                if code:
                    eligible.setdefault(code, []).append(block.pk)
                elif cut > 0 or weight > 0:
                    missing_code.append(block.pk)

            if row["roll_count"] != len(eligible):
                raise RuntimeError(f"Incorrect unapplied code count: {row['key']}")
            if row["rolls_without_code"] != len(missing_code):
                raise RuntimeError(f"Incorrect missing code count: {row['key']}")
            if row["total_weight"] != weight_sum:
                raise RuntimeError(f"Incorrect lifetime delivered weight: {row['key']}")
            self.stdout.write(
                f"{row['label']} | unapplied_coded_rolls={len(eligible)} "
                f"| total_delivered_weight_kg={row['total_weight_display']} "
                f"| unapplied_uncoded_sheets={len(missing_code)} "
                f"| open_cut={row['expected']} "
                f"| applied_output={row['delivered']} "
                f"| pending_output={row['pending']}"
            )
            self.stdout.write("  eligible_codes="+repr(eligible))
            self.stdout.write("  applied_excluded_codes="+repr(consumed))
            self.stdout.write("  uncoded_sheet_ids="+repr(missing_code))
        self.stdout.write(self.style.SUCCESS(
            "SUCCESS: UNAPPLIED FABRIC ROLLS + COLOR WEIGHT AUDIT V118 PASSED"
        ))
