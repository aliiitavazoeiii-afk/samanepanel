"""Read-only regression for V105 margin semantics, code summaries and material KPIs."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
from pathlib import Path
import re
from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import RequestFactory, override_settings

from core import calculator_v37, material_report_v92
from core.finance import digikala_fee_for_unit
from core.models import (
    AccountEntry,
    AppSetting,
    BusinessPayment,
    DigikalaSettlement,
    ExcelManualRow,
    ExcelManualSetting,
    InventoryMovement,
    MaterialReportBlock,
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
        "account_entries": _digest(AccountEntry),
        "app_settings": _digest(AppSetting),
        "manual_settings": _digest(ExcelManualSetting),
        "manual_rows": _digest(ExcelManualRow),
        "payments": _digest(BusinessPayment),
        "receipts": _digest(DigikalaSettlement),
        "product_codes": _digest(ProductCode),
        "product_sizes": _digest(ProductSize),
        "takvin_cost_rules": _digest(TakvinCostRule),
        "material_blocks": _digest(MaterialReportBlock),
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


def _mean_int(rows, key):
    if not rows:
        return 0
    value = sum(Decimal(int(row[key] or 0)) for row in rows) / Decimal(len(rows))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _mean_decimal(rows, key):
    if not rows:
        return Decimal("0")
    return sum(Decimal(str(row[key] or 0)) for row in rows) / Decimal(len(rows))


def _independent_cut_summary():
    total = 0
    count = 0
    blocks = MaterialReportBlock.objects.select_related("brand").all()
    allowed = set(material_report_v92.v23.BASE_KEYS)
    for block in blocks:
        if block.brand.name != "دارما":
            continue
        data = block.input_data or {}
        for key in allowed:
            values = data.get(key, {}) or {}
            cut = max(0, material_report_v92.v23.v20._int(values.get("cut")))
            if cut <= 0:
                continue
            total += cut
            count += 1
    average = 0
    if count:
        average = int(
            (Decimal(total) / Decimal(count)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
    return {"average_cut": average, "cut_entry_count": count, "cut_total": total}


class Command(BaseCommand):
    help = "Read-only: verify V105 sale-margin pricing, code summaries and material KPIs."

    def handle(self, *args, **kwargs):
        before = _state()

        # 1) The user's concrete case: target percentage is margin on sale price.
        cost = 210_000
        target = Decimal("15")
        exact = calculator_v37._solve_sale_price(cost, target)
        fee = int(digikala_fee_for_unit(exact, date.today()))
        profit = Decimal(exact - fee - cost)
        margin = profit * Decimal(100) / Decimal(exact)

        previous = exact - 1
        previous_fee = int(digikala_fee_for_unit(previous, date.today()))
        previous_profit = Decimal(previous - previous_fee - cost)
        previous_margin = previous_profit * Decimal(100) / Decimal(previous)

        if margin < target:
            raise RuntimeError(
                f"V105 target margin failed: price={exact} margin={margin} target={target}"
            )
        if previous_margin >= target:
            raise RuntimeError(
                f"V105 solver is not minimal: previous={previous} margin={previous_margin}"
            )

        suggested = calculator_v37._rounded_up(exact, 1000)
        suggested_fee = int(digikala_fee_for_unit(suggested, date.today()))
        suggested_profit = Decimal(suggested - suggested_fee - cost)
        suggested_margin = suggested_profit * Decimal(100) / Decimal(suggested)
        if suggested_margin < target:
            raise RuntimeError("Rounded suggested price fell below requested sale margin")

        # 2) Code-first profitability summary must cover every active ProductSize once.
        size_rows = calculator_v37._size_profitability_rows()
        sections = calculator_v37._profitability_sections()
        detail_rows = [
            row
            for section in sections
            for code in section["codes"]
            for row in code["sizes"]
        ]
        if len(detail_rows) != len(size_rows):
            raise RuntimeError(
                f"Grouped detail coverage mismatch: grouped={len(detail_rows)} raw={len(size_rows)}"
            )
        if {row["ps_id"] for row in detail_rows} != {row["ps_id"] for row in size_rows}:
            raise RuntimeError("Grouped detail ProductSize IDs do not match raw profitability rows")

        expected_codes = {
            (row["brand"], row["product_id"])
            for row in size_rows
        }
        actual_codes = {
            (section["brand"], code["product_id"])
            for section in sections
            for code in section["codes"]
        }
        if actual_codes != expected_codes:
            raise RuntimeError("Code summary coverage mismatch")

        for section in sections:
            for code in section["codes"]:
                rows = code["sizes"]
                for key, raw_key in (
                    ("avg_sale_price", "sale_price"),
                    ("avg_finished_cost", "finished_cost"),
                    ("avg_fee", "fee"),
                    ("avg_profit", "profit"),
                ):
                    expected = _mean_int(rows, raw_key)
                    if int(code[key]) != expected:
                        raise RuntimeError(
                            f"Code average mismatch product={code['product_id']} {key}: "
                            f"{code[key]} != {expected}"
                        )
                expected_margin = _mean_decimal(rows, "margin_on_sale")
                expected_cost_ratio = _mean_decimal(rows, "profit_on_cost")
                if abs(Decimal(str(code["avg_margin_on_sale"])) - expected_margin) > Decimal("0.000001"):
                    raise RuntimeError("Average sale margin mismatch")
                if abs(Decimal(str(code["avg_profit_on_cost"])) - expected_cost_ratio) > Decimal("0.000001"):
                    raise RuntimeError("Average profit-on-cost mismatch")

        calculator_response = _render(calculator_v37.calculator, "/calculator/")
        if calculator_response.status_code != 200:
            raise RuntimeError(f"Calculator HTTP {calculator_response.status_code}")
        calculator_html = calculator_response.content.decode("utf-8", errors="replace")
        if "حاشیه سود هدف از قیمت فروش" not in calculator_html:
            raise RuntimeError("Target calculator is not labeled as sale-margin based")
        if "میانگین حاشیه سود / فروش" not in calculator_html:
            raise RuntimeError("Code summary sale-margin column missing")
        if "میانگین سود / بهای تمام‌شده" not in calculator_html:
            raise RuntimeError("Code summary profit-on-cost column missing")
        if calculator_html.index("میانگین حاشیه سود / فروش") > calculator_html.index("میانگین سود / بهای تمام‌شده"):
            raise RuntimeError("Sale-margin column must appear before profit-on-cost")
        if "calc105-detail-row d-none" not in calculator_html:
            raise RuntimeError("Size details are not collapsed by default")

        # 3) Material average cut is all-time, Darma-only, five base colors only.
        objects = list(MaterialReportBlock.objects.select_related("brand").all())
        actual_cut = material_report_v92._all_time_cut_summary(objects)
        expected_cut = _independent_cut_summary()
        if actual_cut != expected_cut:
            raise RuntimeError(f"Material cut summary mismatch: {actual_cut} != {expected_cut}")

        material_response = _render(material_report_v92.material_report, "/material-report/")
        if material_response.status_code != 200:
            raise RuntimeError(f"Material report HTTP {material_response.status_code}")
        material_html = material_response.content.decode("utf-8", errors="replace")
        kpi_cards = re.findall(r'class="material-month-kpi(?:\s[^"]*)?"', material_html)
        if len(kpi_cards) != 6:
            raise RuntimeError(
                f"Material report must render exactly six KPI cards in V105; got {len(kpi_cards)}"
            )
        if 'data-material-kpi="average-cut"' not in material_html:
            raise RuntimeError("Average cut KPI marker missing")
        if "میانگین تعداد برش" not in material_html:
            raise RuntimeError("Average cut KPI label missing")

        template_source = (
            Path(settings.BASE_DIR) / "templates/core/material_report_v92.html"
        ).read_text(encoding="utf-8")
        if "header.insertAdjacentElement('afterend', mount)" not in template_source:
            raise RuntimeError("Material KPIs are not mounted directly below the title/header")
        if "tools.appendChild(tpl.content.cloneNode(true))" in template_source:
            raise RuntimeError("Material KPIs still mount beside the search tools")
        if ".material-month-kpi .kpi-value" not in template_source or ".material-month-kpi .kpi-unit" not in template_source:
            raise RuntimeError("Material KPI number/unit typography split missing")

        after = _state()
        if before != after:
            raise RuntimeError("V105 regression changed business state")

        self.stdout.write(
            f"TARGET SALE MARGIN 15% @ COST 210000 = VERIFIED (exact {exact}, rounded {suggested})"
        )
        self.stdout.write("CODE SUMMARY COVERAGE = VERIFIED")
        self.stdout.write(f"SIZE DETAIL COVERAGE = OK ({len(detail_rows)})")
        self.stdout.write("SALE MARGIN COLUMN = BEFORE PROFIT/COST")
        self.stdout.write("SIZE DETAILS = COLLAPSED BY DEFAULT")
        self.stdout.write(
            f"AVERAGE DARMA CUT = {actual_cut['average_cut']} "
            f"FROM {actual_cut['cut_entry_count']} SAVED BASE-COLOR CUTS"
        )
        self.stdout.write("MATERIAL KPI POSITION = BELOW TITLE")
        self.stdout.write("MATERIAL KPI NUMBER/UNIT TYPOGRAPHY = VERIFIED")
        self.stdout.write("NO BUSINESS STATE WRITE = OK")
        self.stdout.write(self.style.SUCCESS("SUCCESS: MARGIN + MATERIAL KPI V105 CHECK PASSED"))
