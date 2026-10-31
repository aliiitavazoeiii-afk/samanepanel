"""Final baseline regression: lock report, finance, calculator and material UI together."""
from hashlib import sha256
from inspect import getsource
from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import RequestFactory, override_settings
from django.urls import resolve

from core import (
    business_tools_v62,
    calculator_v37,
    finance_center_v97,
    material_report_v92,
    report_v10,
)
from core.capital_history_v87 import current_capital_breakdown
from core.models import (
    AccountEntry,
    AppSetting,
    BusinessPayment,
    DigikalaSettlement,
    ExcelManualRow,
    ExcelManualSetting,
    InventoryMovement,
    MaterialReportBlock,
    MaterialReportOutputApplied,
    ProductCode,
    ProductSize,
    RawMaterialStock,
    SaleLine,
    SaleSnapshot,
    StockBalance,
    TakvinCostRule,
)


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
        "accounts": _digest(AccountEntry),
        "app_settings": _digest(AppSetting),
        "manual_settings": _digest(ExcelManualSetting),
        "manual_rows": _digest(ExcelManualRow),
        "payments": _digest(BusinessPayment),
        "receipts": _digest(DigikalaSettlement),
        "material_blocks": _digest(MaterialReportBlock),
        "material_output": _digest(MaterialReportOutputApplied),
        "product_codes": _digest(ProductCode),
        "product_sizes": _digest(ProductSize),
        "takvin_rules": _digest(TakvinCostRule),
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
    help = "Read-only final baseline regression."

    def handle(self, *args, **kwargs):
        before = _state()

        # Routes are pinned to the final implementations.
        route_expectations = {
            "/report/": report_v10.report,
            "/finance/": finance_center_v97.finance_home,
            "/finance/accounts/": finance_center_v97.accounts,
            "/calculator/": calculator_v37.calculator,
            "/material-report/": material_report_v92.material_report,
        }
        for path, expected in route_expectations.items():
            if resolve(path).func is not expected:
                raise RuntimeError(f"Final baseline route drift: {path}")

        # Comprehensive report: moved account management must be absent in RAW
        # server HTML. No JavaScript cleanup is allowed to be required.
        report_response = _render(report_v10.report, "/report/?period=month")
        if report_response.status_code != 200:
            raise RuntimeError(f"Comprehensive report HTTP {report_response.status_code}")
        report_html = report_response.content.decode("utf-8", errors="replace")
        if 'data-report-finance-moved-server="1"' not in report_html:
            raise RuntimeError("Report server-side moved-finance marker missing")
        forbidden_report = (
            '<div class="subheader">حساب بانک و اشخاص</div>',
            'name="key" value="digikala_receivable"',
            'name="key" value="takvin_debt"',
            "ریز حساب‌ها",
            "حساب اشخاص",
        )
        for marker in forbidden_report:
            if marker in report_html:
                raise RuntimeError(f"Old report account UI returned in server HTML: {marker}")
        if '<h2 class="page-title mb-0">سرمایه</h2>' not in report_html:
            raise RuntimeError("Final report capital heading is not server-rendered as سرمایه")
        if '<h2 class="page-title mb-0">سرمایه، موجودی و حساب‌ها</h2>' in report_html:
            raise RuntimeError("Legacy visible report capital/accounts heading returned")
        if "current_capital_breakdown()" not in getsource(report_v10.report):
            raise RuntimeError("Report stopped using canonical current capital breakdown")

        capital = current_capital_breakdown()
        for key in (
            "accounts_total",
            "inventory_total",
            "digikala_receivable",
            "takvin_debt",
            "capital_total",
        ):
            if key not in capital:
                raise RuntimeError(f"Canonical capital key missing: {key}")

        # Finance hub: six shared balances + exactly three navigation cards.
        finance_response = _render(finance_center_v97.finance_home, "/finance/")
        if finance_response.status_code != 200:
            raise RuntimeError(f"Finance HTTP {finance_response.status_code}")
        finance_html = finance_response.content.decode("utf-8", errors="replace")
        if finance_html.count('data-finance-kpi=') != 6:
            raise RuntimeError("Finance must render exactly six shared KPI balances")
        if finance_html.count('class="finance97-card"') != 3:
            raise RuntimeError("Finance must remain exactly three cards")
        for marker in (
            "دریافتی‌ها و پرداختی‌ها",
            "حساب‌ها",
            "محاسبه‌گر",
            'data-finance-card="payments"',
            'data-finance-card="accounts"',
            'data-finance-card="calculator"',
        ):
            if marker not in finance_html:
                raise RuntimeError(f"Finance final marker missing: {marker}")

        # Every active person account is still a payment target.
        person_choices = dict(business_tools_v62.person_payee_choices())
        persons = list(
            ExcelManualRow.objects.filter(
                active=True,
                section=ExcelManualRow.PERSONS,
            ).order_by("sort_order", "id")
        )
        for row in persons:
            if person_choices.get(business_tools_v62.person_payee_key(row.id)) != row.title:
                raise RuntimeError(f"Person payment choice missing: {row.id} {row.title}")

        # Final V105 calculator must stay present.
        calculator_response = _render(calculator_v37.calculator, "/calculator/")
        if calculator_response.status_code != 200:
            raise RuntimeError(f"Calculator HTTP {calculator_response.status_code}")
        calculator_html = calculator_response.content.decode("utf-8", errors="replace")
        for marker in (
            'data-calculator-box="target"',
            'data-calculator-box="profit"',
            "حاشیه سود هدف از قیمت فروش",
            'data-profitability-brand="دارما"',
            'data-profitability-brand="تکوین"',
            "میانگین حاشیه سود / فروش",
        ):
            if marker not in calculator_html:
                raise RuntimeError(f"Final calculator marker missing: {marker}")
        if "حفظ درصد سود فعلی" in calculator_html:
            raise RuntimeError("Legacy calculator returned")

        # Material: keep six V105 monthly KPIs AND add the five open-work colors.
        objects = list(
            MaterialReportBlock.objects.select_related("brand")
            .prefetch_related("output_applications")
            .all()
        )
        progress = material_report_v92._summarize_open_base_colors(objects)
        expected_keys = list(material_report_v92.v23.BASE_KEYS)
        if [row["key"] for row in progress] != expected_keys:
            raise RuntimeError("Five-color order/coverage drift")

        for row in progress:
            expected = delivered = pending = open_blocks = 0
            for block in objects:
                if getattr(block.brand, "name", "") != "دارما":
                    continue
                cut = max(
                    0,
                    material_report_v92.v23.v20._int(
                        ((block.input_data or {}).get(row["key"]) or {}).get("cut")
                    ),
                )
                applied = sum(
                    max(0, int(item.quantity or 0))
                    for item in block.output_applications.all()
                    if item.model_key == row["key"]
                )
                if cut <= applied:
                    continue
                expected += cut
                delivered += applied
                pending += cut - applied
                open_blocks += 1
            actual = (
                row["expected"], row["delivered"], row["pending"], row["open_blocks"]
            )
            manual = (expected, delivered, pending, open_blocks)
            if actual != manual:
                raise RuntimeError(
                    f"Five-color open-work mismatch {row['key']}: {actual} != {manual}"
                )

        material_response = _render(material_report_v92.material_report, "/material-report/")
        if material_response.status_code != 200:
            raise RuntimeError(f"Material report HTTP {material_response.status_code}")
        material_html = material_response.content.decode("utf-8", errors="replace")
        if material_html.count('class="material-month-kpi') < 6:
            raise RuntimeError("Six established material KPI cards missing")
        if material_html.count('data-base-color=') != 5:
            raise RuntimeError("Five base-color cards must render exactly five times")
        for marker in (
            'data-material-color-progress="final"',
            "باید تحویل شود",
            "تحویل‌شده",
            "مانده",
            "میانگین تعداد برش",
        ):
            if marker not in material_html:
                raise RuntimeError(f"Material final marker missing: {marker}")

        after = _state()
        if before != after:
            raise RuntimeError("Final baseline read-only regression changed business state")

        self.stdout.write("COMPREHENSIVE REPORT OLD 3 ACCOUNT BOXES = ABSENT SERVER-SIDE")
        self.stdout.write("COMPREHENSIVE REPORT CAPITAL SOURCE = CANONICAL")
        self.stdout.write("FINANCE KPI BALANCES = 6")
        self.stdout.write("FINANCE NAV CARDS = EXACTLY 3")
        self.stdout.write(f"PERSON PAYMENT CHOICES = OK ({len(persons)})")
        self.stdout.write("CALCULATOR V105 = RESTORED AND LOCKED")
        self.stdout.write("MATERIAL MONTH KPI CARDS = PRESERVED")
        self.stdout.write("FIVE BASE-COLOR OPEN-WORK CARDS = LOCKED")
        self.stdout.write("NO BUSINESS STATE WRITE = OK")
        self.stdout.write(self.style.SUCCESS(
            "SUCCESS: FINAL STABLE BASELINE V108 CHECK PASSED"
        ))
