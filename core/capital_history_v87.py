"""V87 historical capital resolver.

The canonical capital formula is NOT changed here.  The live/current total is
computed from the exact same components used by report_v10.  For a past
report end-date we walk backward from today's canonical total using dated,
auditable events that actually change capital.

This module deliberately does not fabricate previous values for rows that were
overwritten without a ledger.  Such cases are returned as warnings so the UI
can say the value is ledger-reconstructed rather than pretending it is a
stored historical snapshot.
"""
from datetime import date, timedelta

from django.db.models import Sum

from .business_tools_v60 import _invoice_value
from .darma_cost_v55 import darma_cost_for
from .dia_gallery_v45 import dia_gallery_period_metrics, dia_gallery_receivable_total
from .finance import sale_line_metrics
from .finance_excel_v9 import digikala_receivable_total
from .inventory_valuation_v17 import finished_inventory_value_v17
from .material_purchase_v14 import purchase_data_for_payment
from .models import (
    BusinessPayment,
    ExcelManualRow,
    ExcelManualSetting,
    InventoryAdjustment,
    InventoryModelCost,
    MaterialReportBlock,
    SaleLine,
    TakvinPurchase,
)
from .novani_cost_v59 import novani_cost_for
from .report_v5 import _raw_material_context
from .self_spend_v62 import SELF_PAYEE, capital_accounts_queryset, is_self_tracking_row
from .takvin_pricing_v17 import takvin_cost_for


def current_account_breakdown():
    """Canonical current accounts/persons component used by Finance and capital."""
    manual_rows = ExcelManualRow.objects.filter(active=True)
    person_rows = manual_rows.filter(section=ExcelManualRow.PERSONS)
    capital_accounts = capital_accounts_queryset(
        manual_rows.filter(section=ExcelManualRow.ACCOUNTS)
    )
    dia_receivable = int(dia_gallery_receivable_total() or 0)
    accounts_total = (
        sum(int(row.amount or 0) for row in capital_accounts)
        + sum(int(row.amount or 0) for row in person_rows)
        + dia_receivable
    )
    return {
        "accounts_total": int(accounts_total),
        "dia_gallery_receivable": int(dia_receivable),
    }


def current_capital_breakdown():
    """Return the current canonical report components without changing formulas."""
    manual_rows = ExcelManualRow.objects.filter(active=True)
    asset_rows = manual_rows.filter(section=ExcelManualRow.ASSETS)
    account_breakdown = current_account_breakdown()
    accounts_total = int(account_breakdown["accounts_total"])
    dia_receivable = int(account_breakdown["dia_gallery_receivable"])
    assets_total = sum(int(row.amount or 0) for row in asset_rows)
    finished_total = int(finished_inventory_value_v17() or 0)
    raw = _raw_material_context()
    materials_total = int(raw["materials_total"] or 0)
    digikala_receivable = int(digikala_receivable_total() or 0)
    debt_row = ExcelManualSetting.objects.filter(key="takvin_debt").first()
    takvin_debt = int(debt_row.value or 0) if debt_row else 0
    inventory_total = finished_total + materials_total

    total = (
        accounts_total
        + inventory_total
        + digikala_receivable
        - takvin_debt
        + assets_total
    )
    return {
        "accounts_total": int(accounts_total),
        "assets_total": int(assets_total),
        "finished_inventory_total": int(finished_total),
        "materials_total": int(materials_total),
        "inventory_total": int(inventory_total),
        "digikala_receivable": int(digikala_receivable),
        "takvin_debt": int(takvin_debt),
        "dia_gallery_receivable": int(dia_receivable),
        "capital_total": int(total),
    }


def _regular_sales_profit_after(as_of):
    total = 0
    qs = (
        SaleLine.objects.filter(day__date__gt=as_of, quantity__gt=0)
        .select_related("day", "product_size__product__brand", "product_size__size")
        .prefetch_related("product_size__product__composition__color")
    )
    for line in qs:
        total += int(sale_line_metrics(line)["profit"] or 0)
    return int(total)


def _dia_profit_after(as_of):
    today = date.today()
    if as_of >= today:
        return 0
    return int(dia_gallery_period_metrics(as_of + timedelta(days=1), today)["total"]["profit"] or 0)


def _inventory_adjustment_unit_cost(row):
    brand = row.brand.name
    if brand == "انبارش":
        return 0
    if brand == "دارما":
        return int(darma_cost_for(row.date) or 0)
    if brand == "Novani":
        return int(novani_cost_for(row.date) or 0)
    if brand == "تکوین":
        return int(takvin_cost_for(row.size.name, row.date) or 0)
    cost = (
        InventoryModelCost.objects.filter(
            brand=row.brand, color=row.color, size=row.size
        ).values_list("unit_cost", flat=True).first()
        or 0
    )
    return int(cost)


def _inventory_adjustment_capital_after(as_of):
    total = 0
    rows = InventoryAdjustment.objects.filter(
        date__gt=as_of, applied=True
    ).select_related("brand", "color", "size")
    for row in rows:
        total += int(row.delta or 0) * _inventory_adjustment_unit_cost(row)
    return int(total)


def _material_purchase_capital_after(as_of):
    """Goods value minus actual cash paid; prepayments without goods are neutral."""
    total = 0
    rows = BusinessPayment.objects.filter(
        date__gt=as_of, payee__in=[BusinessPayment.FABRIC, BusinessPayment.ELASTIC]
    )
    for payment in rows:
        data = purchase_data_for_payment(payment)
        if not data:
            continue
        total += int(_invoice_value(data) or 0) - int(payment.amount or 0)
    return int(total)


def _self_spend_after(as_of):
    value = (
        BusinessPayment.objects.filter(date__gt=as_of, payee=SELF_PAYEE)
        .aggregate(v=Sum("amount"))["v"]
        or 0
    )
    return -int(value)


# Legacy Expense rows debit Account.MELAT, while the active report capital
# formula reads ExcelManualRow accounts. They must not be subtracted here.

def _takvin_purchase_capital_after(as_of):
    """Active Excel-style Takvin purchase: stock asset rises, supplier debt rises."""
    total = 0
    rows = TakvinPurchase.objects.filter(
        date__gt=as_of,
        applied=True,
        note__startswith="[excel-web]",
    ).select_related("size")
    for row in rows:
        stock_value = int(row.qty or 0) * int(takvin_cost_for(row.size.name, row.date) or 0)
        total += stock_value - int(row.total_cost or 0)
    return int(total)


def _reconstruction_warnings(as_of):
    warnings = []

    # Direct/manual capital rows have no value history.  System-maintained rows are
    # excluded from this warning because their dated effects are handled above or
    # are capital-neutral.
    changed_manual = []
    for row in ExcelManualRow.objects.filter(active=True, updated_at__date__gt=as_of):
        if is_self_tracking_row(row):
            continue
        normalized = (row.title or "").replace(" ", "").lower()
        if any(token in normalized for token in ("ملت", "مفید", "خیاط")):
            continue
        if str(row.note or "").startswith("ساخته‌شده خودکار از پیش‌پرداخت"):
            continue
        changed_manual.append(row.title or f"row#{row.id}")
    if changed_manual:
        warnings.append(
            "ردیف دستی سرمایه بعد از تاریخ انتخابی overwrite شده و مقدار قبلی ledger ندارد: "
            + "، ".join(changed_manual[:6])
        )

    base = ExcelManualSetting.objects.filter(key="digikala_receivable").first()
    if base and base.updated_at.date() > as_of:
        warnings.append(
            "طلب پایه دیجی‌کالا بعد از تاریخ انتخابی ویرایش شده؛ مقدار قبلی آن ذخیره نشده است."
        )

    # Material reports move value between raw materials, tailor balance and finished
    # goods. Old rows do not freeze every raw-material price component, therefore we
    # do not invent an exact delta for past reports.
    material_activity = MaterialReportBlock.objects.filter(
        date__gt=as_of
    ).filter(
        stock_consumptions__quantity__gt=0
    ).exists() or MaterialReportBlock.objects.filter(
        date__gt=as_of,
        output_applications__quantity__gt=0,
    ).exists()
    if material_activity:
        warnings.append(
            "بعد از تاریخ انتخابی صورت مواد/تولید اعمال‌شده وجود دارد؛ قیمت تاریخی تمام اجزای مواد در نسخه‌های قدیمی freeze نشده است."
        )

    return warnings


def capital_as_of(as_of):
    """Resolve capital at end-of-day *as_of* without changing the capital formula."""
    current = current_capital_breakdown()
    today = date.today()
    if as_of >= today:
        return {
            **current,
            "as_of": today,
            "is_historical": False,
            "source": "current",
            "warnings": [],
            "post_period_delta": 0,
        }

    parts = {
        "sales_profit": _regular_sales_profit_after(as_of),
        "dia_profit": _dia_profit_after(as_of),
        "self_spend": _self_spend_after(as_of),
        "material_purchase_difference": _material_purchase_capital_after(as_of),
        "inventory_adjustment": _inventory_adjustment_capital_after(as_of),
        "takvin_purchase_difference": _takvin_purchase_capital_after(as_of),
    }
    post_period_delta = sum(int(value or 0) for value in parts.values())
    warnings = _reconstruction_warnings(as_of)
    return {
        **current,
        "capital_total": int(current["capital_total"] - post_period_delta),
        "as_of": as_of,
        "is_historical": True,
        "source": "ledger-reconstruction",
        "warnings": warnings,
        "post_period_delta": int(post_period_delta),
        "delta_parts": parts,
    }
