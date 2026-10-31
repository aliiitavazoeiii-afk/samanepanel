"""Isolated regression tests. Django's TEST database only, never live records."""
from uuid import uuid4

from django.http import QueryDict
from django.test import TestCase

from .models import (
    Brand, Color, ExcelManualRow, InventoryMovement, SaleLine,
    Size, StockBalance, StockLocation, WholesaleCustomer,
    WholesaleInvoice, WholesaleReceipt,
)
from .wholesale_logic_v119 import account, add_receipt, post_invoice
from .management.commands.repair_pedram_wholesale_v121 import repair
from .business_tools_v14 import _tailor_row, _mellat_row


class NovaniWholesaleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.brand, _ = Brand.objects.get_or_create(name="Novani", defaults={"active": True})
        cls.brand.active = True
        cls.brand.save(update_fields=["active"])
        cls.color, _ = Color.objects.get_or_create(name="مدل تست عمده", defaults={"active": True})
        cls.color.active = True
        cls.color.save(update_fields=["active"])
        cls.size, _ = Size.objects.get_or_create(name="S")
        cls.home, _ = StockLocation.objects.get_or_create(
            key=StockLocation.HOME, defaults={"title": "خانه"}
        )
        cls.stock, _ = StockBalance.objects.update_or_create(
            brand=cls.brand, color=cls.color, size=cls.size,
            location=cls.home, defaults={"qty": 10}
        )
        cls.person = ExcelManualRow.objects.create(
            section=ExcelManualRow.PERSONS, title="خریدار تست عمده",
            amount=0, active=True,
        )
        cls.buyer = WholesaleCustomer.objects.create(
            name="خریدار تست عمده", account_row=cls.person,
        )
        cls.tailor = _tailor_row(create=True)
        cls.tailor.amount = 500000
        cls.tailor.save(update_fields=["amount", "updated_at"])
        cls.mellat = _mellat_row(create=True)
        cls.mellat.amount = 100000
        cls.mellat.save(update_fields=["amount", "updated_at"])
        cls.pedram = WholesaleCustomer.objects.get(name="پدرام")

    def form(self, customer, qty="3", price="85000", token=None):
        form = QueryDict(mutable=True)
        form["customer_id"] = str(customer.pk)
        form["date"] = "۱۴۰۵/۰۷/۲۲"
        form["request_token"] = str(token or uuid4())
        form.setlist("color_id", [str(self.color.pk)])
        form.setlist("size_id", [str(self.size.pk)])
        form.setlist("quantity", [str(qty)])
        form.setlist("unit_price", [str(price)])
        return form

    def test_generic_invoice_deducts_stock_and_creates_real_receivable(self):
        form = self.form(self.buyer)
        inv = post_invoice(form)
        self.assertEqual(inv.total_amount, 255000)
        self.assertEqual(inv.quantity_total, 3)
        self.stock.refresh_from_db()
        self.person.refresh_from_db()
        self.assertEqual(self.stock.qty, 7)
        self.assertEqual(self.person.amount, 255000)
        self.assertEqual(InventoryMovement.objects.filter(
            reference__startswith=f"novani-wholesale:{inv.pk}:"
        ).count(), 1)
        self.assertEqual(SaleLine.objects.count(), 0)
        self.assertEqual(account(self.buyer)["balance"], 255000)

        with self.assertRaises(ValueError):
            post_invoice(form)  # the exact request can never debit again
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.qty, 7)

    def test_pedram_sale_increases_signed_tailor_receivable(self):
        # Prior tailor negative means we owe Pedram, not the other way round.
        self.tailor.amount = -100000
        self.tailor.save(update_fields=["amount", "updated_at"])
        invoice = post_invoice(self.form(self.pedram, qty="2", price="90000"))
        self.tailor.refresh_from_db()
        self.mellat.refresh_from_db()
        self.assertEqual(self.tailor.amount, 80000)
        self.assertEqual(self.mellat.amount, 100000)
        self.assertEqual(invoice.tailor_deducted_amount, 0)
        self.assertEqual(account(self.pedram)["gross"], 180000)
        self.assertEqual(account(self.pedram)["balance"], 80000)
        # Material-report output already applies the opposite wage effect
        # through _adjust_tailor_balance(-wage_delta).
        self.tailor.amount -= 30000
        self.tailor.save(update_fields=["amount", "updated_at"])
        self.tailor.refresh_from_db()
        self.assertEqual(self.tailor.amount, 50000)

    def test_existing_wrong_sign_pedram_invoice_repaired_once(self):
        # Simulate an invoice saved by V119/V120 before the sign fix.
        invoice = post_invoice(self.form(self.pedram, qty="2", price="90000"))
        invoice.tailor_deducted_amount = invoice.total_amount
        invoice.save(update_fields=["tailor_deducted_amount"])
        # V119 also debited the tailor instead of crediting it.
        self.tailor.refresh_from_db()
        self.tailor.amount -= 2 * invoice.total_amount
        self.tailor.save(update_fields=["amount", "updated_at"])
        self.stock.refresh_from_db()
        before_stock = self.stock.qty
        dry = repair(apply=False)
        self.assertEqual(dry["gross"], 180000)
        self.assertEqual(dry["correction"], 360000)
        fix = repair(apply=True)
        self.assertEqual(fix["correction"], 360000)
        self.tailor.refresh_from_db()
        self.assertEqual(self.tailor.amount, 680000)
        invoice.refresh_from_db()
        self.assertEqual(invoice.tailor_deducted_amount, 0)
        self.assertEqual(repair(apply=True)["correction"], 0)
        self.tailor.refresh_from_db()
        self.assertEqual(self.tailor.amount, 680000)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.qty, before_stock)
        self.assertEqual(account(self.pedram)["balance"], 680000)

    def test_shortage_cannot_partially_debit_anything(self):
        with self.assertRaises(ValueError):
            post_invoice(self.form(self.buyer, qty="11"))
        self.stock.refresh_from_db()
        self.person.refresh_from_db()
        self.assertEqual(self.stock.qty, 10)
        self.assertEqual(self.person.amount, 0)
        self.assertEqual(WholesaleInvoice.objects.count(), 0)

    def test_receipt_transfers_receivable_to_mellat_once(self):
        post_invoice(self.form(self.buyer))
        receipt_form = QueryDict(mutable=True)
        receipt_form["customer_id"] = str(self.buyer.pk)
        receipt_form["date"] = "۱۴۰۵/۰۷/۲۲"
        receipt_form["amount"] = "100000"
        receipt_form["request_token"] = str(uuid4())
        receipt = add_receipt(receipt_form)
        self.assertEqual(receipt.amount, 100000)
        self.person.refresh_from_db()
        self.mellat.refresh_from_db()
        self.assertEqual(self.person.amount, 155000)
        self.assertEqual(self.mellat.amount, 200000)
        self.assertEqual(account(self.buyer)["balance"], 155000)
        with self.assertRaises(ValueError):
            add_receipt(receipt_form)
        self.assertEqual(WholesaleReceipt.objects.count(), 1)

    def test_multiple_colors_and_sizes_post_as_one_atomic_invoice(self):
        # Mirrors one V120 matrix submission: two colors, three populated
        # size cells and one price shared by all sizes of the first color.
        second_color, _ = Color.objects.get_or_create(
            name="مدل دوم تست عمده", defaults={"active": True}
        )
        second_color.active = True
        second_color.save(update_fields=["active"])
        medium, _ = Size.objects.get_or_create(name="M")
        xl, _ = Size.objects.get_or_create(name="XL")
        stock_m, _ = StockBalance.objects.update_or_create(
            brand=self.brand, color=self.color, size=medium,
            location=self.home, defaults={"qty": 10}
        )
        stock_xl, _ = StockBalance.objects.update_or_create(
            brand=self.brand, color=second_color, size=xl,
            location=self.home, defaults={"qty": 10}
        )
        form = self.form(self.buyer, qty="2", price="80000")
        form.setlist("color_id", [
            str(self.color.pk), str(self.color.pk), str(second_color.pk),
        ])
        form.setlist("size_id", [
            str(self.size.pk), str(medium.pk), str(xl.pk),
        ])
        form.setlist("quantity", ["2", "1", "3"])
        form.setlist("unit_price", ["80000", "80000", "95000"])
        invoice = post_invoice(form)
        self.assertEqual(invoice.quantity_total, 6)
        self.assertEqual(invoice.total_amount, 525000)
        self.assertEqual(invoice.lines.count(), 3)
        self.assertEqual(InventoryMovement.objects.filter(
            reference__startswith=f"novani-wholesale:{invoice.pk}:"
        ).count(), 3)
        self.stock.refresh_from_db()
        stock_m.refresh_from_db()
        stock_xl.refresh_from_db()
        self.person.refresh_from_db()
        self.assertEqual((self.stock.qty, stock_m.qty, stock_xl.qty), (8, 9, 7))
        self.assertEqual(self.person.amount, 525000)
        self.assertEqual(SaleLine.objects.count(), 0)

    def test_pedram_cannot_receive_second_payment(self):
        form = QueryDict(mutable=True)
        form["customer_id"] = str(self.pedram.pk)
        form["date"] = "۱۴۰۵/۰۷/۲۲"
        form["amount"] = "5000"
        form["request_token"] = str(uuid4())
        with self.assertRaises(ValueError):
            add_receipt(form)
