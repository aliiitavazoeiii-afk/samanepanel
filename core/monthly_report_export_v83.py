"""Read-only Excel export of the selected Jalali report period.

Period transactions are date-filtered. V87 resolves the headline capital at the
selected end date from dated ledgers. Detailed account/inventory sheets remain
explicitly current where old versions did not preserve complete historical values.
"""
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from io import BytesIO

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.utils import timezone

from .capital_history_v87 import capital_as_of
from .dateutils import format_jalali
from .dia_gallery_v45 import dia_gallery_period_metrics, dia_gallery_receivable_total
from .excel_views import DISPLAY_SIZES, _period_range
from .finance import sale_line_metrics
from .finance_excel_v9 import digikala_receivable_total
from .inventory_valuation_v17 import finished_inventory_value_v17
from .monthly_xlsx_v83 import Sheet, make_workbook
from .models import (
    BusinessPayment, ExcelManualRow, ExcelManualSetting, Expense,
    InventoryMovement, MaterialReportBlock, MaterialReportConsumption,
    MaterialReportOutputApplied, RawMaterialStock, SaleLine, StockBalance,
)
from .report_v5 import _raw_material_context
from .self_spend_v62 import capital_accounts_queryset


METRIC_KEYS = ("packs", "shorts", "gross", "digikala_fee", "cogs", "profit")


def _zero():
    return {key: 0 for key in METRIC_KEYS}


def _add(target, metric):
    for key in METRIC_KEYS:
        target[key] += int(metric[key] or 0)


def _percent(value):
    gross = int(value["gross"] or 0)
    return round(value["profit"] * 100 / gross, 2) if gross else 0


def _metrics_row(metric):
    return [
        int(metric["packs"]), int(metric["shorts"]), int(metric["gross"]),
        int(metric["digikala_fee"]), int(metric["cogs"]), int(metric["profit"]),
        _percent(metric),
    ]


def _label_date(value):
    return format_jalali(value) if value else ""


def _period_data(start, end):
    lines = list(
        SaleLine.objects.filter(
            day__date__gte=start, day__date__lte=end, quantity__gt=0
        ).select_related(
            "day", "product_size__product__brand", "product_size__size"
        ).prefetch_related(
            "allocations__color", "product_size__product__composition__color"
        ).order_by("day__date", "id")
    )
    dia = dia_gallery_period_metrics(start, end)
    daily = defaultdict(_zero)
    daily_brand = defaultdict(_zero)
    brands = defaultdict(_zero)
    brand_sizes = defaultdict(_zero)
    products = defaultdict(_zero)
    color_sizes = defaultdict(int)
    sale_rows = []
    for line in lines:
        p = line.product_size.product
        brand = p.brand.name
        size = line.product_size.size.name
        m = sale_line_metrics(line)
        d = line.day.date
        for aggregate in (daily[d], daily_brand[(d, brand)], brands[brand],
                          brand_sizes[(brand, size)], products[(brand, p.code, size)]):
            _add(aggregate, m)
        sale_rows.append([
            _label_date(d), brand, p.code, size, int(line.quantity or 0),
            int(m["shorts"]), int(line.sale_price or 0), int(m["gross"]),
            int(m["digikala_fee"]), int(m["cogs"]), int(m["profit"]), _percent(m),
            int(line.id),
        ])
        if brand == "دارما":
            allocations = list(line.allocations.all())
            if allocations:
                for allocation in allocations:
                    color_sizes[(allocation.color.name, size)] += int(allocation.qty or 0)
            else:
                for comp in p.composition.all():
                    color_sizes[(comp.color.name, size)] += (
                        int(comp.qty or 0) * int(line.quantity or 0)
                    )

    for row in dia["rows"]:
        line = row["line"]
        d = row["date"]
        m = {key: int(row.get(key) or 0) for key in METRIC_KEYS}
        for aggregate in (daily[d], daily_brand[(d, "Dia Gallery")],
                          brands["Dia Gallery"],
                          brand_sizes[("Dia Gallery", row["size"])],
                          products[("Dia Gallery", row["color"], row["size"])]):
            _add(aggregate, m)
        color_sizes[(row["color"], row["size"])] += int(row["quantity"])
        sale_rows.append([
            _label_date(d), "Dia Gallery", row["color"], row["size"],
            int(row["quantity"]), int(row["quantity"]), int(line.unit_price or 0),
            int(row["gross"]), 0, int(row["cogs"]), int(row["profit"]),
            _percent(m), f"dia:{line.id}",
        ])

    sale_rows.sort(key=lambda row: (row[0], row[1], row[2], row[3]))
    return {
        "lines": lines, "dia": dia, "daily": daily, "daily_brand": daily_brand,
        "brands": brands, "brand_sizes": brand_sizes, "products": products,
        "colors": color_sizes, "sale_rows": sale_rows,
    }


def _daily_sheets(data):
    day_headers = [
        "تاریخ شمسی", "برند", "تعداد پک / سفارش", "تعداد شورت",
        "فروش ناخالص (تومان)", "کارمزد (تومان)", "بهای کالا (تومان)",
        "سود ناخالص (تومان)", "حاشیه سود ٪",
    ]
    days = sorted(data["daily"])
    day_rows = []
    for day in days:
        key_rows = sorted(
            (brand, metric) for (when, brand), metric in data["daily_brand"].items()
            if when == day
        )
        for brand, metric in key_rows:
            day_rows.append([_label_date(day), brand, *_metrics_row(metric)])
        day_rows.append([_label_date(day), "جمع روز", *_metrics_row(data["daily"][day])])
    return Sheet(
        "فروش روزانه", day_headers, day_rows,
        widths=(17, 20, 18, 16, 24, 21, 25, 25, 15),
        money_columns=(5, 6, 7, 8), percent_columns=(9,),
    )


def _snapshot_sheets(start, end, data, exported_at):
    total = _zero()
    for metric in data["brands"].values():
        _add(total, metric)

    expense_total = sum(int(x or 0) for x in Expense.objects.filter(
        date__gte=start, date__lte=end
    ).values_list("amount", flat=True))
    raw = _raw_material_context()
    finished_total = int(finished_inventory_value_v17())
    materials_total = int(raw["materials_total"] or 0)
    digikala_receivable = int(digikala_receivable_total() or 0)
    dia_receivable = int(dia_gallery_receivable_total() or 0)

    account_rows = list(
        ExcelManualRow.objects.filter(active=True).order_by("section", "sort_order", "id")
    )
    capital_account_ids = {
        item.id for item in capital_accounts_queryset(
            ExcelManualRow.objects.filter(section=ExcelManualRow.ACCOUNTS, active=True)
        )
    }
    accounts_total = (
        sum(int(r.amount or 0) for r in account_rows
            if r.id in capital_account_ids or r.section == ExcelManualRow.PERSONS)
        + dia_receivable
    )
    assets_total = sum(
        int(r.amount or 0) for r in account_rows if r.section == ExcelManualRow.ASSETS
    )
    debt_row = ExcelManualSetting.objects.filter(key="takvin_debt").first()
    takvin_debt = int(debt_row.value or 0) if debt_row else 0
    current_capital_total = (
        accounts_total + finished_total + materials_total
        + digikala_receivable - takvin_debt + assets_total
    )
    historical_capital = capital_as_of(end)
    period_capital_total = int(historical_capital["capital_total"])

    label = f"{_label_date(start)} تا {_label_date(end)}"
    asof = timezone.localtime(exported_at).strftime("%Y-%m-%d %H:%M %Z")
    summary = [
        ["دوره گزارش", label],
        ["زمان تهیه فایل", asof],
        ["توضیح مهم", "فروش و هزینه‌ها مربوط به بازه انتخابی‌اند؛ سرمایه کل برای پایان بازه محاسبه می‌شود. ریز حساب‌ها و موجودی‌های فاقد تاریخچه کامل، همچنان مانده فعلی‌اند."],
        ["جمع فروش ماه", total["gross"]],
        ["جمع کارمزد ماه", total["digikala_fee"]],
        ["بهای کالای فروش‌رفته ماه", total["cogs"]],
        ["سود ناخالص ماه", total["profit"]],
        ["هزینه‌های ثبت‌شده ماه", expense_total],
        ["سود پس از هزینه‌های ثبت‌شده", total["profit"] - expense_total],
        ["تعداد پک / سفارش ماه", total["packs"]],
        ["تعداد شورت ماه", total["shorts"]],
        ["حاشیه سود ناخالص ٪", _percent(total)],
        ["", ""],
        ["حساب‌ها و اشخاص - فعلی", accounts_total],
        ["کالای آماده - فعلی", finished_total],
        ["مواد اولیه - فعلی", materials_total],
        ["طلب دیجی‌کالا - فعلی", digikala_receivable],
        ["بدهی تکوین - فعلی", takvin_debt],
        ["کالای سرمایه‌ای - فعلی", assets_total],
        ["سرمایه کل - پایان بازه", period_capital_total],
        ["سرمایه کل - فعلی", current_capital_total],
        ["طلب Dia Gallery در جمع حساب‌ها لحاظ شده", dia_receivable],
    ]
    if historical_capital.get("warnings"):
        summary.append(["هشدار بازسازی سرمایه", " | ".join(historical_capital["warnings"])])


    account_sheet = []
    section_names = {
        ExcelManualRow.ACCOUNTS: "حساب‌ها",
        ExcelManualRow.PERSONS: "اشخاص",
        ExcelManualRow.ASSETS: "دارایی سرمایه‌ای",
    }
    for row in account_rows:
        if row.section not in section_names:
            continue
        account_sheet.append([
            section_names[row.section], row.title, int(row.amount or 0),
            row.note or "", "خیر" if (
                row.section == ExcelManualRow.ACCOUNTS and row.id not in capital_account_ids
            ) else "بله",
        ])
    account_sheet.extend([
        ["طلب", "دیجی‌کالا", digikala_receivable, "محاسبه‌شده از گردش فروش/دریافت", "بله"],
        ["طلب", "Dia Gallery", dia_receivable, "قبلاً داخل جمع حساب‌ها لحاظ شده", "بله"],
        ["بدهی", "تکوین", -takvin_debt, "در سرمایه کل کسر شده", "بله"],
    ])

    stock_rows = []
    for row in StockBalance.objects.select_related(
        "brand", "color", "size", "location"
    ).order_by("brand__name", "color__name", "size__sort_order", "location__key", "id"):
        stock_rows.append([
            row.brand.name, row.color.name, row.size.name, row.location.title,
            int(row.qty or 0),
        ])
    materials = []
    for row in RawMaterialStock.objects.filter(active=True).order_by(
        "kind", "location", "material_key", "id"
    ):
        materials.append([
            row.get_kind_display(), row.get_location_display(), row.title,
            row.material_key, row.variant, row.quantity, int(row.unit_price or 0),
            int(row.total_value or 0), row.note or "", int(row.id),
        ])

    return [
        Sheet("خلاصه", ["شاخص", "مقدار / توضیح"], summary, widths=(44, 98), money_columns=(2,)),
        Sheet("حساب‌ها و دارایی", ["بخش", "عنوان", "مبلغ (تومان)", "توضیح", "در سرمایه"],
              account_sheet, widths=(21, 35, 23, 65, 17), money_columns=(3,)),
        Sheet("موجودی کالای فعلی", ["برند", "رنگ", "سایز", "محل", "تعداد"],
              stock_rows, widths=(19, 26, 14, 18, 18)),
        Sheet("مواد اولیه فعلی", ["نوع", "محل", "رنگ / مدل", "کلید", "نوع کش",
                                  "وزن (کیلو)", "فی کیلو", "ارزش", "توضیح", "شناسه"],
              materials, widths=(16, 17, 28, 18, 14, 17, 22, 24, 49, 13),
              decimal_columns=(6,), money_columns=(7, 8)),
    ]


def _transaction_sheets(start, end):
    expenses = [
        [_label_date(row.date), row.category.name, row.title, int(row.amount or 0),
         row.note or "", int(row.id)]
        for row in Expense.objects.filter(date__gte=start, date__lte=end)
        .select_related("category").order_by("date", "id")
    ]
    payments = [
        [_label_date(row.date), row.get_payee_display(), row.get_source_account_display()
         if hasattr(row, "get_source_account_display") else getattr(row, "source_account", ""),
         int(row.amount or 0), row.note or "", int(row.id)]
        for row in BusinessPayment.objects.filter(date__gte=start, date__lte=end)
        .order_by("date", "id")
    ]
    production = []
    blocks = list(
        MaterialReportBlock.objects.filter(date__gte=start, date__lte=end)
        .select_related("brand")
        .prefetch_related("output_applications", "stock_consumptions")
        .order_by("date", "id")
    )
    for block in blocks:
        applied = list(block.output_applications.all())
        applied_total = sum(int(x.quantity or 0) for x in applied)
        consumption = list(block.stock_consumptions.all())
        fabric_used = sum((Decimal(x.quantity or 0) for x in consumption
                           if x.kind == RawMaterialStock.FABRIC), Decimal("0"))
        elastic_used = sum((Decimal(x.quantity or 0) for x in consumption
                            if x.kind == RawMaterialStock.ELASTIC), Decimal("0"))
        production.append([
            _label_date(block.date), block.brand.name, block.title,
            applied_total, fabric_used, elastic_used, int(block.delivery_wage or 0),
            block.note or "", int(block.id),
        ])
    return [
        Sheet("هزینه‌های ماه", ["تاریخ", "دسته", "عنوان", "مبلغ", "توضیح", "شناسه"],
              expenses, widths=(17, 24, 42, 24, 55, 13), money_columns=(4,)),
        Sheet("پرداخت‌های ماه", ["تاریخ", "گیرنده", "منبع پرداخت", "مبلغ", "توضیح", "شناسه"],
              payments, widths=(17, 25, 23, 24, 58, 13), money_columns=(4,)),
        Sheet("صورت‌های تولید ماه", ["تاریخ صورت", "برند", "عنوان", "محصول تحویلیِ اعمال‌شده",
                                   "پارچه مصرفی کیلو", "کش مصرفی کیلو", "مزد ثبت‌شده",
                                   "توضیح", "شناسه"],
              production, widths=(17, 19, 42, 27, 23, 22, 22, 49, 13),
              decimal_columns=(5, 6), money_columns=(7,)),
    ]


@login_required
def export_monthly_report_xlsx(request):
    # A direct visit defaults to the prior completed Jalali month.
    if "period" not in request.GET:
        from django.http import QueryDict
        copied = request.GET.copy()
        copied["period"] = "last_month"
        request.GET = copied
    period, start, end = _period_range(request)
    data = _period_data(start, end)
    now = timezone.now()

    brand_rows = [
        [brand, *_metrics_row(metrics)]
        for brand, metrics in sorted(data["brands"].items())
    ]
    size_rows = [
        [brand, size, *_metrics_row(metrics)]
        for (brand, size), metrics in sorted(data["brand_sizes"].items())
    ]
    product_rows = [
        [brand, code, size, *_metrics_row(metrics)]
        for (brand, code, size), metrics in sorted(data["products"].items())
    ]
    color_rows = [
        [color, size, qty] for (color, size), qty in sorted(data["colors"].items())
    ]

    sheets = []
    sheets.extend(_snapshot_sheets(start, end, data, now))
    sheets.insert(1, _daily_sheets(data))
    sheets.insert(2, Sheet(
        "ریز فروش ماه",
        ["تاریخ", "برند", "کد محصول / رنگ", "سایز", "تعداد پک", "تعداد شورت",
         "فی فروش", "فروش", "کارمزد", "بهای کالا", "سود", "حاشیه سود ٪", "شناسه"],
        data["sale_rows"],
        widths=(17, 20, 29, 13, 16, 18, 20, 22, 22, 22, 22, 19, 16),
        money_columns=(7, 8, 9, 10, 11), percent_columns=(12,),
    ))
    sheets.insert(3, Sheet(
        "فروش به تفکیک برند",
        ["برند", "پک", "شورت", "فروش", "کارمزد", "بهای کالا", "سود", "حاشیه ٪"],
        brand_rows, widths=(20, 15, 16, 23, 21, 22, 22, 16),
        money_columns=(4, 5, 6, 7), percent_columns=(8,),
    ))
    sheets.insert(4, Sheet(
        "فروش برند و سایز",
        ["برند", "سایز", "پک", "شورت", "فروش", "کارمزد", "بهای کالا", "سود", "حاشیه ٪"],
        size_rows, widths=(20, 13, 14, 15, 23, 21, 22, 22, 16),
        money_columns=(5, 6, 7, 8), percent_columns=(9,),
    ))
    sheets.insert(5, Sheet(
        "سود محصولات",
        ["برند", "محصول", "سایز", "پک", "شورت", "فروش", "کارمزد", "بهای کالا", "سود", "حاشیه ٪"],
        product_rows, widths=(20, 25, 13, 14, 15, 22, 21, 22, 22, 16),
        money_columns=(6, 7, 8, 9), percent_columns=(10,),
    ))
    sheets.insert(6, Sheet(
        "فروش رنگ‌های دارما", ["رنگ", "سایز", "تعداد شورت"],
        color_rows, widths=(29, 13, 20),
    ))
    sheets.extend(_transaction_sheets(start, end))

    payload = make_workbook(sheets)
    filename = f"darma-report-{_label_date(start).replace('/', '-')}-{_label_date(end).replace('/', '-')}.xlsx"
    response = HttpResponse(
        payload,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "no-store"
    return response
