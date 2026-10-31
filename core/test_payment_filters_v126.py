"""V126 isolated database tests: all-time and inclusive filtered actual payments."""
from datetime import date
from pathlib import Path

from django.conf import settings
from django.test import RequestFactory, TestCase
from django.template.loader import get_template

from core.business_tools_v91 import _payment_filter_data
from core.dateutils import format_jalali
from core.models import BusinessPayment


class PaymentHistoryFiltersV126Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # 105 records, including older ones beyond the original last-100
        # cut-off, multiple months and both paying bank accounts.
        cls.old = BusinessPayment.objects.create(
            date=date(2026, 9, 15), payee="tailor",
            source_account="melat", amount=250, note="شهریور",
        )
        cls.first = BusinessPayment.objects.create(
            date=date(2026, 10, 1), payee="tailor",
            source_account="mofid", amount=400, note="مهر اول",
        )
        cls.last = BusinessPayment.objects.create(
            date=date(2026, 10, 17), payee="tailor",
            source_account="melat", amount=900, note="مهر آخر",
        )
        cls.new = BusinessPayment.objects.create(
            date=date(2026, 10, 24), payee="tailor",
            source_account="mofid", amount=700, note="آبان",
        )
        for n in range(101):
            BusinessPayment.objects.create(
                date=date(2026, 10, 12), payee="tailor",
                source_account="melat", amount=10, note=f"پرداخت {n}",
            )
        cls.all_sum = 250 + 400 + 900 + 700 + 1010

    def _result(self, **params):
        request = RequestFactory().get("/payments/", {"section": "payments", **params})
        return _payment_filter_data(request)

    def test_all_time_includes_every_record_not_only_last_hundred(self):
        out = self._result()
        self.assertFalse(out["active"])
        self.assertEqual(out["all_total"], self.all_sum)
        self.assertEqual(out["total"], self.all_sum)
        self.assertEqual(out["all_count"], 105)
        self.assertEqual(out["count"], 105)
        self.assertEqual(len(out["rows"]), 100)
        self.assertEqual(out["page"].paginator.num_pages, 2)
        later = self._result(payment_page="2")
        self.assertEqual(len(later["rows"]), 5)
        self.assertEqual(later["total"], self.all_sum)
        self.assertEqual(later["all_total"], self.all_sum)

    def test_inclusive_persian_dates_and_both_bank_accounts(self):
        params = {
            "payment_from": format_jalali(date(2026, 10, 1)),
            "payment_to": format_jalali(date(2026, 10, 17)),
        }
        out = self._result(**params)
        self.assertTrue(out["active"])
        self.assertEqual(out["count"], 103)
        self.assertEqual(out["total"], 400 + 900 + 1010)
        self.assertEqual(out["all_total"], self.all_sum)
        self.assertEqual(len(out["rows"]), 100)
        self.assertTrue(all(date(2026, 10, 1) <= row.date <= date(2026, 10, 17) for row in out["rows"]))
        page2 = self._result(**params, payment_page="2")
        self.assertEqual(len(page2["rows"]), 3)
        self.assertEqual(page2["total"], out["total"])

    def test_start_only_end_only_and_empty_period(self):
        after = self._result(payment_from=format_jalali(date(2026, 10, 24)))
        self.assertEqual((after["total"], after["count"]), (700, 1))
        before = self._result(payment_to=format_jalali(date(2026, 9, 15)))
        self.assertEqual((before["total"], before["count"]), (250, 1))
        empty = self._result(
            payment_from=format_jalali(date(2026, 11, 1)),
            payment_to=format_jalali(date(2026, 11, 30)),
        )
        self.assertEqual((empty["total"], empty["count"], len(empty["rows"])), (0, 0, 0))
        self.assertEqual(empty["all_total"], self.all_sum)

    def test_invalid_range_and_date_fail_safely_without_changing_all_time(self):
        for params in (
            {
                "payment_from": format_jalali(date(2026, 10, 17)),
                "payment_to": format_jalali(date(2026, 10, 1)),
            },
            {"payment_from": "نامعتبر"},
        ):
            out = self._result(**params)
            self.assertTrue(out["error"])
            self.assertEqual((out["total"], out["count"]), (0, 0))
            self.assertEqual(out["all_total"], self.all_sum)
        self.assertEqual(BusinessPayment.objects.count(), 105)

    def test_template_inherits_receipt_filter_without_affecting_payment_form(self):
        get_template("core/payments_v126.html")
        source = (Path(settings.BASE_DIR) / "templates/core/payments_v126.html").read_text("utf-8")
        for marker in (
            "payment_from", "payment_to", "اعمال فیلتر",
            "پاک کردن", "مجموع پرداختی از ابتدا", "payment_filter_page",
            "payment_filtered_total", "payment_all_time_total", "payment_page",
        ):
            self.assertIn(marker, source)
        self.assertIn("{% extends 'core/payments_v91.html' %}", source)
