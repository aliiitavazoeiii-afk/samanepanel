"""XLSX export for V89 working-day pricing monitor."""
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse

from . import pricing_monitor_v88 as v88
from .monthly_xlsx_v83 import Sheet, make_workbook
from .pricing_monitor_v89 import pricing_monitor_data


@login_required
def pricing_monitor_xlsx(request):
    as_of, _ = v88._requested_as_of(request)
    data = pricing_monitor_data(as_of)
    code_filter = (request.GET.get("code") or "").strip()
    size_filter = (request.GET.get("size") or "").strip()
    day_rows = data["day_rows"]
    mtd_rows = data["mtd_rows"]
    evaluations = data["evaluations"]
    if code_filter:
        day_rows = [r for r in day_rows if r["code"] == code_filter]
        mtd_rows = [r for r in mtd_rows if r["code"] == code_filter]
        evaluations = [r for r in evaluations if r["code"] == code_filter]
    if size_filter:
        day_rows = [r for r in day_rows if r["size"] == size_filter]
        mtd_rows = [r for r in mtd_rows if r["size"] == size_filter]
        evaluations = [r for r in evaluations if r["size"] == size_filter]

    headers = [
        "کد", "سایز", "تعداد در پک",
        "پک دوره فعلی", "پک دوره قبل", "تغییر پک", "تغییر پک ٪",
        "فروش فعلی", "فروش قبل", "تغییر فروش", "تغییر فروش ٪",
        "سود فعلی", "سود قبل", "تغییر سود", "تغییر سود ٪",
        "حاشیه فعلی ٪", "حاشیه قبل ٪", "تغییر حاشیه واحد درصد",
        "میانگین قیمت پک فعلی", "میانگین قیمت پک قبل",
        "قیمت هر شورت فعلی", "قیمت هر شورت قبل",
        "سهم فروش فعلی ٪", "سهم فروش قبل ٪", "تغییر سهم واحد درصد",
    ]
    summary = [
        ["تاریخ گزارش", data["as_of_j"]],
        ["روز کاری", data["workday_number"] if data["is_working_day"] else "تعطیل / بدون فروش دارما"],
        ["روز کاری متناظر ماه قبل", data["previous_day_j"]],
        ["قاعده مقایسه", data["comparison_message"]],
        ["تعداد روز کاری تجمعی مقایسه‌شده", data["mtd_workday_count"]],
        ["بازه تجمعی فعلی", f'{data["mtd_start_j"]} تا {data["mtd_end_j"]}'],
        ["بازه تجمعی قبل", f'{data["previous_mtd_start_j"]} تا {data["previous_mtd_end_j"]}'],
        ["بهای فعلی هر شورت دارما", data["current_cost"]],
        ["مبنای سود", "sale_line_metrics + SaleSnapshot تاریخی"],
        ["فروش اعتباری", data["credit_note"]],
    ]
    history_rows = [[
        r["code"], r["size"], r["pack_qty"], r["effective_j"],
        r["previous_price"], r["price"], r["change_pct"],
    ] for r in data["price_history"] if (
        (not code_filter or r["code"] == code_filter)
        and (not size_filter or r["size"] == size_filter)
    )]
    evaluation_rows = [[
        r["code"], r["size"], r["effective_j"], r["complete_days"],
        r["current"]["packs"], r["previous"]["packs"], r["packs_pct"],
        r["current"]["profit"], r["previous"]["profit"], r["profit_pct"],
        r["adjusted_previous_profit"], r["adjusted_profit_pct"], r["status"],
    ] for r in evaluations]

    comparison_widths = (18,12,12,14,14,14,14,20,20,20,16,20,20,20,16,14,14,18,22,22,20,20,16,16,18)
    sheets = [
        Sheet("خلاصه مدیریتی", ["شاخص", "مقدار"], summary, widths=(38, 96), money_columns=(2,)),
        Sheet("مقایسه روز کاری", headers, v88._comparison_sheet_rows(day_rows),
              widths=comparison_widths, money_columns=(8,9,10,12,13,14,19,20,21,22),
              percent_columns=(7,11,15,16,17,18,23,24,25)),
        Sheet("مقایسه تجمعی", headers, v88._comparison_sheet_rows(mtd_rows),
              widths=comparison_widths, money_columns=(8,9,10,12,13,14,19,20,21,22),
              percent_columns=(7,11,15,16,17,18,23,24,25)),
        Sheet("تاریخچه قیمت", ["کد","سایز","تعداد در پک","تاریخ اجرا","قیمت قبلی","قیمت جدید","تغییر ٪"],
              history_rows, widths=(20,12,14,18,22,22,16), money_columns=(5,6), percent_columns=(7,)),
        Sheet("ارزیابی ۱۰ روز کاری", [
            "کد","سایز","شروع قیمت","روز کاری کامل","پک فعلی","پک قبل","تغییر پک ٪",
            "سود واقعی فعلی","سود واقعی قبل","تغییر سود واقعی ٪",
            "سود قبل با هزینه فعلی","تغییر سود تعدیل‌شده ٪","وضعیت",
        ], evaluation_rows, widths=(18,12,18,16,14,14,16,22,22,18,24,20,30),
           money_columns=(8,9,11), percent_columns=(7,10,12)),
    ]
    payload = make_workbook(sheets)
    response = HttpResponse(
        payload,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="darma-pricing-monitor-v89.xlsx"'
    response["Cache-Control"] = "no-store"
    return response
