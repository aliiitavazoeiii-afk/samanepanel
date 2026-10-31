"""Read-only regression for V94 global Jalali picker + Darma inventory adjustment default."""
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import RequestFactory, override_settings
from django.urls import resolve

from core import calendar_views, inventory_operations_v16
from core.models import AppSetting, InventoryMovement, ProductSize, SaleLine, StockBalance


def _digest_model(model):
    fields = [field.attname for field in model._meta.concrete_fields]
    digest = sha256()
    for row in model.objects.order_by(model._meta.pk.attname).values_list(*fields):
        digest.update(repr(tuple(row)).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _state():
    return {
        "stock": _digest_model(StockBalance),
        "movements": _digest_model(InventoryMovement),
        "settings": _digest_model(AppSetting),
        "product_sizes": _digest_model(ProductSize),
        "sale_lines": _digest_model(SaleLine),
    }


class Command(BaseCommand):
    help = "Read-only: validate V94 global date picker and Darma default without business writes."

    def handle(self, *args, **kwargs):
        before = _state()
        base_dir = Path(settings.BASE_DIR)
        global_js = (base_dir / "static/core/number_format.js").read_text(encoding="utf-8")
        picker_js = (base_dir / "static/core/jalali_picker.js").read_text(encoding="utf-8")
        base_html = (base_dir / "templates/base.html").read_text(encoding="utf-8")
        inventory_html = (base_dir / "templates/core/inventory_operations.html").read_text(encoding="utf-8")

        for marker in (
            "darma-global-jalali-picker-v94",
            "/static/core/jalali_picker.js?v=94",
            "defaultInventoryAdjustmentToDarma",
            "adjust-brand",
            "دارما",
            "dispatchEvent(new Event('change'",
        ):
            if marker not in global_js:
                raise RuntimeError(f"V94 global loader/default marker missing: {marker}")

        if "core/number_format.js" not in base_html:
            raise RuntimeError("V94 global loader host script is not loaded by base.html")

        # Match the literal JavaScript source. The previous regression accidentally
        # searched for backslash-escaped quote characters (name=\"date\"), while
        # the actual selector source correctly contains name="date".
        for marker in (
            "__darmaJalaliPickerLoaded",
            "jalali-date",
            'name="date"',
            'name="start"',
            'name="end"',
            'name="effective_from"',
            'name="receipt_from"',
            'name="receipt_to"',
            "MutationObserver",
            "input.readOnly=true",
            "/calendar/picker/",
            "DarmaJalaliPicker={attach,close}",
        ):
            if marker not in picker_js:
                raise RuntimeError(f"V94 Jalali picker coverage marker missing: {marker}")

        if 'id="adjust-brand"' not in inventory_html:
            raise RuntimeError("Inventory adjustment brand select marker missing")

        calendar_match = resolve("/calendar/picker/")
        if calendar_match.func is not calendar_views.jalali_picker:
            raise RuntimeError("Jalali picker endpoint route changed")
        inventory_match = resolve("/inventory/operations/")
        if inventory_match.func is not inventory_operations_v16.inventory_operations:
            raise RuntimeError("Inventory operations route changed")

        factory = RequestFactory()
        user = SimpleNamespace(is_authenticated=True)
        static_override = {
            **settings.STORAGES,
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }

        calendar_request = factory.get("/calendar/picker/")
        calendar_request.user = user
        calendar_response = calendar_views.jalali_picker(calendar_request)
        if calendar_response.status_code != 200:
            raise RuntimeError(f"Jalali picker endpoint HTTP {calendar_response.status_code}")

        inventory_request = factory.get("/inventory/operations/")
        inventory_request.user = user
        with override_settings(STORAGES=static_override):
            inventory_response = inventory_operations_v16.inventory_operations(inventory_request)
        if inventory_response.status_code != 200:
            raise RuntimeError(f"Inventory operations render HTTP {inventory_response.status_code}")
        rendered = inventory_response.content.decode("utf-8", errors="replace")
        if 'id="adjust-brand"' not in rendered or ">دارما</option>" not in rendered:
            raise RuntimeError("Rendered inventory adjustment UI does not expose Darma brand option")

        after = _state()
        if before != after:
            raise RuntimeError("V94 read-only checks changed stock/pricing/sales state")

        self.stdout.write("GLOBAL JALALI PICKER LOADER = OK")
        self.stdout.write("DATE SELECTOR COVERAGE = OK")
        self.stdout.write("DYNAMIC DATE INPUT OBSERVER = OK")
        self.stdout.write("JALALI PICKER ENDPOINT = OK")
        self.stdout.write("INVENTORY ADJUSTMENT UI DEFAULTS TO DARMA = OK")
        self.stdout.write("INVENTORY OPERATIONS ROUTE UNCHANGED = OK")
        self.stdout.write("NO STOCK / MOVEMENT / PRICE / SALE WRITE = OK")
        self.stdout.write(self.style.SUCCESS("SUCCESS: GLOBAL CALENDAR + DARMA DEFAULT V94 CHECK PASSED"))
