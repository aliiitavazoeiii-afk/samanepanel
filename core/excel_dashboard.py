from collections import defaultdict
from datetime import date

import jdatetime
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.shortcuts import render

from .dateutils import format_jalali
from .dia_gallery_v45 import dia_gallery_period_metrics
from .finance import sale_line_metrics
from .models import InventoryMovement, MaterialReportBlock, SaleDay, SaleLine, StockBalance, StockLocation, TakvinPurchase
from .pricing_monitor_v88 import dashboard_pricing_context

EXCEL_TAKVIN_PREFIX = "[excel-web]"


def _empty_metrics():
    return {
        "gross": 0,
        "profit": 0,
        "shorts": 0,
        "digikala_fee": 0,
        "packs": 0,
        "cogs": 0,
        "margin": 0,
    }


def _add_metrics(target, source):
    for key in ["gross", "profit", "shorts", "digikala_fee", "packs", "cogs"]:
        target[key] += source[key]


def _finish_metrics(values):
    values["margin"] = values["profit"] * 100 / values["gross"] if values["gross"] else 0
    return values


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

    # Dashboard trend: last 14 days that actually have a recorded sale.
    # Empty/holiday days are intentionally omitted instead of rendered as zero-value points.
    chart_days = list(
        SaleDay.objects.filter(date__lte=today)
        .filter(Q(lines__quantity__gt=0) | Q(dia_gallery_sales__quantity__gt=0))
        .distinct()
        .order_by("-date")[:14]
    )
    chart_days.sort(key=lambda day: day.date)

    daily = defaultdict(lambda: {"gross": 0, "profit": 0})
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
            daily[line.day.date]["gross"] += metrics["gross"]
            daily[line.day.date]["profit"] += metrics["profit"]
        for row in dia_gallery_period_metrics(chart_start, chart_end)["rows"]:
            daily[row["date"]]["gross"] += int(row["gross"] or 0)
            daily[row["date"]]["profit"] += int(row["profit"] or 0)

    chart_labels, chart_sales, chart_profit = [], [], []
    for day in chart_days:
        jlabel = format_jalali(day.date)
        chart_labels.append(jlabel[5:] if len(jlabel) >= 10 else jlabel)
        chart_sales.append(daily[day.date]["gross"])
        chart_profit.append(daily[day.date]["profit"])

    # Dashboard alerts are only for Darma HOME cells that have genuinely been stocked.
    # StockBalance rows are created at zero for every color/size, so zero rows with no positive
    # inventory history are catalog placeholders and must not create false warnings.
    alerts = []
    defined_cells = set(
        InventoryMovement.objects.filter(
            brand__name="دارما",
            delta__gt=0,
        ).values_list("size_id", "color_id")
    )
    low_home = (
        StockBalance.objects.filter(
            brand__name="دارما",
            location__key=StockLocation.HOME,
            color__active=True,
            qty__lt=10,
        )
        .exclude(color__name__in=["قرمز", "زرد"])
        .select_related("color", "size")
        .order_by("qty", "color__name", "size__sort_order", "size__id")
    )
    for balance in low_home:
        current_qty = int(balance.qty or 0)
        # A currently positive cell is obviously real. A zero/negative cell is real only when
        # it has previously received positive inventory. If the user stocks it later, the next
        # low-stock state will automatically become eligible for an alert.
        if current_qty <= 0 and (balance.size_id, balance.color_id) not in defined_cells:
            continue
        alerts.append({
            "level": "red",
            "title": f"{balance.color.name} / {balance.size.name}",
            "detail": f"موجودی خانه: {current_qty} عدد",
            "url": "/inventory/",
        })

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
        "alerts": alerts,
        "purchase_month_total": purchase_month_total,
    }
    context.update(dashboard_pricing_context(today))
    return render(request, "core/dashboard_excel.html", context)
