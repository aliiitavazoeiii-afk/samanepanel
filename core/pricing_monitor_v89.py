"""V89 pricing monitor: compare Darma by working-day ordinal, not calendar day."""
from collections import defaultdict
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from . import pricing_monitor_v88 as v88
from .dateutils import format_jalali
from .pricing_eval_v89 import latest_price_evaluations
from .working_days_v89 import month_bounds, working_dates


def _aggregate_dates(dates):
    dates = list(dict.fromkeys(dates or []))
    if not dates:
        return {
            "products": {}, "days": {},
            "total": v88._finish(v88._zero()), "pack_qty": {},
        }
    wanted = set(dates)
    by_product = defaultdict(v88._zero)
    by_day = defaultdict(v88._zero)
    total = v88._zero()
    pack_qty = {}
    qs = v88._sale_lines(min(wanted), max(wanted)).filter(day__date__in=wanted)
    for line in qs:
        metrics = v88.sale_line_metrics(line)
        key = (v88._canonical_code(line.product_size.product.code), line.product_size.size.name)
        v88._add(by_product[key], metrics)
        v88._add(by_day[line.day.date], metrics)
        v88._add(total, metrics)
        packs = int(metrics.get("packs") or 0)
        shorts = int(metrics.get("shorts") or 0)
        pack_qty[key] = (
            max(1, round(shorts / packs))
            if packs > 0 else int(line.product_size.product.pack_qty or 0)
        )
    return {
        "products": {k: v88._finish(v) for k, v in by_product.items()},
        "days": {k: v88._finish(v) for k, v in by_day.items()},
        "total": v88._finish(total),
        "pack_qty": pack_qty,
    }


def pricing_monitor_data(as_of=None, *, include_evaluations=True):
    as_of = as_of or date.today()
    is_partial_day = as_of == date.today()
    month_start, _ = month_bounds(as_of)
    previous_month_start = v88._previous_jalali_month_start(as_of)
    previous_month_end = month_start - timedelta(days=1)

    current_working_through_day = working_dates(month_start, as_of)
    is_working_day = as_of in current_working_through_day
    workday_number = (
        current_working_through_day.index(as_of) + 1
        if is_working_day else len(current_working_through_day)
    )
    previous_month_working = working_dates(previous_month_start, previous_month_end)
    previous_day = (
        previous_month_working[workday_number - 1]
        if is_working_day and workday_number > 0 and len(previous_month_working) >= workday_number
        else None
    )

    current_day = v88._aggregate(as_of, as_of)
    previous_day_data = v88._aggregate(previous_day, previous_day) if previous_day else _aggregate_dates([])

    fair_through = as_of - timedelta(days=1) if is_partial_day else as_of
    current_complete_working = working_dates(month_start, fair_through) if fair_through >= month_start else []
    common_count = min(len(current_complete_working), len(previous_month_working))
    matched_current_dates = current_complete_working[:common_count]
    matched_previous_dates = previous_month_working[:common_count]
    current_mtd = _aggregate_dates(matched_current_dates)
    previous_mtd = _aggregate_dates(matched_previous_dates)

    top_keys = v88._top_previous_month_keys(as_of, 20)
    day_comparison_available = bool(is_working_day and previous_day)
    day_rows = (
        v88._combined_rows(
            current_day, previous_day_data,
            partial=is_partial_day, top_keys=top_keys,
        )
        if day_comparison_available else []
    )
    mtd_rows = v88._combined_rows(current_mtd, previous_mtd, partial=False, top_keys=top_keys)

    current_cost = int(v88.darma_cost_for(as_of) or 0)
    for row in mtd_rows:
        prev = row["previous"]
        adjusted_previous_profit = (
            int(prev["gross"] or 0)
            - int(prev["fee"] or 0)
            - int(prev["shorts"] or 0) * current_cost
        )
        row["adjusted_previous_profit"] = adjusted_previous_profit
        row["adjusted_profit_delta"] = {
            "value": int(row["current"]["profit"] or 0) - adjusted_previous_profit,
            "pct": v88._pct_change(row["current"]["profit"], adjusted_previous_profit),
        }

    labels, current_cum, previous_cum, current_profit_cum, previous_profit_cum = [], [], [], [], []
    cur_sales = prev_sales = cur_profit = prev_profit = 0
    for idx, (cur_date, prev_date) in enumerate(zip(matched_current_dates, matched_previous_dates), start=1):
        cur_day = current_mtd["days"].get(cur_date, {})
        prev_day_metrics = previous_mtd["days"].get(prev_date, {})
        cur_sales += int(cur_day.get("gross", 0))
        prev_sales += int(prev_day_metrics.get("gross", 0))
        cur_profit += int(cur_day.get("profit", 0))
        prev_profit += int(prev_day_metrics.get("profit", 0))
        labels.append(str(idx))
        current_cum.append(cur_sales)
        previous_cum.append(prev_sales)
        current_profit_cum.append(cur_profit)
        previous_profit_cum.append(prev_profit)

    history = v88._price_history() if include_evaluations else []
    evaluations = latest_price_evaluations(as_of, history) if include_evaluations else []

    if not is_working_day:
        comparison_message = "این تاریخ روز کاری دارما نیست؛ مقایسه روزانه انجام نمی‌شود."
    elif not previous_day:
        comparison_message = "برای شماره این روز کاری، در ماه قبل روز کاری متناظر وجود ندارد."
    else:
        comparison_message = f"روز کاری {workday_number} ماه جاری با روز کاری {workday_number} ماه قبل مقایسه می‌شود."

    return {
        "as_of": as_of,
        "as_of_j": format_jalali(as_of),
        "previous_day": previous_day,
        "previous_day_j": format_jalali(previous_day) if previous_day else "—",
        "is_partial_day": is_partial_day,
        "is_working_day": is_working_day,
        "workday_number": workday_number,
        "day_comparison_available": day_comparison_available,
        "comparison_message": comparison_message,
        "day_current": current_day,
        "day_previous": previous_day_data,
        "day_rows": day_rows,
        "mtd_current": current_mtd,
        "mtd_previous": previous_mtd,
        "mtd_rows": mtd_rows,
        "mtd_workday_count": common_count,
        "mtd_start_j": format_jalali(matched_current_dates[0]) if matched_current_dates else "—",
        "mtd_end_j": format_jalali(matched_current_dates[-1]) if matched_current_dates else "—",
        "previous_mtd_start_j": format_jalali(matched_previous_dates[0]) if matched_previous_dates else "—",
        "previous_mtd_end_j": format_jalali(matched_previous_dates[-1]) if matched_previous_dates else "—",
        "top_keys": top_keys,
        "price_history": history,
        "evaluations": evaluations,
        "current_cost": current_cost,
        "credit_data_available": False,
        "credit_note": "نوع پرداخت نقدی/اعتباری در SaleLine/SaleSnapshot فعلی ذخیره نشده؛ بنابراین این ماژول مبلغ اعتباری یا کارمزد اضافه را حدس نمی‌زند.",
        "chart_labels": labels,
        "chart_sales_current": current_cum,
        "chart_sales_previous": previous_cum,
        "chart_profit_current": current_profit_cum,
        "chart_profit_previous": previous_profit_cum,
    }


def dashboard_pricing_context(as_of=None):
    data = pricing_monitor_data(as_of or date.today(), include_evaluations=False)
    return {
        "pricing_monitor": {
            "as_of_j": data["as_of_j"],
            "previous_day_j": data["previous_day_j"],
            "is_partial_day": data["is_partial_day"],
            "is_working_day": data["is_working_day"],
            "workday_number": data["workday_number"],
            "comparison_message": data["comparison_message"],
            "rows": data["day_rows"][:8] if data["day_comparison_available"] else [],
            "current_total": data["day_current"]["total"],
            "previous_total": data["day_previous"]["total"],
        }
    }


@login_required
def pricing_monitor(request):
    as_of, date_warning = v88._requested_as_of(request)
    data = pricing_monitor_data(as_of)
    data["date_warning"] = date_warning
    code_filter = (request.GET.get("code") or "").strip()
    size_filter = (request.GET.get("size") or "").strip()
    if code_filter:
        data["day_rows"] = [r for r in data["day_rows"] if r["code"] == code_filter]
        data["mtd_rows"] = [r for r in data["mtd_rows"] if r["code"] == code_filter]
        data["evaluations"] = [r for r in data["evaluations"] if r["code"] == code_filter]
    if size_filter:
        data["day_rows"] = [r for r in data["day_rows"] if r["size"] == size_filter]
        data["mtd_rows"] = [r for r in data["mtd_rows"] if r["size"] == size_filter]
        data["evaluations"] = [r for r in data["evaluations"] if r["size"] == size_filter]
    data["code_filter"] = code_filter
    data["size_filter"] = size_filter
    data["date_filter"] = data["as_of_j"]
    data["filter_codes"] = sorted({k[0] for k in data["top_keys"]})
    data["filter_sizes"] = sorted({k[1] for k in data["top_keys"]})
    return render(request, "core/pricing_monitor_v89.html", data)
