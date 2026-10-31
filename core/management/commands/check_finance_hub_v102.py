"""Read-only regression for V102 consolidated Finance hub and canonical capital."""
from hashlib import sha256
from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import RequestFactory, override_settings
from django.urls import resolve

from core import business_tools_v91, calculator_v37, finance_center_v97, report_v10
from core.capital_history_v87 import current_capital_breakdown
from core.dia_gallery_v45 import dia_gallery_receivable_total
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import (
    AccountEntry,
    AppSetting,
    BusinessPayment,
    DigikalaSettlement,
    ExcelManualRow,
    ExcelManualSetting,
    InventoryMovement,
    RawMaterialStock,
    SaleLine,
    SaleSnapshot,
    StockBalance,
)
from core.report_v5 import _raw_material_context
from core.self_spend_v62 import capital_accounts_queryset
from core.ui_polish_v98 import V98PresentationMiddleware


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
        "settings": _digest(AppSetting),
        "manual_settings": _digest(ExcelManualSetting),
        "manual_rows": _digest(ExcelManualRow),
        "payments": _digest(BusinessPayment),
        "receipts": _digest(DigikalaSettlement),
    }


def _render(view, path):
    req = RequestFactory().get(path)
    req.user = SimpleNamespace(is_authenticated=True)
    storage = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    with override_settings(STORAGES=storage):
        return V98PresentationMiddleware(view)(req)


def _independent_capital():
    manual = ExcelManualRow.objects.filter(active=True)
    account_rows = capital_accounts_queryset(
        manual.filter(section=ExcelManualRow.ACCOUNTS)
    )
    person_rows = manual.filter(section=ExcelManualRow.PERSONS)
    asset_rows = manual.filter(section=ExcelManualRow.ASSETS)

    dia = int(dia_gallery_receivable_total() or 0)
    accounts = (
        sum(int(row.amount or 0) for row in account_rows)
        + sum(int(row.amount or 0) for row in person_rows)
        + dia
    )
    assets = sum(int(row.amount or 0) for row in asset_rows)
    finished = int(finished_inventory_value_v17() or 0)
    materials = int(_raw_material_context()["materials_total"] or 0)
    inventory = finished + materials
    digi = int(digikala_receivable_total() or 0)
    debt = ExcelManualSetting.objects.filter(key="takvin_debt").first()
    takvin_debt = int(debt.value or 0) if debt else 0
    total = accounts + inventory + digi - takvin_debt + assets

    return {
        "accounts_total": accounts,
        "assets_total": assets,
        "finished_inventory_total": finished,
        "materials_total": materials,
        "inventory_total": inventory,
        "digikala_receivable": digi,
        "takvin_debt": takvin_debt,
        "dia_gallery_receivable": dia,
        "capital_total": total,
    }


class Command(BaseCommand):
    help = "Read-only: verify V102 Finance hub and canonical current-capital invariants."

    def handle(self, *args, **kwargs):
        before = _state()

        if resolve("/finance/").func != finance_center_v97.finance_home:
            raise RuntimeError("/finance/ is not routed to the Finance hub")
        if resolve("/finance/accounts/").func != finance_center_v97.accounts:
            raise RuntimeError("/finance/accounts/ is not routed to Accounts")
        if resolve("/payments/").func != business_tools_v91.payments:
            raise RuntimeError("Payments route changed unexpectedly")
        if resolve("/calculator/").func != calculator_v37.calculator:
            raise RuntimeError("Calculator route changed unexpectedly")
        if resolve("/report/").func != report_v10.report:
            raise RuntimeError("Comprehensive report route changed unexpectedly")

        hub_response = _render(finance_center_v97.finance_home, "/finance/")
        if hub_response.status_code != 200:
            raise RuntimeError(f"Finance hub HTTP {hub_response.status_code}")
        hub = hub_response.content.decode("utf-8", errors="replace")

        if 'data-finance-hub="v102"' not in hub:
            raise RuntimeError("V102 Finance hub marker missing")
        if hub.count('class="finance97-card"') != 3:
            raise RuntimeError("Finance hub must contain exactly three cards")
        for marker in (
            'data-finance-card="payments"',
            'data-finance-card="accounts"',
            'data-finance-card="calculator"',
        ):
            if marker not in hub:
                raise RuntimeError(f"Finance card missing: {marker}")
        if 'data-finance-accounts-preview=' in hub or 'finance100-accounts' in hub:
            raise RuntimeError("Account preview must not be rendered on the Finance hub")
        if 'data-finance-root-nav="base-v103"' not in hub:
            raise RuntimeError("Native direct Finance navigation missing from rendered HTML")
        if '<span class="erp-nav-group-title">مالی و ابزار</span>' in hub:
            raise RuntimeError("Finance & Tools must not remain an expandable sidebar group")
        if '/static/core/number_format.js?v=103' not in hub:
            raise RuntimeError("V103 cache-busted presentation helper missing")
        if hub_response.get("Cache-Control") != "no-store, no-cache, must-revalidate, max-age=0":
            raise RuntimeError("V102 Finance hub no-cache header missing")

        accounts_response = _render(finance_center_v97.accounts, "/finance/accounts/")
        if accounts_response.status_code != 200:
            raise RuntimeError(f"Finance accounts HTTP {accounts_response.status_code}")
        accounts_html = accounts_response.content.decode("utf-8", errors="replace")
        expected_accounts = list(
            ExcelManualRow.objects.filter(
                active=True, section=ExcelManualRow.ACCOUNTS
            ).order_by("sort_order", "id")
        )
        expected_persons = list(
            ExcelManualRow.objects.filter(
                active=True, section=ExcelManualRow.PERSONS
            ).order_by("sort_order", "id")
        )
        for row in expected_accounts + expected_persons:
            if f'id="finance-row-{row.id}"' not in accounts_html:
                raise RuntimeError(
                    f"Finance/Accounts missing row id={row.id} title={row.title!r}"
                )

        report_response = _render(report_v10.report, "/report/?period=today")
        if report_response.status_code != 200:
            raise RuntimeError(f"Comprehensive Report HTTP {report_response.status_code}")
        report_html = report_response.content.decode("utf-8", errors="replace")
        if 'data-report-accounts-moved="1"' not in report_html:
            raise RuntimeError("Comprehensive Report account-move marker missing")
        if 'id="section-accounts"' in report_html:
            raise RuntimeError("Comprehensive Report still server-renders account rows")
        if 'name="key" value="digikala_receivable"' in report_html:
            raise RuntimeError("Comprehensive Report still renders editable Digikala account form")
        if 'name="key" value="takvin_debt"' in report_html:
            raise RuntimeError("Comprehensive Report still renders editable Takvin debt form")

        canonical = current_capital_breakdown()
        expected = _independent_capital()
        for key, value in expected.items():
            if int(canonical.get(key, 0)) != int(value):
                raise RuntimeError(
                    f"Canonical capital mismatch for {key}: "
                    f"canonical={canonical.get(key)} expected={value}"
                )

        formula_total = (
            int(canonical["accounts_total"])
            + int(canonical["inventory_total"])
            + int(canonical["digikala_receivable"])
            - int(canonical["takvin_debt"])
            + int(canonical["assets_total"])
        )
        if formula_total != int(canonical["capital_total"]):
            raise RuntimeError("Canonical capital formula invariant failed")

        after = _state()
        if before != after:
            raise RuntimeError("V102 read-only regression changed business state")

        self.stdout.write("FINANCE HUB = EXACTLY 3 CARDS")
        self.stdout.write("FINANCE SIDEBAR = NATIVE DIRECT ROOT LINK")
        self.stdout.write(f"ACCOUNT ROW COVERAGE = OK ({len(expected_accounts)})")
        self.stdout.write(f"PERSON ROW COVERAGE = OK ({len(expected_persons)})")
        self.stdout.write("COMPREHENSIVE REPORT ACCOUNT MANAGEMENT = REMOVED")
        self.stdout.write("PAYMENTS = UNCHANGED ROUTE")
        self.stdout.write("CALCULATOR = UNCHANGED ROUTE")
        self.stdout.write("CURRENT CAPITAL COMPONENTS = CANONICAL")
        self.stdout.write("CURRENT CAPITAL FORMULA = VERIFIED")
        self.stdout.write("NO BUSINESS STATE WRITE = OK")
        self.stdout.write(self.style.SUCCESS("SUCCESS: FINANCE HUB + CAPITAL V102 CHECK PASSED"))
