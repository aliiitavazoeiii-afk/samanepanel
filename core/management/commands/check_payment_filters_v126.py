"""Production read-only audit: V126 payment date filters and exact cash totals."""
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Sum
from django.template.loader import get_template
from django.test import RequestFactory, override_settings
from django.urls import resolve

from core import business_tools_v91
from core.dateutils import format_jalali
from core.models import AccountEntry, BusinessPayment, DigikalaSettlement


class Command(BaseCommand):
    help = "Read-only: verify payment all-time totals, inclusive Jalali date filters, pagination and UI."

    def handle(self, *args, **kwargs):
        before = {
            "payments": BusinessPayment.objects.count(),
            "receipts": DigikalaSettlement.objects.count(),
            "account_entries": AccountEntry.objects.count(),
        }
        if resolve("/payments/").func is not business_tools_v91.payments:
            raise RuntimeError("Active /payments/ route differs from V126 read-only view")

        factory = RequestFactory()
        all_data = business_tools_v91._payment_filter_data(
            factory.get("/payments/", {"section": "payments"})
        )
        all_count = BusinessPayment.objects.count()
        all_total = int(
            BusinessPayment.objects.aggregate(v=Sum("amount"))["v"] or 0
        )
        if (
            all_data["total"] != all_total
            or all_data["all_total"] != all_total
            or all_data["count"] != all_count
            or all_data["all_count"] != all_count
            or len(all_data["rows"]) != min(100, all_count)
        ):
            raise RuntimeError("Payment all-history total/count or first-page count mismatch")

        first = BusinessPayment.objects.order_by("date", "id").first()
        last = BusinessPayment.objects.order_by("-date", "-id").first()
        if first is not None and last is not None:
            data = business_tools_v91._payment_filter_data(factory.get(
                "/payments/",
                {
                    "section": "payments",
                    "payment_from": format_jalali(first.date),
                    "payment_to": format_jalali(last.date),
                },
            ))
            if data["total"] != all_total or data["count"] != all_count:
                raise RuntimeError("Inclusive full date-range payment total/count mismatch")
            bounded = business_tools_v91._payment_filter_data(factory.get(
                "/payments/", {
                    "section": "payments",
                    "payment_from": format_jalali(last.date),
                    "payment_to": format_jalali(last.date),
                },
            ))
            expected = BusinessPayment.objects.filter(date=last.date)
            expected_total = int(expected.aggregate(v=Sum("amount"))["v"] or 0)
            if bounded["total"] != expected_total or bounded["count"] != expected.count():
                raise RuntimeError("One-day inclusive Jalali filter fails")

            if all_count > 100:
                second = business_tools_v91._payment_filter_data(factory.get(
                    "/payments/", {"section": "payments", "payment_page": "2"},
                ))
                if (
                    second["total"] != all_total
                    or len(second["rows"]) != min(100, all_count - 100)
                ):
                    raise RuntimeError("Payment list pages accidentally filter cash totals")

        wrong = business_tools_v91._payment_filter_data(factory.get(
            "/payments/", {
                "section": "payments",
                "payment_from": "1405/12/29",
                "payment_to": "1405/01/01",
            },
        ))
        if not wrong["error"] or wrong["rows"] or wrong["total"] or wrong["all_total"] != all_total:
            raise RuntimeError("Invalid payment date range did not fail safely")

        # V91 receipts must remain independent and unchanged.
        receipt_data = business_tools_v91._receipt_filter_data(
            factory.get("/payments/", {"section": "receipts"})
        )
        expected_receipts = int(
            DigikalaSettlement.objects.aggregate(v=Sum("amount"))["v"] or 0
        )
        if receipt_data["total"] != expected_receipts:
            raise RuntimeError("Original receipt totals unexpectedly changed")

        get_template("core/payments_v126.html")
        source = (
            Path(settings.BASE_DIR) / "templates/core/payments_v126.html"
        ).read_text(encoding="utf-8")
        for marker in (
            "payment_from", "payment_to", "اعمال فیلتر",
            "پاک کردن", "payment_all_time_total", "payment_filtered_total",
            "payment_page", "مجموع پرداختی از ابتدا",
        ):
            if marker not in source:
                raise RuntimeError(f"V126 payments UI regression: {marker}")

        test_req = factory.get("/payments/", {"section": "payments"})
        test_req.user = SimpleNamespace(is_authenticated=True)
        static_override = {
            **settings.STORAGES,
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
            },
        }
        with override_settings(STORAGES=static_override):
            response = business_tools_v91.payments(test_req)
        if response.status_code != 200:
            raise RuntimeError(f"Payment history page render failed: {response.status_code}")
        html = response.content.decode("utf-8", errors="replace")
        for marker in ("از تاریخ", "تا تاریخ", "مجموع پرداختی از ابتدا", "جمع کل پرداختی‌ها"):
            if marker not in html:
                raise RuntimeError(f"V126 payment filter missing from rendered HTML: {marker}")

        after = {
            "payments": BusinessPayment.objects.count(),
            "receipts": DigikalaSettlement.objects.count(),
            "account_entries": AccountEntry.objects.count(),
        }
        if before != after:
            raise RuntimeError("V126 read-only payments check changed financial records")
        self.stdout.write(
            f"PAYMENTS_ALL_TIME_COUNT={all_count} PAYMENTS_ALL_TIME_CASH_TOMAN={all_total}"
        )
        self.stdout.write(
            "V126 PAYMENT_FILTER=OK; JALALI_DATE_INCLUSIVE=OK; PAGINATION=OK; "
            "RECEIPT_V91=UNCHANGED; DATA_WRITES=ZERO"
        )
        self.stdout.write(self.style.SUCCESS(
            "SUCCESS: V126 PAYMENT HISTORY FILTERS CHECK PASSED"
        ))
