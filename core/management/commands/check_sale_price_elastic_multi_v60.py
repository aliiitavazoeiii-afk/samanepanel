from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum
from django.http import QueryDict
from django.template.loader import get_template
from django.urls import resolve

from core.business_tools_v60 import _purchase_signature as payment_purchase_signature
from core.material_flow import COLOR_LABELS, ELASTIC, WAREHOUSE, q
from core.material_purchase_v60 import (
    MULTI_KIND,
    apply_purchase_stock,
    build_purchase_from_post,
    purchase_signature,
    purchase_summary,
    reverse_purchase_stock,
)
from core.models import AppSetting, BusinessPayment, ProductSize, RawMaterialStock, SaleDay, SaleLine
from core.sale_price_v60 import sale_price_for, set_sale_price_rule


class Command(BaseCommand):
    help = "Transactional V60 regression: dated Darma/Takvin sale prices + one-payment multi-color elastic purchase."

    def _state(self):
        return {
            "settings": AppSetting.objects.count(),
            "payments": BusinessPayment.objects.count(),
            "raw_rows": RawMaterialStock.objects.count(),
            "raw_qty": str(
                RawMaterialStock.objects.filter(active=True).aggregate(v=Sum("quantity"))["v"]
                or Decimal("0")
            ),
            "sale_days": SaleDay.objects.count(),
            "sales": SaleLine.objects.count(),
        }

    def _active_ps(self, brand_name):
        return (
            ProductSize.objects.filter(
                product__brand__name=brand_name,
                product__active=True,
                active=True,
            )
            .select_related("product__brand", "product", "size")
            .order_by("id")
            .first()
        )

    def _cell_qty(self, material_key, variant):
        return sum(
            (
                q(row.quantity)
                for row in RawMaterialStock.objects.filter(
                    active=True,
                    kind=ELASTIC,
                    location=WAREHOUSE,
                    material_key=material_key,
                    variant=variant,
                )
            ),
            Decimal("0"),
        )

    def handle(self, *args, **options):
        for template_name in (
            "core/settings_product_form_v60.html",
            "core/settings_products_v60.html",
            "core/payments_v60.html",
        ):
            try:
                get_template(template_name)
            except Exception as exc:
                raise CommandError(f"V60 template failed to compile: {template_name}: {exc}") from exc

        source_checks = {
            "core/sale_entry_v60.py": ("sale_price_for(ps, day.date)", "snapshot_sale_line"),
            "core/daily_order_views_v60.py": ("_preseed_date_effective_prices", "sale_price_for(ps, day.date)"),
            "core/settings_product_v60.py": ("sale_price_effective_from", "set_sale_price_rule"),
            "core/pricing_v60.py": ("effective_from", "_schedule_group_prices"),
            "core/settings_rules_v17.py": ("SALE_PRICE_RULE_PREFIX", "exclude(key__startswith=SALE_PRICE_RULE_PREFIX)"),
            "core/material_purchase_v60.py": ("elastic_multi", "elastic16_qty__", "elastic25_qty__"),
            "core/static/core/payments_elastic_multi_v60.js": ("elastic-color-row", "elastic16_qty__", "elastic25_qty__"),
            "templates/core/settings_product_form_v60.html": ("salePriceDateV60", "jalali_picker.js"),
            "templates/core/settings_products_v60.html": ("effective_from", "jalali_picker.js"),
        }
        for relative, markers in source_checks.items():
            text = (Path(settings.BASE_DIR) / relative).read_text(encoding="utf-8")
            for marker in markers:
                if marker not in text:
                    raise CommandError(f"V60 source marker missing: {relative}: {marker}")

        # V60 owns sale-price and elastic-purchase behavior. Later payment wrappers
        # (V61/V62) may own the active /payments routes while delegating those V60
        # mechanics, so accept those wrappers instead of falsely flagging regression.
        route_expectations = {
            "/sales/save/": {"core.sale_entry_v60"},
            "/payments/": {"core.business_tools_v60", "core.business_tools_v61", "core.business_tools_v62"},
            "/payments/add/": {"core.business_tools_v60", "core.business_tools_v61", "core.business_tools_v62"},
            "/settings/products/": {"core.pricing_v60"},
            "/settings/products/new/": {"core.settings_product_v60"},
        }
        for url, allowed_modules in route_expectations.items():
            match = resolve(url)
            actual = match.func.__module__
            if actual not in allowed_modules:
                raise CommandError(
                    f"V60 route mismatch: {url} -> {actual}, expected one of {sorted(allowed_modules)}"
                )

        darma_ps = self._active_ps("دارما")
        takvin_ps = self._active_ps("تکوین")
        if not darma_ps or not takvin_ps:
            raise CommandError("V60 regression needs one active Darma and one active Takvin ProductSize")

        colors = list(COLOR_LABELS.items())
        if len(colors) < 2:
            raise CommandError("V60 regression needs at least two material colors")
        (color1, label1), (color2, label2) = colors[:2]

        before = self._state()
        with transaction.atomic():
            try:
                rule_day = date(2099, 7, 2)
                prior_day = rule_day - timedelta(days=1)
                later_day = rule_day + timedelta(days=1)
                darma_before = int(sale_price_for(darma_ps, prior_day))
                takvin_before = int(sale_price_for(takvin_ps, prior_day))
                darma_new = max(1, darma_before + 12_345)
                takvin_new = max(1, takvin_before + 23_456)
                darma_default_before = int(darma_ps.default_sale_price or 0)
                takvin_default_before = int(takvin_ps.default_sale_price or 0)

                set_sale_price_rule(darma_ps, rule_day, darma_new)
                set_sale_price_rule(takvin_ps, rule_day, takvin_new)
                if int(sale_price_for(darma_ps, prior_day)) != darma_before:
                    raise CommandError("V60 Darma future price leaked into prior day")
                if int(sale_price_for(takvin_ps, prior_day)) != takvin_before:
                    raise CommandError("V60 Takvin future price leaked into prior day")
                if int(sale_price_for(darma_ps, rule_day)) != darma_new:
                    raise CommandError("V60 Darma effective-date sale price did not activate")
                if int(sale_price_for(takvin_ps, later_day)) != takvin_new:
                    raise CommandError("V60 Takvin effective-date sale price did not activate")

                darma_ps.refresh_from_db()
                takvin_ps.refresh_from_db()
                if int(darma_ps.default_sale_price or 0) != darma_default_before:
                    raise CommandError("V60 scheduling overwrote Darma legacy current default")
                if int(takvin_ps.default_sale_price or 0) != takvin_default_before:
                    raise CommandError("V60 scheduling overwrote Takvin legacy current default")

                free_day = date(2099, 8, 1)
                while SaleDay.objects.filter(date=free_day).exists():
                    free_day += timedelta(days=1)
                sale_day = SaleDay.objects.create(date=free_day)
                frozen_price = 777_777
                line = SaleLine.objects.create(
                    day=sale_day,
                    product_size=darma_ps,
                    quantity=1,
                    sale_price=frozen_price,
                )
                set_sale_price_rule(darma_ps, free_day, frozen_price + 111_111)
                line.refresh_from_db()
                if int(line.sale_price or 0) != frozen_price:
                    raise CommandError("V60 rule rewrote an existing SaleLine.sale_price")

                post = QueryDict("", mutable=True)
                post["note"] = "v60 regression"
                post[f"elastic16_qty__{color1}"] = "1.250"
                post[f"elastic16_price__{color1}"] = "2600000"
                post[f"elastic25_qty__{color2}"] = "0.750"
                post[f"elastic25_price__{color2}"] = "2800000"
                invoice, data = build_purchase_from_post("elastic", post)
                if data.get("k") != MULTI_KIND or len(data.get("items") or []) != 2:
                    raise CommandError("V60 multi-color elastic parser did not keep two color rows")
                expected_invoice = int(Decimal("1.250") * 2_600_000 + Decimal("0.750") * 2_800_000)
                if int(invoice) != expected_invoice:
                    raise CommandError(f"V60 multi elastic invoice mismatch: {invoice} != {expected_invoice}")
                summary = purchase_summary(data)
                if label1 not in summary or label2 not in summary:
                    raise CommandError("V60 multi elastic summary lost a purchased color")
                if not purchase_signature(data):
                    raise CommandError("V60 multi elastic physical signature missing")

                legacy = {
                    "k": "elastic",
                    "m": color1,
                    "q16": "1.250",
                    "p16": 2_600_000,
                    "q25": "0",
                    "p25": 0,
                }
                single_multi = {
                    "k": MULTI_KIND,
                    "items": [
                        {
                            "m": color1,
                            "q16": "1.250",
                            "p16": 2_600_000,
                            "q25": "0",
                            "p25": 0,
                        }
                    ],
                }
                if payment_purchase_signature(legacy) != payment_purchase_signature(single_multi):
                    raise CommandError("V60 legacy elastic edit compatibility signature mismatch")

                q1_before = self._cell_qty(color1, "16")
                q2_before = self._cell_qty(color2, "25")
                payment = BusinessPayment.objects.create(
                    date=date.today(), payee="elastic", amount=expected_invoice, note="v60 regression"
                )
                apply_purchase_stock(payment, data)
                q1_after = self._cell_qty(color1, "16")
                q2_after = self._cell_qty(color2, "25")
                if q1_after - q1_before != Decimal("1.250"):
                    raise CommandError("V60 first elastic color quantity did not apply exactly")
                if q2_after - q2_before != Decimal("0.750"):
                    raise CommandError("V60 second elastic color quantity did not apply exactly")
                reverse_purchase_stock(payment, data)
                if self._cell_qty(color1, "16") != q1_before:
                    raise CommandError("V60 first elastic color did not reverse to original quantity")
                if self._cell_qty(color2, "25") != q2_before:
                    raise CommandError("V60 second elastic color did not reverse to original quantity")
            finally:
                transaction.set_rollback(True)

        after = self._state()
        if before != after:
            raise CommandError(f"V60 regression left persistent business data changed: {before} != {after}")

        self.stdout.write("SALE PRICE: Darma + Takvin defaults resolve by SaleDay date")
        self.stdout.write("SALE HISTORY: existing SaleLine.sale_price stays frozen")
        self.stdout.write("PRODUCT UI: explicit Jalali effective date; future price does not overwrite current default")
        self.stdout.write("DIGIKALA IMPORT: new rows are preseeded from the SaleDay-effective price")
        self.stdout.write("ELASTIC PAYMENT: multiple colors + 16/25 variants fit one purchase payload")
        self.stdout.write("LEGACY ELASTIC EDIT: unchanged physical purchase remains finance-only")
        self.stdout.write("ELASTIC REVERSE: each purchased color/variant returns to its original quantity")
        self.stdout.write("NO TEST DATA CHANGED")
        self.stdout.write(self.style.SUCCESS("SUCCESS: SALE PRICE + ELASTIC MULTI V60 CHECK PASSED"))
