"""Read-only regression for V91 receipt date/source filters and filtered totals."""
from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Sum
from django.test import RequestFactory, override_settings
from django.template.loader import get_template
from django.urls import resolve

from core import business_tools_v91
from core.dateutils import format_jalali
from core.models import AccountEntry, BusinessPayment, DigikalaSettlement


class Command(BaseCommand):
    help = "Read-only: validate V91 receipt filters, totals, route and render."

    def handle(self, *args, **kwargs):
        before = {
            "receipts": DigikalaSettlement.objects.count(),
            "payments": BusinessPayment.objects.count(),
            "account_entries": AccountEntry.objects.count(),
        }

        match = resolve("/payments/")
        if match.func is not business_tools_v91.payments:
            raise RuntimeError("Active /payments/ route is not V91")

        get_template("core/payments_v91.html")

        factory = RequestFactory()
        all_request = factory.get("/payments/", {"section": "receipts"})
        all_data = business_tools_v91._receipt_filter_data(all_request)
        expected_all_total = int(
            DigikalaSettlement.objects.aggregate(v=Sum("amount"))["v"] or 0
        )
        expected_all_count = DigikalaSettlement.objects.count()
        if all_data["total"] != expected_all_total or all_data["count"] != expected_all_count:
            raise RuntimeError("V91 all-receipts total/count mismatch")

        first = DigikalaSettlement.objects.order_by("date", "id").first()
        last = DigikalaSettlement.objects.order_by("-date", "-id").first()
        if first is not None and last is not None:
            range_request = factory.get(
                "/payments/",
                {
                    "section": "receipts",
                    "receipt_from": format_jalali(first.date),
                    "receipt_to": format_jalali(last.date),
                },
            )
            range_data = business_tools_v91._receipt_filter_data(range_request)
            expected_range = DigikalaSettlement.objects.filter(
                date__gte=first.date,
                date__lte=last.date,
            )
            expected_range_total = int(expected_range.aggregate(v=Sum("amount"))["v"] or 0)
            if range_data["total"] != expected_range_total or range_data["count"] != expected_range.count():
                raise RuntimeError("V91 date-range total/count mismatch")

            source = str(last.source or "").strip()
            if source:
                source_request = factory.get(
                    "/payments/",
                    {
                        "section": "receipts",
                        "receipt_from": format_jalali(first.date),
                        "receipt_to": format_jalali(last.date),
                        "receipt_source": source,
                    },
                )
                source_data = business_tools_v91._receipt_filter_data(source_request)
                expected_source = expected_range.filter(source=source)
                expected_source_total = int(expected_source.aggregate(v=Sum("amount"))["v"] or 0)
                if source_data["total"] != expected_source_total or source_data["count"] != expected_source.count():
                    raise RuntimeError("V91 source-filter total/count mismatch")

        bad_request = factory.get(
            "/payments/",
            {
                "section": "receipts",
                "receipt_from": "1405/12/29",
                "receipt_to": "1405/01/01",
            },
        )
        bad_data = business_tools_v91._receipt_filter_data(bad_request)
        if not bad_data["error"] or bad_data["rows"] or bad_data["total"] != 0:
            raise RuntimeError("V91 invalid-range guard failed")

        render_request = factory.get("/payments/", {"section": "receipts"})
        render_request.user = SimpleNamespace(is_authenticated=True)
        static_override = {
            **settings.STORAGES,
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }
        with override_settings(STORAGES=static_override):
            response = business_tools_v91.payments(render_request)
        if response.status_code != 200:
            raise RuntimeError(f"V91 payments render HTTP {response.status_code}")
        text = response.content.decode("utf-8", errors="replace")
        for required in ("از تاریخ", "تا تاریخ", "همه دریافتی‌ها", "جمع کل"):
            if required not in text:
                raise RuntimeError(f"V91 receipt filter UI marker missing: {required}")

        after = {
            "receipts": DigikalaSettlement.objects.count(),
            "payments": BusinessPayment.objects.count(),
            "account_entries": AccountEntry.objects.count(),
        }
        if after != before:
            raise RuntimeError(f"V91 read-only regression changed financial row counts: {before} -> {after}")

        self.stdout.write("PAYMENTS V91 ROUTE = OK")
        self.stdout.write("ALL RECEIPTS TOTAL / COUNT = OK")
        self.stdout.write("JALALI DATE RANGE FILTER = OK")
        self.stdout.write("SOURCE FILTER = OK")
        self.stdout.write("INVALID RANGE GUARD = OK")
        self.stdout.write("PAYMENTS V91 TEMPLATE / RENDER = OK")
        self.stdout.write("NO FINANCIAL ROW WRITE = OK")
        self.stdout.write(self.style.SUCCESS("SUCCESS: RECEIPT FILTERS V91 CHECK PASSED"))
