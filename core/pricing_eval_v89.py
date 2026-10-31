"""Working-day based 10-day price evaluation for V89."""
from collections import defaultdict
from datetime import date, timedelta

from . import pricing_monitor_v88 as v88
from .dateutils import format_jalali
from .working_days_v89 import group_working_dates, previous_working_date, working_dates


def latest_price_evaluations(as_of, history=None):
    history = history if history is not None else v88._price_history()
    latest = {}
    for row in history:
        if row["effective_from"] <= as_of:
            latest[(row["code"], row["size"])] = row
    if not latest:
        return []

    complete_through = as_of if as_of < date.today() else date.today() - timedelta(days=1)
    earliest = min(row["effective_from"] for row in latest.values()) + timedelta(days=1)
    if complete_through < earliest:
        all_working = []
        grouped = defaultdict(list)
    else:
        previous_start = v88._previous_jalali_month_start(earliest)
        all_working = working_dates(previous_start, complete_through)
        grouped = group_working_dates(all_working)

    windows = {}
    wanted = set()
    for key, rule in latest.items():
        candidates = [
            d for d in all_working
            if d > rule["effective_from"] and d <= complete_through
        ][:10]
        current_dates = []
        prior_dates = []
        for current_date in candidates:
            _ordinal, prior = previous_working_date(current_date, grouped)
            if prior is None:
                continue
            current_dates.append(current_date)
            prior_dates.append(prior)
            wanted.add(current_date)
            wanted.add(prior)
        windows[key] = (rule, current_dates, prior_dates)

    by_date_product = defaultdict(v88._zero)
    all_darma_by_date = defaultdict(v88._zero)
    if wanted:
        qs = v88._sale_lines(min(wanted), max(wanted)).filter(day__date__in=wanted)
        for line in qs.iterator(chunk_size=250):
            metrics = v88.sale_line_metrics(line)
            key = (
                v88._canonical_code(line.product_size.product.code),
                line.product_size.size.name,
            )
            v88._add(by_date_product[(line.day.date, key)], metrics)
            v88._add(all_darma_by_date[line.day.date], metrics)

    current_cost = int(v88.darma_cost_for(as_of) or 0)
    rows = []
    for key, (rule, current_dates, prior_dates) in windows.items():
        cur_raw, prev_raw, all_cur, all_prev = (
            v88._zero(), v88._zero(), v88._zero(), v88._zero()
        )
        for day in current_dates:
            v88._add(cur_raw, by_date_product.get((day, key), v88._zero()))
            v88._add(all_cur, all_darma_by_date.get(day, v88._zero()))
        for day in prior_dates:
            v88._add(prev_raw, by_date_product.get((day, key), v88._zero()))
            v88._add(all_prev, all_darma_by_date.get(day, v88._zero()))

        cur, prev = v88._finish(cur_raw), v88._finish(prev_raw)
        adjusted_prev_profit = (
            int(prev["gross"] or 0)
            - int(prev["fee"] or 0)
            - int(prev["shorts"] or 0) * current_cost
        )
        packs_pct = v88._pct_change(cur["packs"], prev["packs"])
        profit_pct = v88._pct_change(cur["profit"], prev["profit"])
        adjusted_profit_pct = v88._pct_change(cur["profit"], adjusted_prev_profit)
        cur_share = cur["gross"] * 100 / all_cur["gross"] if all_cur["gross"] else 0
        prev_share = prev["gross"] * 100 / all_prev["gross"] if all_prev["gross"] else 0
        share_delta_pp = cur_share - prev_share
        complete_days = len(current_dates)

        if complete_days < 10 or prev["packs"] == 0:
            status = "نیازمند داده بیشتر"
        elif (
            packs_pct is not None and packs_pct >= 0
            and adjusted_profit_pct is not None and adjusted_profit_pct > 0
            and share_delta_pp >= -1
        ):
            status = "نشانه مثبت؛ نرخ تبدیل نامشخص"
        elif (
            packs_pct is not None and packs_pct < 0
            and adjusted_profit_pct is not None and adjusted_profit_pct < 0
        ):
            status = "نیازمند بررسی افت عملکرد"
        else:
            status = "نیازمند پایش بیشتر"

        rows.append({
            **rule,
            "complete_days": complete_days,
            "period_start_j": format_jalali(current_dates[0]) if current_dates else "—",
            "period_end_j": format_jalali(current_dates[-1]) if current_dates else "—",
            "current": cur,
            "previous": prev,
            "adjusted_previous_profit": adjusted_prev_profit,
            "packs_pct": packs_pct,
            "profit_pct": profit_pct,
            "adjusted_profit_pct": adjusted_profit_pct,
            "current_share": cur_share,
            "previous_share": prev_share,
            "share_delta_pp": share_delta_pp,
            "status": status,
        })
    rows.sort(key=lambda r: (-r["complete_days"], r["code"], r["size"]))
    return rows
