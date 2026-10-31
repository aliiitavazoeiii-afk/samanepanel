"""Read-only regression for V103 native Finance navigation."""
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import RequestFactory, override_settings
from django.urls import resolve

from core import finance_center_v97
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
        "app_settings": _digest(AppSetting),
        "manual_settings": _digest(ExcelManualSetting),
        "manual_rows": _digest(ExcelManualRow),
        "payments": _digest(BusinessPayment),
        "receipts": _digest(DigikalaSettlement),
    }


def _request(path):
    req = RequestFactory().get(path)
    req.user = SimpleNamespace(is_authenticated=True)
    return req


def _render_direct(view, path):
    storage = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    with override_settings(STORAGES=storage):
        return view(_request(path))


class Command(BaseCommand):
    help = "Read-only: prove Finance navigation is native in base.html and Accounts is reachable."

    def handle(self, *args, **kwargs):
        before = _state()

        if resolve("/finance/").func is not finance_center_v97.finance_home:
            raise RuntimeError("/finance/ route mismatch")
        if resolve("/finance/accounts/").func is not finance_center_v97.accounts:
            raise RuntimeError("/finance/accounts/ route mismatch")

        base_path = Path(settings.BASE_DIR) / "templates/base.html"
        base = base_path.read_text(encoding="utf-8")
        if 'data-finance-root-nav="base-v103"' not in base:
            raise RuntimeError("base.html does not contain native V103 Finance link")
        if '<span class="erp-nav-group-title">مالی و ابزار</span>' in base:
            raise RuntimeError("base.html still contains expandable Finance group")
        if "href=\"{% url 'finance' %}\"" not in base:
            raise RuntimeError("base.html native Finance link does not target named finance route")
        if "{% static 'core/number_format.js' %}?v=103" not in base:
            raise RuntimeError("base.html does not cache-bust number_format.js at V103")

        hub_response = _render_direct(finance_center_v97.finance_home, "/finance/")
        if hub_response.status_code != 200:
            raise RuntimeError(f"Direct Finance render HTTP {hub_response.status_code}")
        hub = hub_response.content.decode("utf-8", errors="replace")
        if 'data-finance-root-nav="base-v103"' not in hub:
            raise RuntimeError("Native Finance root link missing before middleware")
        if '<span class="erp-nav-group-title">مالی و ابزار</span>' in hub:
            raise RuntimeError("Expandable Finance group survived direct render")
        if 'data-finance-hub="v102"' not in hub:
            raise RuntimeError("Three-card Finance hub marker missing")
        if hub.count('class="finance97-card"') != 3:
            raise RuntimeError("Finance hub is not exactly three cards")
        for marker in (
            'data-finance-card="payments"',
            'data-finance-card="accounts"',
            'data-finance-card="calculator"',
            'href="/finance/accounts/"',
        ):
            if marker not in hub:
                raise RuntimeError(f"Finance hub marker missing: {marker}")

        # Then pass the already-correct HTML through the real presentation
        # middleware class and prove the middleware does not need to rewrite nav.
        storage = {
            **settings.STORAGES,
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }
        with override_settings(STORAGES=storage):
            wrapped = V98PresentationMiddleware(finance_center_v97.finance_home)(_request("/finance/"))
        wrapped_html = wrapped.content.decode("utf-8", errors="replace")
        if 'data-finance-root-nav="base-v103"' not in wrapped_html:
            raise RuntimeError("Middleware removed native Finance nav")
        if wrapped.get("X-Darma-Finance-Nav-V103") != "native":
            raise RuntimeError("Middleware did not recognize native Finance nav")

        accounts_response = _render_direct(finance_center_v97.accounts, "/finance/accounts/")
        if accounts_response.status_code != 200:
            raise RuntimeError(f"Accounts render HTTP {accounts_response.status_code}")
        accounts = accounts_response.content.decode("utf-8", errors="replace")
        expected = list(
            ExcelManualRow.objects.filter(
                active=True,
                section__in=[ExcelManualRow.ACCOUNTS, ExcelManualRow.PERSONS],
            ).order_by("section", "sort_order", "id")
        )
        for row in expected:
            if f'id="finance-row-{row.id}"' not in accounts:
                raise RuntimeError(f"Accounts page missing row {row.id}: {row.title}")

        js = (Path(settings.BASE_DIR) / "static/core/number_format.js").read_text(encoding="utf-8")
        if "base.html owns the Finance navigation" not in js:
            raise RuntimeError("number_format.js is not in V103 native-nav mode")
        if "financeLink = document.createElement('a')" in js:
            raise RuntimeError("JavaScript still constructs Finance navigation")

        after = _state()
        if before != after:
            raise RuntimeError("V103 regression changed business state")

        self.stdout.write("BASE FINANCE NAV = NATIVE DIRECT LINK")
        self.stdout.write("LEGACY FINANCE SUBMENU = ABSENT")
        self.stdout.write("FINANCE HUB = EXACTLY 3 CARDS")
        self.stdout.write("ACCOUNTS CARD -> /finance/accounts/ = OK")
        self.stdout.write(f"ACCOUNT/PERSON ROW COVERAGE = OK ({len(expected)})")
        self.stdout.write("MIDDLEWARE NAV REWRITE = NOT REQUIRED")
        self.stdout.write("JAVASCRIPT NAV CONSTRUCTION = DISABLED")
        self.stdout.write("NO BUSINESS STATE WRITE = OK")
        self.stdout.write(self.style.SUCCESS("SUCCESS: NATIVE FINANCE NAV V103 CHECK PASSED"))
