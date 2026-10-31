from collections import defaultdict
from datetime import date

import jdatetime
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.shortcuts import render

from .dateutils import format_jalali
from .dia_gallery_v45 import dia_gallery_period_metrics
from .excel_dashboard import EXCEL_TAKVIN_PREFIX, _add_metrics, _empty_metrics, _finish_metrics
from .finance import sale_line_metrics
from .models import MaterialReportBlock, SaleDay, SaleLine, TakvinPurchase


@login_required
def dashboard(request):
    today = date.today()
    today_metrics = _empty_metrics()
    today_day = SaleDay.objects.filter(date=today).first()
    if today_day:
        for line in today_day.lines.filter(quantity__gt=0).select_related(
            "product_size__product", "product_size__size"
        ):
            _add_metrics(today_metrics, sale_line_metrics(line))
    _add_metrics(today_metrics, dia_gallery_period_metrics(today, today)["total"])
    _finish_metrics(today_metrics)

    tj = jdatetime.date.fromgregorian(date=today)
    month_start = jdatetime.date(tj.year, tj.month, 1).togregorian()
    month_metrics = _empty_metrics()
    month_lines = SaleLine.objects.filter(
        day__date__gte=month_start, day__date__lte=today, quantity__gt=0
    ).select_related("day", "product_size__product", "product_size__size")
    for line in month_lines:
        _add_metrics(month_metrics, sale_line_metrics(line))
    _add_metrics(month_metrics, dia_gallery_period_metrics(month_start, today)["total"])
    _finish_metrics(month_metrics)

    # V89: show the latest 30 dates that actually contain recorded sales.
    chart_days = list(
        SaleDay.objects.filter(date__lte=today)
        .filter(Q(lines__quantity__gt=0) | Q(dia_gallery_sales__quantity__gt=0))
        .distinct()
        .order_by("-date")[:30]
    )
    chart_days.sort(key=lambda day: day.date)

    # Keep the summary metrics on exactly the same population as the chart:
    # latest N recorded-sale dates, with both ordinary sales and Dia Gallery.
    daily = defaultdict(lambda: {"gross": 0, "profit": 0, "shorts": 0})
    if chart_days:
        chart_start = chart_days[0].date
        chart_end = chart_days[-1].date
        chart_lines = SaleLine.objects.filter(
            day__date__gte=chart_start,
            day__date__lte=chart_end,
            quantity__gt=0,
        ).select_related("day", "product_size__product", "product_size__size")
        for line in chart_lines:
            metrics = sale_line_metrics(line)
            daily[line.day.date]["gross"] += int(metrics["gross"] or 0)
            daily[line.day.date]["profit"] += int(metrics["profit"] or 0)
            daily[line.day.date]["shorts"] += int(metrics["shorts"] or 0)
        for row in dia_gallery_period_metrics(chart_start, chart_end)["rows"]:
            daily[row["date"]]["gross"] += int(row["gross"] or 0)
            daily[row["date"]]["profit"] += int(row["profit"] or 0)
            daily[row["date"]]["shorts"] += int(row["shorts"] or 0)

    chart_labels, chart_sales, chart_profit, chart_shorts = [], [], [], []
    for day in chart_days:
        jlabel = format_jalali(day.date)
        chart_labels.append(jlabel[5:] if len(jlabel) >= 10 else jlabel)
        chart_sales.append(daily[day.date]["gross"])
        chart_profit.append(daily[day.date]["profit"])
        chart_shorts.append(daily[day.date]["shorts"])

    chart_day_count = len(chart_days)
    chart_avg_sales = (
        round(sum(chart_sales) / chart_day_count) if chart_day_count else 0
    )
    chart_avg_profit = (
        round(sum(chart_profit) / chart_day_count) if chart_day_count else 0
    )
    chart_avg_shorts = (
        round(sum(chart_shorts) / chart_day_count, 1) if chart_day_count else 0
    )

    purchase_month_total = TakvinPurchase.objects.filter(
        date__gte=month_start,
        date__lte=today,
        note__startswith=EXCEL_TAKVIN_PREFIX,
    ).aggregate(v=Sum("total_cost"))["v"] or 0

    context = {
        "today_metrics": today_metrics,
        "month_metrics": month_metrics,
        "today_j": format_jalali(today),
        "material_blocks": MaterialReportBlock.objects.count(),
        "chart_labels": chart_labels,
        "chart_sales": chart_sales,
        "chart_profit": chart_profit,
        "chart_shorts": chart_shorts,
        "chart_day_count": chart_day_count,
        "chart_avg_sales": chart_avg_sales,
        "chart_avg_profit": chart_avg_profit,
        "chart_avg_shorts": chart_avg_shorts,
        "purchase_month_total": purchase_month_total,
    }
    return render(request, "core/dashboard_excel_v89.html", context)
