"""Read-only regression for V104 Finance KPIs and rebuilt calculator."""
from datetime import date
from decimal import Decimal
from hashlib import sha256
from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import RequestFactory, override_settings
from django.urls import resolve

from core import business_tools_v91, calculator_v37, finance_center_v97
from core.darma_cost_v55 import darma_cost_for
from core.finance import digikala_fee_for_unit
from core.finance_overview_v104 import finance_kpis
from core.models import (
    AccountEntry,
    AppSetting,
    BusinessPayment,
    DigikalaSettlement,
    ExcelManualRow,
    ExcelManualSetting,
    InventoryMovement,
    ProductCode,
    ProductSize,
    RawMaterialStock,
    SaleLine,
    SaleSnapshot,
    StockBalance,
    TakvinCostRule,
)
from core.sale_price_v60 import sale_price_for
from core.takvin_pricing_v17 import takvin_cost_for


def _digest(model):
    fields = [field.attname for field in model._meta.concrete_fields]
    h = sha256()
    for row in model.objects.order_by(model._meta.pk.attname).values_list(*fields):
        h.update(repr(tuple(row)).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def _state():
    return {
        "raw": _digest(RawMaterialStock),
        "stock": _digest(StockBalance),
        "movement": _digest(InventoryMovement),
        "sales": _digest(SaleLine),
        "snapshots": _digest(SaleSnapshot),
        "account_entries": _digest(AccountEntry),
        "app_settings": _digest(AppSetting),
        "manual_settings": _digest(ExcelManualSetting),
        "manual_rows": _digest(ExcelManualRow),
        "payments": _digest(BusinessPayment),
        "receipts": _digest(DigikalaSettlement),
        "product_codes": _digest(ProductCode),
        "product_sizes": _digest(ProductSize),
        "takvin_cost_rules": _digest(TakvinCostRule),
    }


def _request(path):
    req = RequestFactory().get(path)
    req.user = SimpleNamespace(is_authenticated=True)
    return req


def _render(view, path):
    storage = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    with override_settings(STORAGES=storage):
        return view(_request(path))


class Command(BaseCommand):
    help = "Read-only: verify V104 Finance KPIs and calculator profitability math."

    def handle(self, *args, **kwargs):
        before = _state()

        if resolve("/finance/").func is not finance_center_v97.finance_home:
            raise RuntimeError("Finance route changed")
        if resolve("/payments/").func is not business_tools_v91.payments:
            raise RuntimeError("Payments route changed")
        if resolve("/calculator/").func is not calculator_v37.calculator:
            raise RuntimeError("Calculator route changed")
        if resolve("/calculator/quote/").func is not calculator_v37.calculator_quote:
            raise RuntimeError("Calculator quote route changed")
        if resolve("/calculator/target-quote/").func is not calculator_v37.calculator_target_quote:
            raise RuntimeError("Calculator target route changed")

        kpis = finance_kpis()
        expected_kpi_keys = {
            "mellat_balance",
            "mofid_balance",
            "digikala_receivable",
            "dia_gallery_receivable",
            "tailor_balance",
            "takvin_debt",
        }
        if set(kpis) != expected_kpi_keys:
            raise RuntimeError(f"Finance KPI keys mismatch: {set(kpis)}")

        finance_response = _render(finance_center_v97.finance_home, "/finance/")
        if finance_response.status_code != 200:
            raise RuntimeError(f"Finance hub HTTP {finance_response.status_code}")
        finance_html = finance_response.content.decode("utf-8", errors="replace")
        if finance_html.count('data-finance-kpi=') != 6:
            raise RuntimeError("Finance hub must render exactly six KPI cards")
        if finance_html.count('class="finance97-card"') != 3:
            raise RuntimeError("Finance hub must still render exactly three navigation cards")
        for marker in (
            'data-finance-kpi="mellat"',
            'data-finance-kpi="mofid"',
            'data-finance-kpi="digikala"',
            'data-finance-kpi="dia"',
            'data-finance-kpi="tailor"',
            'data-finance-kpi="takvin"',
        ):
            if marker not in finance_html:
                raise RuntimeError(f"Finance KPI missing: {marker}")

        payments_response = _render(business_tools_v91.payments, "/payments/")
        if payments_response.status_code != 200:
            raise RuntimeError(f"Payments HTTP {payments_response.status_code}")
        payments_html = payments_response.content.decode("utf-8", errors="replace")
        if payments_html.count('data-finance-kpi=') != 6:
            raise RuntimeError("Payments must render the same six KPI cards")
        if 'data-finance-kpis="v104"' not in finance_html or 'data-finance-kpis="v104"' not in payments_html:
            raise RuntimeError("Finance/Payments do not share the V104 KPI partial")

        accounts_response = _render(finance_center_v97.accounts, "/finance/accounts/")
        accounts_html = accounts_response.content.decode("utf-8", errors="replace")
        for marker in ('data-account-summary="accounts"', 'data-account-summary="dia"', "fa97-value"):
            if marker not in accounts_html:
                raise RuntimeError(f"Accounts KPI presentation marker missing: {marker}")

        calculator_response = _render(calculator_v37.calculator, "/calculator/")
        if calculator_response.status_code != 200:
            raise RuntimeError(f"Calculator HTTP {calculator_response.status_code}")
        calculator_html = calculator_response.content.decode("utf-8", errors="replace")
        for marker in (
            'data-calculator-box="target"',
            'data-calculator-box="profit"',
            'data-profitability-brand="دارما"',
            'data-profitability-brand="تکوین"',
        ):
            if marker not in calculator_html:
                raise RuntimeError(f"Calculator marker missing: {marker}")
        if "حفظ درصد سود فعلی" in calculator_html:
            raise RuntimeError("Legacy brand-current-profit calculator still visible")

        # V105 semantics: target is net profit / sale price, not profit / cost.
        test_cost = 210_000
        test_pct = Decimal("15")
        exact = calculator_v37._solve_sale_price(test_cost, test_pct)
        achieved_profit = Decimal(exact - digikala_fee_for_unit(exact, date.today()) - test_cost)
        previous_price = exact - 1
        previous_profit = Decimal(previous_price - digikala_fee_for_unit(previous_price, date.today()) - test_cost)
        achieved_margin = achieved_profit * Decimal(100) / Decimal(exact)
        previous_margin = previous_profit * Decimal(100) / Decimal(previous_price)
        if achieved_margin < test_pct or previous_margin >= test_pct:
            raise RuntimeError("Sale-margin target solver is not minimal/exact")

        actual_rows = calculator_v37._size_profitability_rows()
        expected_sizes = list(
            ProductSize.objects.filter(
                product__brand__name__in=calculator_v37.TARGET_BRANDS,
                product__active=True,
                active=True,
            )
            .select_related("product__brand", "product", "size")
            .order_by("product__brand__name", "product__code", "size__sort_order", "id")
        )
        if len(actual_rows) != len(expected_sizes):
            raise RuntimeError(
                f"Profitability coverage mismatch: rows={len(actual_rows)} expected={len(expected_sizes)}"
            )

        by_id = {int(row["ps_id"]): row for row in actual_rows}
        today = date.today()
        for ps in expected_sizes:
            row = by_id.get(ps.id)
            if row is None:
                raise RuntimeError(f"Missing profitability row for ProductSize {ps.id}")
            expected_price = int(sale_price_for(ps, today) or 0)
            expected_unit_cost = (
                int(darma_cost_for(today) or 0)
                if ps.product.brand.name == "دارما"
                else int(takvin_cost_for(ps.size.name, today) or 0)
            )
            expected_cost = int(ps.product.pack_qty or 0) * expected_unit_cost
            expected_fee = int(digikala_fee_for_unit(expected_price, today)) if expected_price > 0 else 0
            expected_profit = expected_price - expected_fee - expected_cost if expected_price > 0 else 0
            for key, expected in (
                ("sale_price", expected_price),
                ("unit_cost", expected_unit_cost),
                ("finished_cost", expected_cost),
                ("fee", expected_fee),
                ("profit", expected_profit),
            ):
                if int(row[key]) != int(expected):
                    raise RuntimeError(
                        f"Profitability mismatch ps={ps.id} key={key}: row={row[key]} expected={expected}"
                    )

        after = _state()
        if before != after:
            raise RuntimeError("V104 read-only regression changed business state")

        self.stdout.write("FINANCE KPI SOURCE = SHARED")
        self.stdout.write("FINANCE HUB KPI CARDS = 6")
        self.stdout.write("PAYMENTS KPI CARDS = SAME 6")
        self.stdout.write("FINANCE NAV CARDS = STILL 3")
        self.stdout.write("ACCOUNT SUMMARY TYPOGRAPHY = V104")
        self.stdout.write("CALCULATOR LEGACY STRUCTURE = REMOVED")
        self.stdout.write("TARGET SALE-MARGIN SOLVER = VERIFIED")
        self.stdout.write(f"PRODUCT PROFITABILITY COVERAGE = OK ({len(actual_rows)})")
        self.stdout.write("PRODUCT PRICE/COST/FEE/PROFIT = VERIFIED")
        self.stdout.write("NO BUSINESS STATE WRITE = OK")
        self.stdout.write(self.style.SUCCESS("SUCCESS: FINANCE KPI + CALCULATOR V104 CHECK PASSED"))
