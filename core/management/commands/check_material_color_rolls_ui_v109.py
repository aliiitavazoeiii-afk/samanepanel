"""Read-only regression for V109 material color roll counts + vertical sheet summaries."""
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import RequestFactory, override_settings

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


def _request(path):
    req = RequestFactory().get(path)
    req.user = SimpleNamespace(is_authenticated=True)
    return req


class Command(BaseCommand):
    help = "Read-only V109 regression."

    def handle(self, *args, **kwargs):
        before = _state()

        objects = list(
            MaterialReportBlock.objects.select_related("brand")
            .prefetch_related("output_applications")
            .all()
        )
        rows = material_report_v92._summarize_open_base_colors(objects)
        expected_keys = list(material_report_v92.v23.BASE_KEYS)
        if [row["key"] for row in rows] != expected_keys:
            raise RuntimeError("V109 base-color coverage/order drift")

        for row in rows:
            codes = set()
            uncoded = 0
            expected = delivered = pending = 0
            for block in objects:
                if getattr(block.brand, "name", "") != "دارما":
                    continue
                values = ((block.input_data or {}).get(row["key"]) or {})
                cut = max(
                    0,
                    material_report_v92.v23.v20._int(values.get("cut")),
                )
                applied = sum(
                    max(0, int(item.quantity or 0))
                    for item in block.output_applications.all()
                    if item.model_key == row["key"]
                )
                if cut <= applied:
                    continue

                code = str(values.get("fabric_code") or "").strip()
                weight = max(
                    material_report_v92._decimal(values.get("weight")),
                    material_report_v92.Decimal("0"),
                )
                if code:
                    codes.add(code)
                elif weight > 0:
                    uncoded += 1

                expected += cut
                delivered += applied
                pending += cut - applied

            manual_rolls = len(codes) + uncoded
            if int(row["roll_count"]) != manual_rolls:
                raise RuntimeError(
                    f"Roll count mismatch {row['key']}: {row['roll_count']} != {manual_rolls}"
                )
            if (row["expected"], row["delivered"], row["pending"]) != (
                expected,
                delivered,
                pending,
            ):
                raise RuntimeError(f"Open-work quantity drift for {row['key']}")

        storage = {
            **settings.STORAGES,
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }
        with override_settings(STORAGES=storage):
            response = material_report_v92.material_report(_request("/material-report/"))
        if response.status_code != 200:
            raise RuntimeError(f"Material report HTTP {response.status_code}")
        html = response.content.decode("utf-8", errors="replace")

        if html.count('data-base-color=') != 5:
            raise RuntimeError("V109 must render exactly five base-color cards")
        if html.count("طاقه تحویلی") != 5:
            raise RuntimeError("Each base-color card must show delivered roll count")

        source = (
            Path(settings.BASE_DIR) / "templates/core/material_report_v36.html"
        ).read_text(encoding="utf-8")
        for marker in (
            ".summary-pills{display:grid;grid-template-columns:1fr",
            "font-size:.82rem",
            'class="material-summary-main"',
        ):
            if marker not in source:
                raise RuntimeError(f"Vertical/enlarged summary marker missing: {marker}")

        # Existing delivery/business operations remain untouched in V109.
        if "DELIVERY_PART_COUNT = 3" not in (
            Path(settings.BASE_DIR) / "core/material_report_v23.py"
        ).read_text(encoding="utf-8"):
            raise RuntimeError("V106 three-delivery contract disappeared")

        after = _state()
        if before != after:
            raise RuntimeError("V109 regression changed persistent business state")

        self.stdout.write("BASE COLOR CARDS = EXACTLY 5")
        self.stdout.write("PER-COLOR OPEN-WORK ROLL COUNT = VERIFIED")
        self.stdout.write("ROLL COUNT RULE = UNIQUE FABRIC CODE + POSITIVE-WEIGHT UNCODED ROLL")
        self.stdout.write("MATERIAL SHEET SUMMARY = VERTICAL")
        self.stdout.write("SUMMARY TEXT = ENLARGED WITHOUT BUSINESS-LOGIC CHANGE")
        self.stdout.write("THREE DELIVERY CONTRACT = PRESERVED")
        self.stdout.write("NO BUSINESS STATE WRITE = OK")
        self.stdout.write(self.style.SUCCESS(
            "SUCCESS: MATERIAL COLOR ROLLS + SUMMARY UI V109 CHECK PASSED"
        ))
