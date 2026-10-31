"""Read-only regression for V90 Darma-only daily color/size sales matrix."""
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import RequestFactory, override_settings
from django.template.loader import get_template

from core.daily_report_v8 import _build_color_size_matrix, daily_report
from core.models import SaleDay, SaleLine


class Command(BaseCommand):
    help = "Read-only: validate V90 Darma-only daily color-by-size sales matrix and report render."

    def handle(self, *args, **kwargs):
        before_days = SaleDay.objects.count()
        before_lines = SaleLine.objects.count()

        # Non-Darma sales are deliberately present and must have zero effect.
        synthetic = [
            {
                "brand_name": "دارما", "code": "pack6", "size_name": "M",
                "shorts": 3, "color_source": "allocation",
                "colors": [
                    {"name": "سرمه‌ای", "qty": 2, "replacement_qty": 1},
                    {"name": "سفید", "qty": 1, "replacement_qty": 0},
                ],
            },
            {
                "brand_name": "تکوین", "code": "15", "size_name": "M",
                "shorts": 40, "color_source": "allocation",
                "colors": [
                    {"name": "سرمه‌ای", "qty": 40, "replacement_qty": 0},
                ],
            },
            {
                "brand_name": "دارما", "code": "s5", "size_name": "L",
                "shorts": 1, "color_source": "allocation",
                "colors": [
                    {"name": "سرمه‌ای", "qty": 1, "replacement_qty": 0},
                ],
            },
            {
                "brand_name": "انبارش", "code": "D110", "size_name": "XL",
                "shorts": 20, "color_source": "allocation",
                "colors": [
                    {"name": "مشکی", "qty": 20, "replacement_qty": 0},
                ],
            },
        ]
        matrix = _build_color_size_matrix(synthetic)
        if matrix["sizes"] != ["M", "L"]:
            raise RuntimeError(f"Unexpected V90 Darma size columns: {matrix['sizes']}")
        if matrix["total"] != 4 or matrix["expected_shorts"] != 4 or matrix["has_mismatch"]:
            raise RuntimeError("V90 Darma-only matrix total mismatch on synthetic data")
        if not matrix["has_replacement"]:
            raise RuntimeError("V90 replacement marker was lost")

        navy = next((row for row in matrix["rows"] if row["color_name"] == "سرمه‌ای"), None)
        if navy is None:
            raise RuntimeError("V90 Darma navy row missing")
        values = {cell["name"]: cell["qty"] for cell in navy["size_values"]}
        if values.get("M") != 2 or values.get("L") != 1 or navy["total"] != 3:
            raise RuntimeError("V90 Darma color-by-size aggregation failed")
        if any(row["color_name"] == "مشکی" for row in matrix["rows"]):
            raise RuntimeError("V90 leaked Anbaresh/non-Darma colors into Darma matrix")

        preferred_order = [
            "مشکی", "سفید", "سرمه‌ای", "صورتی", "کرم", "طوسی",
            "راه راه", "راه راه طوسی", "برعکس مشکی", "برعکس سفید", "برعکس سرمه‌ای",
        ]
        scrambled = [
            "برعکس سرمه‌ای", "صورتی", "راه راه طوسی", "مشکی", "طوسی",
            "برعکس سفید", "کرم", "سرمه‌ای", "راه راه", "سفید", "برعکس مشکی",
        ]
        order_probe = _build_color_size_matrix([{
            "brand_name": "دارما",
            "code": "order-probe",
            "size_name": "M",
            "shorts": len(scrambled),
            "color_source": "allocation",
            "colors": [
                {"name": name, "qty": 1, "replacement_qty": 0}
                for name in scrambled
            ],
        }])
        actual_order = [row["color_name"] for row in order_probe["rows"]]
        if actual_order != preferred_order:
            raise RuntimeError(f"V90 Darma color order mismatch: {actual_order}")

        alias_probe = _build_color_size_matrix([{
            "brand_name": "دارما",
            "code": "alias-probe",
            "size_name": "M",
            "shorts": 4,
            "color_source": "allocation",
            "colors": [
                {"name": "سرمه ای", "qty": 1, "replacement_qty": 0},
                {"name": "توسی", "qty": 1, "replacement_qty": 0},
                {"name": "راه‌راه طوسی", "qty": 1, "replacement_qty": 0},
                {"name": "مشکی برعکس", "qty": 1, "replacement_qty": 0},
            ],
        }])
        alias_names = [row["color_name"] for row in alias_probe["rows"]]
        if alias_names != ["سرمه ای", "توسی", "راه‌راه طوسی", "مشکی برعکس"]:
            raise RuntimeError(f"V90 color alias ordering mismatch: {alias_names}")

        get_template("core/daily_report_v45.html")

        latest_day = SaleDay.objects.order_by("-date", "-id").first()
        if latest_day is not None:
            request = RequestFactory().get(f"/sales/{latest_day.id}/report/")
            request.user = SimpleNamespace(is_authenticated=True)
            static_override = {
                **settings.STORAGES,
                "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
            }
            with override_settings(STORAGES=static_override), patch(
                "core.daily_report_v8.notify_after_daily_report",
                return_value=None,
            ):
                response = daily_report(request, latest_day.id)
            if response.status_code != 200:
                raise RuntimeError(f"V90 daily report render HTTP {response.status_code}")
            text = response.content.decode("utf-8", errors="replace")
            has_darma_sales = SaleLine.objects.filter(
                day=latest_day,
                quantity__gt=0,
                product_size__product__brand__name="دارما",
            ).exists()
            if "فروش تعدادی دارما به تفکیک رنگ و سایز" not in text and has_darma_sales:
                raise RuntimeError("V90 Darma-only matrix block missing from populated daily report")

        if SaleDay.objects.count() != before_days or SaleLine.objects.count() != before_lines:
            raise RuntimeError("V90 read-only regression changed SaleDay/SaleLine row counts")

        self.stdout.write("DARMA-ONLY FILTER = OK")
        self.stdout.write("TAKVIN / ANBARESH EXCLUDED = OK")
        self.stdout.write("DARMA COLOR + SIZE AGGREGATION = OK")
        self.stdout.write("DARMA BUSINESS COLOR ORDER = OK")
        self.stdout.write("COLOR ORDER ALIASES = OK")
        self.stdout.write("REPLACEMENT COLOR MARKER = OK")
        self.stdout.write("DAILY REPORT TEMPLATE / RENDER = OK")
        self.stdout.write("TELEGRAM SIDE EFFECT SUPPRESSED = OK")
        self.stdout.write("NO SALE ROW WRITE = OK")
        self.stdout.write(self.style.SUCCESS("SUCCESS: DAILY COLOR-SIZE MATRIX V90 CHECK PASSED"))
