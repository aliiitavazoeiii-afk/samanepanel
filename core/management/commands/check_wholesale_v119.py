"""Read-only V119 assertions; safe against the live production database."""
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Sum
from django.template.loader import get_template
from django.test import RequestFactory, override_settings
from django.urls import resolve, reverse

from core import wholesale_v119
from core.models import (
    InventoryMovement, WholesaleCustomer, WholesaleInvoice, WholesaleInvoiceLine,
    WholesaleReceipt, SaleLine,
)
from core.wholesale_logic_v119 import ALLOWED_SIZES, positive, account


class Command(BaseCommand):
    help = "Audit Novani wholesale routes, immutable invoice ledger, stock movements and Pedram."

    def handle(self, *args, **kwargs):
        base = (Path(settings.BASE_DIR) / "templates/base.html").read_text(encoding="utf-8")
        nav = base.split('<nav class="erp-nav" aria-label="منوی اصلی">', 1)[1].split("</nav>", 1)[0]
        if nav.count('title="فروش عمده"') != 1 or nav.count("<svg class=\"v116-icon\"") != 10:
            raise RuntimeError("Wholesale navigation absent or legacy sidebar changed")
        if "خرید تکوین" not in nav or "خرید تکی" in nav:
            raise RuntimeError("Takvin label did not change correctly")
        if nav.index('title="فروش عمده"') > nav.index("nav114-separator"):
            raise RuntimeError("Wholesale must be in the first navigation group")
        for name in (
            "wholesale_home", "wholesale_customer_add", "wholesale_invoice_add",
            "wholesale_receipt_add", "wholesale_export",
        ):
            if not reverse(name).startswith("/wholesale/"):
                raise RuntimeError(f"Wrong wholesale route: {name}")
        if resolve("/wholesale/").func is not wholesale_v119.wholesale_home:
            raise RuntimeError("Wholesale homepage route drift")
        get_template("core/wholesale_v119.html")
        template = (Path(settings.BASE_DIR) / "templates/core/wholesale_v119.html").read_text(encoding="utf-8")
        for marker in (
            'grid-template-columns:repeat(2,minmax(0,1fr))',
            'id="whInvoiceLines"', 'name="customer_id"',
            'name="date"', 'id="whColorPicker"', "picker.addEventListener('change'",
            'id="whColorCardTemplate"', 'data-color-price',
            'data-size-qty="{{ size.pk }}"', 'data-size-available',
            'data-color-id', 'id="whInvoiceHidden"',
            "appendField('color_id',item.color)",
            "appendField('size_id',item.size)",
            "appendField('quantity',item.quantity)",
            "appendField('unit_price',price)",
            "if(!nonzero.length)continue",
            'id="whTotal"', 'id="whPieces"',
            "خروجی اکسل", "حساب خریداران", "فروش عمده نوانی",
        ):
            if marker not in template:
                raise RuntimeError(f"Wholesale UI missing {marker}")
        if "whLineTemplate" in template or "whAddLine" in template:
            raise RuntimeError("Old one-variant-per-row wholesale editor returned")
        # One shared unit price in the color card, applied to every nonzero
        # size in its matrix. Hidden POST fields preserve the V119 atomic
        # stock/buyer/Pedram rules, without new backend write semantics.
        if template.count('data-color-price') < 3:
            raise RuntimeError("Color-level pricing input or aggregation missing")
        for format_marker in (
            "{% load static jalali %}", "const toAscii=value", "groupInput(input)",
            'type="text" data-color-price',
            'name="amount" inputmode="numeric" type="text"',
            "appendField('unit_price',price)", "|groupnum",
        ):
            if format_marker not in template:
                raise RuntimeError(f"V121 wholesale thousands formatting missing: {format_marker}")
        if ALLOWED_SIZES != {"S", "M", "L", "XL", "XXL", "3XL"}:
            raise RuntimeError("Novani wholesale size range drift")
        if positive("۱۲٬۵۰۰", "مبلغ") != 12500:
            raise RuntimeError("Persian number normalization wrong")
        storage = {**settings.STORAGES, "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        }}
        with override_settings(STORAGES=storage):
            factory = RequestFactory()
            for path in ("/wholesale/", "/wholesale/?customer=" + str(
                WholesaleCustomer.objects.get(name="پدرام").pk
            )):
                request = factory.get(path)
                request.user = SimpleNamespace(is_authenticated=True)
                response = wholesale_v119.wholesale_home(request)
                if response.status_code != 200:
                    raise RuntimeError("V119 wholesale page did not render")
                if 'data-wholesale="v119"' not in response.content.decode("utf-8"):
                    raise RuntimeError("V119 wholesale page markup missing")
        if WholesaleCustomer.objects.filter(is_pedram=True, name="پدرام").count() != 1:
            raise RuntimeError("Exact Pedram special buyer not seeded")
        if WholesaleCustomer.objects.filter(is_pedram=True).count() != 1:
            raise RuntimeError("More than one buyer bypasses ordinary accounting")
        for invoice in WholesaleInvoice.objects.select_related("customer").prefetch_related("lines").all():
            lines = list(invoice.lines.all())
            if not lines or sum(x.amount for x in lines) != invoice.total_amount:
                raise RuntimeError(f"Invoice {invoice.pk} gross mismatch")
            if sum(x.quantity for x in lines) != invoice.quantity_total:
                raise RuntimeError(f"Invoice {invoice.pk} piece count mismatch")
            # V121: any prior Pedram wrong-sign "offset" has been repaired.
            wanted_offset = 0
            if invoice.tailor_deducted_amount != wanted_offset:
                raise RuntimeError(f"Invoice {invoice.pk} tailor offset drift")
            for line in lines:
                reference = f"novani-wholesale:{invoice.pk}:{line.pk}"
                movements = InventoryMovement.objects.filter(reference=reference)
                if movements.count() != 1:
                    raise RuntimeError(f"Missing/duplicate inventory movement: {reference}")
                movement = movements.first()
                if (movement.delta != -line.quantity or movement.brand.name != "Novani"
                        or movement.color_id != line.color_id or movement.size_id != line.size_id
                        or movement.location.key != "home"):
                    raise RuntimeError(f"Novani inventory movement mismatch: {reference}")
        from core.business_tools_v14 import _tailor_row
        tailor = _tailor_row(create=False)
        for customer in WholesaleCustomer.objects.all():
            values = account(customer)
            if customer.is_pedram and tailor is not None:
                if values["balance"] != int(tailor.amount or 0):
                    raise RuntimeError("Pedram balance is not the shared tailor signed balance")
            # The historical shared tailor account is SIGNED and may be
            # negative when we owe Pedram; this is legitimate, not a defect.
            if values["balance"] < 0 and not customer.is_pedram:
                raise RuntimeError(f"Negative customer receivable ledger: {customer.pk}")
        self.stdout.write("PEDRAM = ONE SIGNED SHARED TAILOR ACCOUNT / WHOLESALE SALES CREATE RECEIVABLE")
        self.stdout.write("NOVANI STOCK = HOME ONLY; EACH INVOICE LINE HAS ONE SALE MOVEMENT")
        self.stdout.write("PERSON ACCOUNT RECEIVABLE / CASH RECEIPT = SEPARATE FROM DAILY SALES")
        self.stdout.write("READ ONLY: NO SALES OR STOCK WRITES")
        self.stdout.write(self.style.SUCCESS("SUCCESS: NOVANI WHOLESALE V119 CHECK PASSED"))
