"""Read-only regression for compact V110 material-sheet summary box grid."""
from hashlib import sha256
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.template.loader import get_template

from core import material_report_v92
from core.models import (
    AccountEntry,
    AppSetting,
    BusinessPayment,
    DigikalaSettlement,
    ExcelManualRow,
    ExcelManualSetting,
    InventoryMovement,
    MaterialReportBlock,
    MaterialReportConsumption,
    MaterialReportOutputApplied,
    RawMaterialStock,
    SaleLine,
    SaleSnapshot,
    StockBalance,
)


def _digest(model):
    fields = [field.attname for field in model._meta.concrete_fields]
    h = sha256()
    for row in model.objects.order_by(model._meta.pk.attname).values_list(*fields):
        h.update(repr(tuple(row)).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def _state():
    return {
        "raw": _digest(RawMaterialStock),
        "blocks": _digest(MaterialReportBlock),
        "consumption": _digest(MaterialReportConsumption),
        "output": _digest(MaterialReportOutputApplied),
        "stock": _digest(StockBalance),
        "movement": _digest(InventoryMovement),
        "sales": _digest(SaleLine),
        "snapshots": _digest(SaleSnapshot),
        "accounts": _digest(AccountEntry),
        "app_settings": _digest(AppSetting),
        "manual_settings": _digest(ExcelManualSetting),
        "manual_rows": _digest(ExcelManualRow),
        "payments": _digest(BusinessPayment),
        "receipts": _digest(DigikalaSettlement),
    }


class Command(BaseCommand):
    help = "Read-only V110 compact material summary regression."

    def handle(self, *args, **kwargs):
        before = _state()

        # Compile both material templates.
        get_template("core/material_report_v36.html")
        get_template("core/material_report_v92.html")

        source = (
            Path(settings.BASE_DIR) / "templates/core/material_report_v36.html"
        ).read_text(encoding="utf-8")

        required = (
            'data-summary-box-grid="v110"',
            "grid-template-columns:minmax(120px,1fr) minmax(220px,1.65fr) minmax(170px,1.25fr) minmax(150px,1fr) minmax(170px,1.1fr)",
            "summary-brand-box",
            "summary-models-box",
            "summary-codes-box",
            "summary-material-box",
            "summary-output-box",
            "summary-sub-line",
            "min-height:34px",
            "padding:5px 9px",
            "font-size:.76rem",
        )
        for marker in required:
            if marker not in source:
                raise RuntimeError(f"V110 summary-grid marker missing: {marker}")

        forbidden = (
            ".summary-pills{display:grid;grid-template-columns:1fr;justify-items:start",
            "font-size:.82rem;line-height:1.35",
        )
        for marker in forbidden:
            if marker in source:
                raise RuntimeError(f"V109 tall vertical summary returned: {marker}")

        # Match exact HTML class attributes, not a class name appearing in
        # CSS selectors. Material status has two mutually exclusive branches;
        # each rendered sheet still receives exactly one of those two.
        expected_html_counts = {
            'class="apply-state brand-pill summary-brand-box"': 1,
            'class="apply-state summary-models-box"': 1,
            'class="apply-state summary-codes-box"': 1,
            'class="apply-state applied summary-material-box"': 1,
            'class="apply-state pending summary-material-box"': 1,
            'class="apply-state applied summary-output-box"': 1,
        }
        for html_marker, expected_count in expected_html_counts.items():
            actual_count = source.count(html_marker)
            if actual_count != expected_count:
                raise RuntimeError(
                    f"Expected {expected_count} HTML marker {html_marker}, "
                    f"got {actual_count}"
                )

        # Pending increase/reduction must stay INSIDE output box rather than
        # create extra summary grid cells that increase collapsed-card height.
        output_start = source.index('class="apply-state applied summary-output-box"')
        output_end = source.index("</span>\n      </div>", output_start)
        output_chunk = source[output_start:output_end]
        for marker in ("افزایش منتظر", "کاهش منتظر", "summary-sub-line"):
            if marker not in output_chunk:
                raise RuntimeError(
                    f"Pending delivery status escaped the compact output box: {marker}"
                )

        # V118: only unconsumed, nonempty fabric codes for the SAME color
        # are counted as rolls. Weight remains lifetime-entered, regardless
        # of fabric consumption. The sewing-output stats are unchanged.
        objects = list(
            MaterialReportBlock.objects.select_related("brand")
            .prefetch_related("output_applications", "stock_consumptions")
            .all()
        )
        rows = material_report_v92._summarize_open_base_colors(objects)
        expected_keys = list(material_report_v92.v23.BASE_KEYS)
        if [row["key"] for row in rows] != expected_keys:
            raise RuntimeError("Base-color coverage/order drift under V118")

        for row in rows:
            codes = set()
            missing_codes = 0
            total_weight = material_report_v92.Decimal("0")
            for block in objects:
                if getattr(block.brand, "name", "") != "دارما":
                    continue
                values = ((block.input_data or {}).get(row["key"]) or {})
                code = str(values.get("fabric_code") or "").strip()
                cut = max(0, material_report_v92.v23.v20._int(values.get("cut")))
                weight = max(
                    material_report_v92._decimal(values.get("weight")),
                    material_report_v92.Decimal("0"),
                )
                total_weight += weight
                applied = any(
                    used.kind == material_report_v92.v23.FABRIC
                    and used.material_key == row["key"]
                    and material_report_v92._decimal(used.quantity) > 0
                    for used in block.stock_consumptions.all()
                )
                if applied:
                    continue
                if code:
                    codes.add(code)
                elif weight > 0 or cut > 0:
                    missing_codes += 1
            if row["roll_count"] != len(codes):
                raise RuntimeError("V118 distinct UNAPPLIED fabric-code count drift")
            if row["rolls_without_code"] != missing_codes:
                raise RuntimeError("V118 uncoded unapplied sheet diagnostic drift")
            if row["total_weight"] != total_weight:
                raise RuntimeError("V118 all-time color delivery weight drift")
            if row["total_weight_display"] != material_report_v92._format_weight(total_weight):
                raise RuntimeError("V118 displayed color weight drift")

        v92_source = (
            Path(settings.BASE_DIR) / "templates/core/material_report_v92.html"
        ).read_text(encoding="utf-8")
        if v92_source.count('data-base-color="{{ item.key }}"') != 1:
            raise RuntimeError("Base-color card template marker drifted")
        for marker in ("طاقه اعمال‌نشده", "item.roll_count", "وزن پارچه اعمال‌نشده", "item.total_weight_display", "باید تحویل شود", "تحویل ثبت‌شده", "مانده خالص"):
            if marker not in v92_source:
                raise RuntimeError(f"Base-color card marker missing: {marker}")

        # Existing V106 three-delivery UI is still present.
        if "delivery-split" not in source or "part.name" not in source:
            raise RuntimeError("Three-delivery UI disappeared from material report")

        after = _state()
        if before != after:
            raise RuntimeError("V110 regression changed persistent business state")

        self.stdout.write("MATERIAL SUMMARY DESKTOP GRID = 5 BOXES")
        self.stdout.write("COLLAPSED HEIGHT = COMPACT HORIZONTAL LAYOUT")
        self.stdout.write("MODEL / FABRIC / MATERIAL / DELIVERY = SEPARATE BOXES")
        self.stdout.write("PENDING OUTPUT STATUS = KEPT INSIDE DELIVERY BOX")
        self.stdout.write("V109 COLOR ROLL CARDS + ROLL COUNTS = VERIFIED")
        self.stdout.write("THREE DELIVERY INPUTS = PRESERVED")
        self.stdout.write("NO BUSINESS STATE WRITE = OK")
        self.stdout.write(self.style.SUCCESS(
            "SUCCESS: COMPACT MATERIAL SUMMARY BOX GRID V110 CHECK PASSED"
        ))
