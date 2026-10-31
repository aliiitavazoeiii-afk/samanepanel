"""Read-only regression for V96 inventory/material center and fabric aggregation."""
from decimal import Decimal
from hashlib import sha256
from inspect import getsource
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import RequestFactory, override_settings
from django.template.loader import get_template
from django.urls import resolve

from core import inventory_center_v96, inventory_v20, report_v10
from core.brand_colors import norm
from core.models import (
    AppSetting,
    ExcelManualRow,
    InventoryMovement,
    MaterialReportConsumption,
    RawMaterialStock,
    StockBalance,
)
from core.report_v5 import _raw_material_context


def _digest_model(model):
    fields = [field.attname for field in model._meta.concrete_fields]
    digest = sha256()
    for row in model.objects.order_by(model._meta.pk.attname).values_list(*fields):
        digest.update(repr(tuple(row)).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _state():
    return {
        "raw": _digest_model(RawMaterialStock),
        "material_consumption": _digest_model(MaterialReportConsumption),
        "stock": _digest_model(StockBalance),
        "movements": _digest_model(InventoryMovement),
        "settings": _digest_model(AppSetting),
        "manual_rows": _digest_model(ExcelManualRow),
    }


class Command(BaseCommand):
    help = "Read-only: validate V96 inventory hub, raw-material move, aggregation and no-write behavior."

    def handle(self, *args, **kwargs):
        before = _state()

        # Routes: existing /inventory/ becomes the center; old stock screen is kept.
        if resolve("/inventory/").func is not inventory_center_v96.inventory_home:
            raise RuntimeError("/inventory/ is not V96 inventory center")
        if resolve("/inventory/stock/").func is not inventory_v20.inventory:
            raise RuntimeError("/inventory/stock/ does not preserve V20 finished inventory")
        if resolve("/inventory/materials/").func is not inventory_center_v96.raw_materials:
            raise RuntimeError("/inventory/materials/ is not V96 raw-material view")
        if resolve("/inventory/materials/action/").func is not inventory_center_v96.raw_material_action:
            raise RuntimeError("V96 raw-material action route missing")
        if resolve("/report/").func is not report_v10.report:
            raise RuntimeError("Comprehensive report route changed unexpectedly")

        for template_name in (
            "core/inventory_center_v96.html",
            "core/raw_material_inventory_v96.html",
            "core/report_excel_v96.html",
            "core/inventory_v19.html",
        ):
            get_template(template_name)

        # Pure canonicalization check: legacy blank-key «سفید» must resolve to
        # the same visible identity as current key=white.
        legacy = SimpleNamespace(material_key="", title="سفید", id=1)
        current = SimpleNamespace(material_key="white", title="سفید", id=2)
        key_map = {norm("سفید"): "white"}
        if inventory_center_v96._canonical_material_key(legacy, key_map) != "white":
            raise RuntimeError("Legacy white fabric row does not canonicalize to white")
        if inventory_center_v96._canonical_material_key(current, key_map) != "white":
            raise RuntimeError("Current white fabric key changed")

        # Pure aggregate math check: no storage mutation, quantity/value preserved.
        rows = [
            SimpleNamespace(
                id=1, material_key="white", title="سفید", quantity=Decimal("100"),
                unit_price=100_000, total_value=10_000_000, unit="کیلو", note="old",
            ),
            SimpleNamespace(
                id=2, material_key="white", title="سفید", quantity=Decimal("252"),
                unit_price=120_000, total_value=30_240_000, unit="کیلو", note="new",
            ),
        ]
        groups = inventory_center_v96._fabric_location_groups(rows)
        if len(groups) != 1:
            raise RuntimeError("Same-color fabric lots are not shown as one V96 aggregate row")
        group = groups[0]
        if group["quantity"] != Decimal("352") or group["total_value"] != 40_240_000:
            raise RuntimeError(f"Fabric aggregate totals wrong: {group}")
        if group["row_count"] != 2:
            raise RuntimeError("Fabric internal lot provenance disappeared")

        # Validate actual production data aggregation is value/quantity neutral.
        raw = _raw_material_context()
        for rows_key in ("fabric_warehouse", "fabric_tailor", "fabric_depot"):
            source_rows = raw[rows_key]
            actual_groups = inventory_center_v96._fabric_location_groups(source_rows)
            source_qty = sum((Decimal(row.quantity or 0) for row in source_rows), Decimal("0"))
            grouped_qty = sum((Decimal(row["quantity"] or 0) for row in actual_groups), Decimal("0"))
            source_value = sum(int(row.total_value or 0) for row in source_rows)
            grouped_value = sum(int(row["total_value"] or 0) for row in actual_groups)
            if source_qty != grouped_qty or source_value != grouped_value:
                raise RuntimeError(f"V96 grouping changed quantity/value for {rows_key}")

        # Report still calculates inventory/raw material capital exactly as before;
        # only its detailed UI is moved away from the report page.
        report_source = getsource(report_v10.report)
        for marker in (
            'raw = _raw_material_context()',
            'inventory_total = finished_inventory_total + raw["materials_total"]',
            'current_capital_total = accounts_total + inventory_total + digikala_receivable - takvin_debt + assets_total',
            '"core/report_excel_v96.html"',
        ):
            if marker not in report_source:
                raise RuntimeError(f"Report capital/reference marker missing: {marker}")

        report_template = (
            Path(settings.BASE_DIR) / "templates/core/report_excel_v96.html"
        ).read_text(encoding="utf-8")
        if "موجودی و مواد اولیه" not in report_template or "section.remove()" not in report_template:
            raise RuntimeError("V96 report template does not remove inventory/raw-material detail domain")

        action_source = getsource(inventory_center_v96.raw_material_action)
        for marker in (
            "add_warehouse_stock",
            "transfer_fabric_to_tailor",
            "update_fabric_stock",
            "delete_fabric_stock",
            "transfer_elastic_to_tailor",
            "update_elastic_group",
            "delete_elastic_group",
        ):
            if marker not in action_source:
                raise RuntimeError(f"V96 material action lost legacy flow: {marker}")

        factory = RequestFactory()
        user = SimpleNamespace(is_authenticated=True)
        static_override = {
            **settings.STORAGES,
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }
        with override_settings(STORAGES=static_override):
            req = factory.get("/inventory/")
            req.user = user
            response = inventory_center_v96.inventory_home(req)
            if response.status_code != 200:
                raise RuntimeError(f"Inventory center render HTTP {response.status_code}")
            text = response.content.decode("utf-8", errors="replace")
            for marker in ("موجودی کالا", "مواد اولیه"):
                if marker not in text:
                    raise RuntimeError(f"Inventory center UI marker missing: {marker}")

            req = factory.get("/inventory/materials/")
            req.user = user
            response = inventory_center_v96.raw_materials(req)
            if response.status_code != 200:
                raise RuntimeError(f"Raw-material center render HTTP {response.status_code}")
            text = response.content.decode("utf-8", errors="replace")
            for marker in ("موجودی پارچه", "نزد خیاط", "دپو", "موجودی کش"):
                if marker not in text:
                    raise RuntimeError(f"Raw-material UI marker missing: {marker}")

            req = factory.get("/inventory/stock/")
            req.user = user
            response = inventory_v20.inventory(req)
            if response.status_code != 200:
                raise RuntimeError(f"Finished inventory render HTTP {response.status_code}")

        after = _state()
        if before != after:
            raise RuntimeError("V96 read-only regression changed inventory/material/account state")

        self.stdout.write("INVENTORY CENTER ROUTES = OK")
        self.stdout.write("FINISHED INVENTORY V20 PRESERVED = OK")
        self.stdout.write("RAW MATERIALS MOVED TO INVENTORY UI = OK")
        self.stdout.write("LEGACY/CURRENT FABRIC COLOR CANONICALIZATION = OK")
        self.stdout.write("SAME-COLOR FABRIC LOTS DISPLAY AS ONE ROW = OK")
        self.stdout.write("FABRIC QUANTITY/VALUE AGGREGATION = NEUTRAL")
        self.stdout.write("FABRIC LOT PROVENANCE = PRESERVED")
        self.stdout.write("REPORT CAPITAL FORMULA = UNCHANGED")
        self.stdout.write("MATERIAL FLOW FUNCTIONS = UNCHANGED/REUSED")
        self.stdout.write("NO RAW / STOCK / MOVEMENT / ACCOUNT WRITE = OK")
        self.stdout.write(self.style.SUCCESS("SUCCESS: INVENTORY + MATERIAL CENTER V96 CHECK PASSED"))
