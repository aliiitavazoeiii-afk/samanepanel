"""Read-only regression for V98/V99/V100 finance navigation + account visibility."""
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import RequestFactory, override_settings
from django.urls import resolve

from core import business_tools_v91, calculator_v37, finance_center_v97
from core.models import (
    AppSetting,
    ExcelManualRow,
    ExcelManualSetting,
    InventoryMovement,
    RawMaterialStock,
    SaleLine,
    StockBalance,
)
from core.ui_polish_v98 import V98PresentationMiddleware


def _digest(model):
    fields = [field.attname for field in model._meta.concrete_fields]
    h = sha256()
    for row in model.objects.order_by(model._meta.pk.attname).values_list(*fields):
        h.update(repr(tuple(row)).encode("utf-8")); h.update(b"\n")
    return h.hexdigest()


def _state():
    return {
        "raw": _digest(RawMaterialStock),
        "stock": _digest(StockBalance),
        "movement": _digest(InventoryMovement),
        "sales": _digest(SaleLine),
        "settings": _digest(AppSetting),
        "manual_settings": _digest(ExcelManualSetting),
        "manual_rows": _digest(ExcelManualRow),
    }


def _render_through_middleware(view, path):
    request = RequestFactory().get(path)
    request.user = SimpleNamespace(is_authenticated=True)
    static_override = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    with override_settings(STORAGES=static_override):
        response = V98PresentationMiddleware(view)(request)
    if response.status_code != 200:
        raise RuntimeError(f"Render HTTP {response.status_code} for {path}")
    return response, response.content.decode("utf-8", errors="replace")


class Command(BaseCommand):
    help = "Read-only: validate final finance nav and live account-row visibility."

    def handle(self, *args, **kwargs):
        before = _state()

        if resolve("/finance/").func is not finance_center_v97.finance_home:
            raise RuntimeError("Finance hub route changed")
        if resolve("/finance/accounts/").func is not finance_center_v97.accounts:
            raise RuntimeError("Finance accounts route changed")
        if resolve("/payments/").func is not business_tools_v91.payments:
            raise RuntimeError("Payments/receipts route changed")
        if resolve("/calculator/").func is not calculator_v37.calculator:
            raise RuntimeError("Calculator route changed")

        js = (Path(settings.BASE_DIR) / "static/core/number_format.js").read_text(encoding="utf-8")
        for marker in (
            "normalizeFinanceNav",
            "financeLink.href = '/finance/'",
            "oldFinanceGroup.remove()",
            "text-decoration:none!important",
            ".rm97-kpi strong",
            "font-size:1.35rem!important",
        ):
            if marker not in js:
                raise RuntimeError(f"Presentation marker missing: {marker}")

        middleware_path = "core.ui_polish_v98.V98PresentationMiddleware"
        if middleware_path not in settings.MIDDLEWARE:
            raise RuntimeError("Presentation middleware is not enabled")

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

        response, rendered = _render_through_middleware(
            finance_center_v97.finance_home, "/finance/"
        )
        if response.get("X-Darma-Finance-Nav-V100") != "server":
            raise RuntimeError("Server-side finance submenu replacement did not run")
        if 'data-finance-root-nav="server-v100"' not in rendered:
            raise RuntimeError("Direct server-rendered finance link missing")
        if 'erp-nav-group-title">مالی و ابزار' in rendered:
            raise RuntimeError("Legacy Finance & Tools submenu still exists in final HTML")
        if 'href="/finance/"' not in rendered:
            raise RuntimeError("Direct /finance/ href missing from final HTML")
        for marker in ("دریافتی‌ها و پرداختی‌ها", "حساب‌ها", "محاسبه‌گر"):
            if marker not in rendered:
                raise RuntimeError(f"Finance hub card missing: {marker}")
        if 'data-finance-accounts-preview="v100"' not in rendered:
            raise RuntimeError("V100 account preview missing from Finance hub")

        rendered_account_count = rendered.count('data-finance-account-id="')
        rendered_person_count = rendered.count('data-finance-person-id="')
        if rendered_account_count != len(expected_accounts):
            raise RuntimeError(
                f"Finance hub account count mismatch: db={len(expected_accounts)} html={rendered_account_count}"
            )
        if rendered_person_count != len(expected_persons):
            raise RuntimeError(
                f"Finance hub person count mismatch: db={len(expected_persons)} html={rendered_person_count}"
            )
        for row in expected_accounts:
            if f'data-finance-account-id="{row.id}"' not in rendered:
                raise RuntimeError(f"Finance hub missing account row id={row.id} title={row.title!r}")
        for row in expected_persons:
            if f'data-finance-person-id="{row.id}"' not in rendered:
                raise RuntimeError(f"Finance hub missing person row id={row.id} title={row.title!r}")

        accounts_response, accounts_html = _render_through_middleware(
            finance_center_v97.accounts, "/finance/accounts/"
        )
        for row in expected_accounts + expected_persons:
            if f'id="finance-row-{row.id}"' not in accounts_html:
                raise RuntimeError(
                    f"Full Finance/Accounts page missing manual row id={row.id} title={row.title!r}"
                )

        if response.get("Cache-Control") != "no-store, no-cache, must-revalidate, max-age=0":
            raise RuntimeError("V100 no-cache header missing from Finance hub")
        if accounts_response.get("Cache-Control") != "no-store, no-cache, must-revalidate, max-age=0":
            raise RuntimeError("V100 no-cache header missing from Finance/Accounts")
        if '/static/core/number_format.js?v=100' not in rendered:
            raise RuntimeError("V100 cache-busted UI helper missing")

        after = _state()
        if before != after:
            raise RuntimeError("Read-only finance/account regression changed business state")

        self.stdout.write("SERVER-SIDE FINANCE NAV REPLACEMENT = OK")
        self.stdout.write("LEGACY FINANCE SUBMENU ABSENT = OK")
        self.stdout.write("FINANCE HUB 3 CARDS = OK")
        self.stdout.write(f"FINANCE HUB ACCOUNT ROWS = OK ({len(expected_accounts)})")
        self.stdout.write(f"FINANCE HUB PERSON ROWS = OK ({len(expected_persons)})")
        self.stdout.write("FULL FINANCE/ACCOUNTS ROW COVERAGE = OK")
        self.stdout.write("V100 HTML NO-CACHE = OK")
        self.stdout.write("GLOBAL LINK UNDERLINES REMOVED = OK")
        self.stdout.write("RAW MATERIAL KPI NUMBER SIZE = OK")
        self.stdout.write("V100 CACHE-BUSTED UI HELPER = OK")
        self.stdout.write("PAYMENTS / CALCULATOR ROUTES = UNCHANGED")
        self.stdout.write("NO BUSINESS STATE WRITE = OK")
        self.stdout.write(self.style.SUCCESS("SUCCESS: FINANCE ACCOUNTS VISIBLE V100 CHECK PASSED"))
