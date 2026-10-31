"""Read-only production regression for V88 pricing monitor."""
from datetime import date, timedelta
from io import BytesIO
from types import SimpleNamespace
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import RequestFactory, override_settings
from django.template.loader import get_template
from django.urls import resolve

from core.dateutils import format_jalali
from core.models import AppSetting, SaleLine
from core.pricing_monitor_v88 import (
    _canonical_code,
    _previous_jalali_same_day,
    pricing_monitor,
    pricing_monitor_data,
    pricing_monitor_xlsx,
)


class Command(BaseCommand):
    help = "Read-only: validate V88 Darma pricing comparison, historical date filter and XLSX."

    def handle(self, *args, **kwargs):
        before_sales = SaleLine.objects.count()
        before_settings = AppSetting.objects.count()

        if _canonical_code("pack6") != "06" or _canonical_code("06") != "06":
            raise RuntimeError("pack6/06 canonical grouping regression")

        completed = date.today() - timedelta(days=1)
        previous = _previous_jalali_same_day(completed)
        data = pricing_monitor_data(completed)
        if data["is_partial_day"]:
            raise RuntimeError("A completed historical date was marked partial")
        if data["previous_day"] != previous:
            raise RuntimeError("Previous Jalali same-day mapping mismatch")

        get_template("core/pricing_monitor_v88.html")
        get_template("core/_pricing_monitor_dashboard_v88.html")
        if resolve("/pricing-monitor/").func is not pricing_monitor:
            raise RuntimeError("pricing-monitor route is not active")
        if resolve("/pricing-monitor/export/xlsx/").func is not pricing_monitor_xlsx:
            raise RuntimeError("pricing-monitor XLSX route is not active")

        user = SimpleNamespace(is_authenticated=True)
        factory = RequestFactory()
        historical_j = format_jalali(completed)

        request = factory.get("/pricing-monitor/", {"date": historical_j})
        request.user = user
        # docker compose run --entrypoint python intentionally skips entrypoint.sh,
        # which normally runs collectstatic before starting Gunicorn. Rendering
        # the test page must not require a production staticfiles manifest.
        # Override the test storage only; production still uses WhiteNoise's
        # CompressedManifestStaticFilesStorage after its normal collectstatic.
        with override_settings(STORAGES={
            **settings.STORAGES,
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
            },
        }):
            response = pricing_monitor(request)
        if response.status_code != 200:
            raise RuntimeError(f"Pricing monitor HTTP status {response.status_code}")

        request = factory.get("/pricing-monitor/export/xlsx/", {"date": historical_j})
        request.user = user
        response = pricing_monitor_xlsx(request)
        if response.status_code != 200:
            raise RuntimeError(f"Pricing XLSX HTTP status {response.status_code}")
        if not response.content.startswith(b"PK"):
            raise RuntimeError("Pricing export is not an XLSX archive")

        with ZipFile(BytesIO(response.content)) as archive:
            if archive.testzip() is not None:
                raise RuntimeError("Pricing XLSX ZIP integrity failed")
            main = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            names = [node.attrib["name"] for node in workbook.find(f"{main}sheets")]
            required = {
                "خلاصه مدیریتی", "مقایسه روز مشابه", "مقایسه تجمعی",
                "تاریخچه قیمت", "ارزیابی ۱۰ روزه",
            }
            missing = required - set(names)
            if missing:
                raise RuntimeError(f"Missing V88 XLSX sheets: {sorted(missing)}")

        if SaleLine.objects.count() != before_sales or AppSetting.objects.count() != before_settings:
            raise RuntimeError("V88 read-only check changed database row counts")

        self.stdout.write(f"DATE = {historical_j}")
        self.stdout.write(f"PREVIOUS SAME JALALI DAY = {format_jalali(previous)}")
        self.stdout.write(f"TOP PREVIOUS-MONTH KEYS = {len(data['top_keys'])}")
        self.stdout.write(f"DAY COMPARISON ROWS = {len(data['day_rows'])}")
        self.stdout.write(f"MTD COMPARISON ROWS = {len(data['mtd_rows'])}")
        self.stdout.write("PACK6 / 06 CANONICAL GROUP = OK")
        self.stdout.write("HISTORICAL DATE FILTER = OK")
        self.stdout.write("TEMPLATES / ROUTES / RENDER (TEST STATIC STORAGE) = OK")
        self.stdout.write("XLSX ZIP / SHEETS = OK")
        self.stdout.write("NO ROW-COUNT WRITE = OK")
        self.stdout.write(self.style.SUCCESS("SUCCESS: PRICING MONITOR V88 CHECK PASSED"))
