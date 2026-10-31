"""V111 read-only regression: product definition -> canonical colors/sizes -> daily sale UI."""
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.contrib.messages.storage.cookie import CookieStorage
from django.core.management.base import BaseCommand
from django.db import transaction
from django.test import RequestFactory, override_settings
from django.template.loader import get_template
from django.urls import resolve

from core import product_center_v93, sale_entry_v60, settings_product_v60
from core.brand_colors import colors_for_brand
from core.dateutils import format_jalali
from core.models import (
    AccountEntry, Brand, Color, ProductCode, ProductComposition, ProductSize,
    SaleDay, SaleLine, Size, StockBalance,
)


def digest(model):
    fields = [f.attname for f in model._meta.concrete_fields]
    h = sha256()
    for row in model.objects.order_by(model._meta.pk.attname).values_list(*fields):
        h.update(repr(tuple(row)).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def state():
    return {m.__name__: digest(m) for m in (
        Brand, Color, Size, ProductCode, ProductComposition, ProductSize,
        StockBalance, SaleDay, SaleLine, AccountEntry,
    )}


class Command(BaseCommand):
    help = "V111 product registration, color catalog and daily sale read-only regression."

    def handle(self, *args, **kwargs):
        before = state()
        if not hasattr(ProductCode, "title"):
            raise RuntimeError("V111 product title schema is missing; apply migration 0018")

        for template in (
            "core/settings_products_v93.html",
            "core/settings_product_form_v60.html",
            "core/_product_center_colors_v93.html",
            "core/sale_size.html",
        ):
            get_template(template)

        if resolve("/settings/products/").func is not product_center_v93.settings_products:
            raise RuntimeError("Product center route drift")
        if resolve("/settings/products/new/").func is not settings_product_v60.settings_product_form:
            raise RuntimeError("Product creation route drift")
        if resolve("/sales/1/1/1/").func is not sale_entry_v60.sale_size:
            raise RuntimeError("Daily sale size route drift")

        static_storage = {
            **settings.STORAGES,
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }
        rf = RequestFactory()
        def req(path, payload=None):
            result = rf.post(path, payload) if payload is not None else rf.get(path)
            result.user = SimpleNamespace(is_authenticated=True)
            result._messages = CookieStorage(result)
            return result

        with override_settings(STORAGES=static_storage):
            hub = product_center_v93.settings_products(req("/settings/products/"))
            if hub.status_code != 200 or 'data-product-definition-card="v111"' not in hub.content.decode("utf-8"):
                raise RuntimeError("The fourth product-definition card is not present")
            colors = product_center_v93.settings_products(req("/settings/products/?section=colors"))
            if colors.status_code != 200 or "عنوان محصول" not in colors.content.decode("utf-8"):
                raise RuntimeError("Colors catalog lacks product titles")
            form = settings_product_v60.settings_product_form(req("/settings/products/new/"))
            if form.status_code != 200:
                raise RuntimeError("Product definition form did not render")
            form_text = form.content.decode("utf-8")
            for marker in ('name="code"', 'name="title"', 'name="pack_qty"', "compositionTotal", "size-check"):
                if marker not in form_text:
                    raise RuntimeError(f"Product form missing canonical field: {marker}")

            darma = Brand.objects.filter(name="دارما", active=True).first()
            if not darma:
                raise RuntimeError("Darma brand not available for test")
            color = colors_for_brand(darma).first()
            size = Size.objects.filter(name="M").first()
            if not color or not size:
                raise RuntimeError("No Darma color or size available for product test")

            with transaction.atomic():
                try:
                    code = "v111-definition-rollback-probe"
                    if ProductCode.objects.filter(brand=darma, code=code).exists():
                        raise RuntimeError("Reserved regression product code already exists")
                    payload = {
                        "brand": str(darma.id),
                        "code": code,
                        "title": "محصول آزمایشی V111",
                        "pack_qty": "1",
                        "active": "on",
                        "note": "یادداشت محفوظ",
                        "color_%s" % color.id: "1",
                        "size_%s" % size.id: "on",
                        "sale_price_%s" % size.id: "450000",
                        "sale_price_effective_from": format_jalali(date.today() + timedelta(days=1)),
                    }
                    response = settings_product_v60.settings_product_form(
                        req("/settings/products/new/", payload)
                    )
                    if response.status_code not in (301, 302):
                        raise RuntimeError(
                            f"Creating a product failed HTTP {response.status_code}"
                        )
                    product = ProductCode.objects.filter(brand=darma, code=code).first()
                    if not product or product.title != payload["title"] or product.note != "یادداشت محفوظ":
                        raise RuntimeError("Product code/title/note were not saved separately")
                    if product.pack_qty != 1:
                        raise RuntimeError("Pack quantity was not persisted")
                    parts = list(ProductComposition.objects.filter(product=product))
                    if len(parts) != 1 or parts[0].color_id != color.id or parts[0].qty != 1:
                        raise RuntimeError("Color composition not saved to canonical catalog")
                    ps = ProductSize.objects.filter(product=product, size=size, active=True).first()
                    if not ps:
                        raise RuntimeError("Product size not created in daily-order source")

                    colors_after = product_center_v93.settings_products(
                        req("/settings/products/?section=colors")
                    )
                    text = colors_after.content.decode("utf-8")
                    for value in (code, payload["title"], color.name):
                        if value not in text:
                            raise RuntimeError(
                                f"New product not immediately visible in color catalog: {value}"
                            )
                    sale_day = SaleDay.objects.create(
                        date=date.today() + timedelta(days=5000)
                    )
                    sale_screen = sale_entry_v60.sale_size(
                        req(f"/sales/{sale_day.id}/{darma.id}/{size.id}/"),
                        sale_day.id, darma.id, size.id
                    )
                    sale_html = sale_screen.content.decode("utf-8")
                    for value in (code, payload["title"], color.name, "data-sale-color-composition"):
                        if value not in sale_html:
                            raise RuntimeError(
                                f"Daily order did not read product catalog data: {value}"
                            )
                finally:
                    transaction.set_rollback(True)

        # Mirrors carry Darma titles into the Anbaresh catalog channel.
        mirror = (Path(settings.BASE_DIR) / "core/anbaresh_catalog_v19.py").read_text(encoding="utf-8")
        if 'target.title = source.title' not in mirror:
            raise RuntimeError("Anbaresh mirror does not propagate product titles")

        after = state()
        if after != before:
            raise RuntimeError("V111 regression changed persistent product/account/stock/sale state")

        self.stdout.write("PRODUCT DEFINITION CARD = FOURTH CARD")
        self.stdout.write("CODE + INDEPENDENT TITLE + PACK COUNT = PERSISTED")
        self.stdout.write("COLOR COMPOSITION = CANONICAL PRODUCTCOMPOSITION")
        self.stdout.write("SIZES = CANONICAL PRODUCTSIZE")
        self.stdout.write("COLOR CATALOG IMMEDIATE COVERAGE = OK")
        self.stdout.write("DAILY SALE CODE/TITLE/COLORS = READ FROM SAME CATALOG")
        self.stdout.write("ANBARESH DARMA MIRROR TITLE = PRESERVED")
        self.stdout.write("LEGACY PRODUCT NOTES = NOT OVERWRITTEN")
        self.stdout.write("TRANSACTIONAL TEST ROLLBACK = OK")
        self.stdout.write("NO PERSISTENT BUSINESS STATE WRITE = OK")
        self.stdout.write(self.style.SUCCESS(
            "SUCCESS: PRODUCT DEFINITION + COLORS + DAILY SALES V111 CHECK PASSED"
        ))
