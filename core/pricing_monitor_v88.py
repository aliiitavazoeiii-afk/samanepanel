"""V88 read-only Darma pricing/performance monitor.

No accounting, stock, receivable, SaleLine or historical row is mutated here.
All historical economics come from the canonical sale_line_metrics() helper,
which honors SaleSnapshot when present.
"""
from collections import defaultdict
from datetime import date, timedelta

import jdatetime
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render

from .darma_cost_v55 import darma_cost_for
from .dateutils import format_jalali, parse_jalali_date
from .finance import sale_line_metrics
from .models import AppSetting, ProductSize, SaleLine
from .monthly_xlsx_v83 import Sheet, make_workbook
from .sale_price_v60 import RULE_PREFIX as SALE_PRICE_RULE_PREFIX, _parse_rule_key


def _previous_jalali_same_day(value):
    j = jdatetime.date.fromgregorian(date=value)
    year, month = j.year, j.month - 1
    if month == 0:
        year -= 1
        month = 12
    day = j.day
    while day > 0:
        try:
            return jdatetime.date(year, month, day).togregorian()
        except ValueError:
            day -= 1
    raise ValueError("Previous Jalali month could not be resolved.")


def _jalali_month_start(value):
    j = jdatetime.date.fromgregorian(date=value)
    return jdatetime.date(j.year, j.month, 1).togregorian()


def _previous_jalali_month_start(value):
    j = jdatetime.date.fromgregorian(date=value)
    year, month = j.year, j.month - 1
    if month == 0:
        year -= 1
        month = 12
    return jdatetime.date(year, month, 1).togregorian()


def _canonical_code(code):
    raw = str(code or "").strip()
    compact = raw.replace("-", "").replace("_", "").replace(" ", "").lower()
    if compact in {"06", "6", "pack6", "pack06"}:
        return "06"
    return raw


def _zero():
    return {
        "packs": 0, "shorts": 0, "gross": 0, "fee": 0,
        "cogs": 0, "profit": 0,
    }


def _add(target, metrics):
    target["packs"] += int(metrics.get("packs") or 0)
    target["shorts"] += int(metrics.get("shorts") or 0)
    target["gross"] += int(metrics.get("gross") or 0)
    target["fee"] += int(metrics.get("digikala_fee") or metrics.get("fee") or 0)
    target["cogs"] += int(metrics.get("cogs") or 0)
    target["profit"] += int(metrics.get("profit") or 0)


def _finish(values):
    result = dict(values)
    packs = int(result["packs"] or 0)
    shorts = int(result["shorts"] or 0)
    gross = int(result["gross"] or 0)
    result["margin"] = (result["profit"] * 100 / gross) if gross else 0
    result["avg_pack_price"] = round(gross / packs) if packs else 0
    result["avg_short_price"] = round(gross / shorts) if shorts else 0
    result["profit_per_pack"] = round(result["profit"] / packs) if packs else 0
    return result


def _pct_change(current, previous):
    current, previous = float(current or 0), float(previous or 0)
    if previous == 0:
        return None if current != 0 else 0.0
    return (current - previous) * 100 / abs(previous)


def _delta(current, previous, *, partial=False):
    if partial:
        return {"value": None, "pct": None}
    return {
        "value": (current or 0) - (previous or 0),
        "pct": _pct_change(current, previous),
    }


def _sale_lines(start, end):
    return (
        SaleLine.objects.filter(
            day__date__gte=start,
            day__date__lte=end,
            quantity__gt=0,
            product_size__product__brand__name="دارما",
        )
        .select_related(
            "day", "product_size__product__brand",
            "product_size__product", "product_size__size", "snapshot",
        )
        .order_by("day__date", "id")
    )


def _aggregate(start, end):
    by_product = defaultdict(_zero)
    by_day = defaultdict(_zero)
    total = _zero()
    pack_qty = {}
    for line in _sale_lines(start, end):
        metrics = sale_line_metrics(line)
        code = _canonical_code(line.product_size.product.code)
        size = line.product_size.size.name
        key = (code, size)
        _add(by_product[key], metrics)
        _add(by_day[line.day.date], metrics)
        _add(total, metrics)
        packs = int(metrics.get("packs") or 0)
        shorts = int(metrics.get("shorts") or 0)
        if packs > 0:
            pack_qty[key] = max(1, round(shorts / packs))
        else:
            pack_qty[key] = int(line.product_size.product.pack_qty or 0)
    return {
        "products": {k: _finish(v) for k, v in by_product.items()},
        "days": {k: _finish(v) for k, v in by_day.items()},
        "total": _finish(total),
        "pack_qty": pack_qty,
    }


def _combined_rows(current_data, previous_data, *, partial=False, top_keys=None):
    keys = set(current_data["products"]) | set(previous_data["products"])
    if top_keys is not None:
        keys &= set(top_keys)
    current_total_gross = int(current_data["total"]["gross"] or 0)
    previous_total_gross = int(previous_data["total"]["gross"] or 0)
    rows = []
    for key in keys:
        code, size = key
        cur = current_data["products"].get(key, _finish(_zero()))
        prev = previous_data["products"].get(key, _finish(_zero()))
        pack_qty = (
            current_data["pack_qty"].get(key)
            or previous_data["pack_qty"].get(key)
            or 0
        )
        cur_share = cur["gross"] * 100 / current_total_gross if current_total_gross else 0
        prev_share = prev["gross"] * 100 / previous_total_gross if previous_total_gross else 0
        rows.append({
            "code": code,
            "size": size,
            "pack_qty": pack_qty,
            "current": cur,
            "previous": prev,
            "packs_delta": _delta(cur["packs"], prev["packs"], partial=partial),
            "gross_delta": _delta(cur["gross"], prev["gross"], partial=partial),
            "profit_delta": _delta(cur["profit"], prev["profit"], partial=partial),
            "margin_delta_pp": None if partial else cur["margin"] - prev["margin"],
            "avg_price_delta": _delta(
                cur["avg_pack_price"], prev["avg_pack_price"], partial=partial
            ),
            "current_share": cur_share,
            "previous_share": prev_share,
            "share_delta_pp": None if partial else cur_share - prev_share,
        })
    rows.sort(
        key=lambda row: (
            -int(row["current"]["packs"] or 0),
            -int(row["previous"]["packs"] or 0),
            row["code"], row["size"],
        )
    )
    return rows


def _top_previous_month_keys(as_of, limit=20):
    prev_start = _previous_jalali_month_start(as_of)
    this_start = _jalali_month_start(as_of)
    prev_end = this_start - timedelta(days=1)
    data = _aggregate(prev_start, prev_end)
    ranked = sorted(
        data["products"].items(),
        key=lambda item: (
            -int(item[1]["packs"] or 0),
            -int(item[1]["gross"] or 0),
            item[0],
        ),
    )
    return [key for key, _ in ranked[:limit]]


def _price_history():
    ps_map = {
        row.id: row
        for row in ProductSize.objects.filter(
            product__brand__name="دارما",
            product__active=True,
            active=True,
        ).select_related("product", "size")
    }
    rows = []
    for setting in AppSetting.objects.filter(
        key__startswith=SALE_PRICE_RULE_PREFIX
    ).order_by("key"):
        parsed = _parse_rule_key(setting.key)
        if not parsed:
            continue
        ps_id, effective_from = parsed
        ps = ps_map.get(ps_id)
        if not ps:
            continue
        try:
            price = int(setting.value or 0)
        except (TypeError, ValueError):
            continue
        rows.append({
            "setting_id": setting.id,
            "product_size_id": ps_id,
            "code": _canonical_code(ps.product.code),
            "size": ps.size.name,
            "pack_qty": int(ps.product.pack_qty or 0),
            "effective_from": effective_from,
            "effective_j": format_jalali(effective_from),
            "price": price,
            "legacy_price": int(ps.default_sale_price or 0),
            "updated_at": setting.updated_at,
        })
    rows.sort(key=lambda r: (r["effective_from"], r["setting_id"]))
    previous = {}
    for row in rows:
        ps_id = row["product_size_id"]
        row["previous_price"] = previous.get(ps_id, row["legacy_price"] or None)
        row["change_pct"] = (
            _pct_change(row["price"], row["previous_price"])
            if row["previous_price"] else None
        )
        previous[ps_id] = row["price"]
    return rows


def _same_jalali_dates(start, end):
    result = []
    d = start
    while d <= end:
        result.append((d, _previous_jalali_same_day(d)))
        d += timedelta(days=1)
    return result


def _window_for_dates(dates):
    if not dates:
        return {"products": {}, "days": {}, "total": _finish(_zero()), "pack_qty": {}}
    wanted = set(dates)
    by_product = defaultdict(_zero)
    total = _zero()
    pack_qty = {}
    qs = _sale_lines(min(wanted), max(wanted))
    for line in qs:
        if line.day.date not in wanted:
            continue
        metrics = sale_line_metrics(line)
        key = (_canonical_code(line.product_size.product.code), line.product_size.size.name)
        _add(by_product[key], metrics)
        _add(total, metrics)
        packs = int(metrics.get("packs") or 0)
        shorts = int(metrics.get("shorts") or 0)
        pack_qty[key] = round(shorts / packs) if packs else int(line.product_size.product.pack_qty or 0)
    return {
        "products": {k: _finish(v) for k, v in by_product.items()},
        "days": {},
        "total": _finish(total),
        "pack_qty": pack_qty,
    }


def _latest_price_evaluations(as_of, *, history=None):
    """Compute every latest ten-day evaluation from ONE bounded sale query.

    The old implementation scanned two windows for every product/size, then did
    it again for dashboard, HTML and XLSX rendering. That query fan-out can
    exhaust a small production VPS. Only the exact needed dates are fetched.
    """
    latest = {}
    for row in history if history is not None else _price_history():
        if row["effective_from"] <= as_of:
            latest[(row["code"], row["size"])] = row

    complete_through = (
        as_of if as_of < date.today()
        else date.today() - timedelta(days=1)
    )
    windows = {}
    wanted = set()
    for key, rule in latest.items():
        # V60 has date precision only: conservatively exclude the price-change
        # date because the actual activation time may be unknown.
        first_full = rule["effective_from"] + timedelta(days=1)
        complete_days = min(
            10, max(0, (complete_through - first_full).days + 1)
        )
        if complete_days:
            last_full = first_full + timedelta(days=complete_days - 1)
            pairs = _same_jalali_dates(first_full, last_full)
            current_dates = [pair[0] for pair in pairs]
            prior_dates = [pair[1] for pair in pairs]
            wanted.update(current_dates)
            wanted.update(prior_dates)
        else:
            current_dates, prior_dates = [], []
        windows[key] = (rule, complete_days, current_dates, prior_dates)

    by_date_product = defaultdict(_zero)
    all_darma_by_date = defaultdict(_zero)
    if wanted:
        qs = _sale_lines(min(wanted), max(wanted)).filter(day__date__in=wanted)
        for line in qs.iterator(chunk_size=250):
            metrics = sale_line_metrics(line)
            key = (
                _canonical_code(line.product_size.product.code),
                line.product_size.size.name,
            )
            _add(by_date_product[(line.day.date, key)], metrics)
            _add(all_darma_by_date[line.day.date], metrics)

    current_cost = int(darma_cost_for(as_of) or 0)
    rows = []
    for key, (rule, complete_days, current_dates, prior_dates) in windows.items():
        cur_raw, prev_raw, all_cur, all_prev = (
            _zero(), _zero(), _zero(), _zero()
        )
        for day in current_dates:
            _add(cur_raw, by_date_product.get((day, key), _zero()))
            _add(all_cur, all_darma_by_date.get(day, _zero()))
        for day in prior_dates:
            _add(prev_raw, by_date_product.get((day, key), _zero()))
            _add(all_prev, all_darma_by_date.get(day, _zero()))
        cur, prev = _finish(cur_raw), _finish(prev_raw)
        adjusted_prev_profit = (
            int(prev["gross"] or 0)
            - int(prev["fee"] or 0)
            - int(prev["shorts"] or 0) * current_cost
        )
        packs_pct = _pct_change(cur["packs"], prev["packs"])
        profit_pct = _pct_change(cur["profit"], prev["profit"])
        adjusted_profit_pct = _pct_change(cur["profit"], adjusted_prev_profit)
        cur_share = (
            cur["gross"] * 100 / all_cur["gross"] if all_cur["gross"] else 0
        )
        prev_share = (
            prev["gross"] * 100 / all_prev["gross"] if all_prev["gross"] else 0
        )
        share_delta_pp = cur_share - prev_share

        if complete_days < 10 or prev["packs"] == 0:
            status = "نیازمند داده بیشتر"
        elif (
            packs_pct is not None and packs_pct >= 0
            and adjusted_profit_pct is not None and adjusted_profit_pct > 0
            and share_delta_pp >= -1
        ):
            # Conversion and order-level credit data are unavailable; this
            # cannot be presented as a fully verified green recommendation.
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
            "period_start_j": (
                format_jalali(current_dates[0]) if current_dates else "—"
            ),
            "period_end_j": (
                format_jalali(current_dates[-1]) if current_dates else "—"
            ),
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

def pricing_monitor_data(as_of=None, *, include_evaluations=True):
    as_of = as_of or date.today()
    previous_day = _previous_jalali_same_day(as_of)
    is_partial_day = as_of == date.today()

    current_day = _aggregate(as_of, as_of)
    previous_same_day = _aggregate(previous_day, previous_day)

    # Fair month-to-date comparison excludes today's incomplete day.
    fair_end = as_of - timedelta(days=1) if is_partial_day else as_of
    month_start = _jalali_month_start(as_of)
    if fair_end < month_start:
        current_mtd = _aggregate(month_start, month_start - timedelta(days=1))
        previous_mtd = _aggregate(previous_day, previous_day - timedelta(days=1))
        current_mtd_start, current_mtd_end = month_start, fair_end
        previous_mtd_start, previous_mtd_end = _previous_jalali_month_start(as_of), _previous_jalali_month_start(as_of) - timedelta(days=1)
    else:
        current_mtd_start, current_mtd_end = month_start, fair_end
        current_mtd = _aggregate(current_mtd_start, current_mtd_end)
        previous_mtd_start = _previous_jalali_month_start(as_of)
        previous_mtd_end = _previous_jalali_same_day(fair_end)
        previous_mtd = _aggregate(previous_mtd_start, previous_mtd_end)

    top_keys = _top_previous_month_keys(as_of, 20)
    day_rows = _combined_rows(
        current_day, previous_same_day,
        partial=is_partial_day,
        top_keys=top_keys,
    )
    mtd_rows = _combined_rows(
        current_mtd, previous_mtd,
        partial=False,
        top_keys=top_keys,
    )

    # Fair pricing analysis: preserve the historical previous-period profit, but
    # also show what that same previous-period sales mix would have earned using
    # today's Darma accounting cost. This isolates selling-price effect from COGS.
    current_cost = int(darma_cost_for(as_of) or 0)
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
            "pct": _pct_change(row["current"]["profit"], adjusted_previous_profit),
        }

    # cumulative complete-day chart
    labels, current_cum, previous_cum, current_profit_cum, previous_profit_cum = [], [], [], [], []
    if fair_end >= month_start:
        cur_sales = prev_sales = cur_profit = prev_profit = 0
        current_days = current_mtd["days"]
        previous_days = previous_mtd["days"]
        d = month_start
        while d <= fair_end:
            p = _previous_jalali_same_day(d)
            cur_sales += int(current_days.get(d, {}).get("gross", 0))
            prev_sales += int(previous_days.get(p, {}).get("gross", 0))
            cur_profit += int(current_days.get(d, {}).get("profit", 0))
            prev_profit += int(previous_days.get(p, {}).get("profit", 0))
            labels.append(format_jalali(d)[8:10])
            current_cum.append(cur_sales)
            previous_cum.append(prev_sales)
            current_profit_cum.append(cur_profit)
            previous_profit_cum.append(prev_profit)
            d += timedelta(days=1)

    return {
        "as_of": as_of,
        "as_of_j": format_jalali(as_of),
        "previous_day": previous_day,
        "previous_day_j": format_jalali(previous_day),
        "is_partial_day": is_partial_day,
        "day_current": current_day,
        "day_previous": previous_same_day,
        "day_rows": day_rows,
        "mtd_current": current_mtd,
        "mtd_previous": previous_mtd,
        "mtd_rows": mtd_rows,
        "mtd_start_j": format_jalali(current_mtd_start),
        "mtd_end_j": format_jalali(current_mtd_end) if current_mtd_end >= current_mtd_start else "—",
        "previous_mtd_start_j": format_jalali(previous_mtd_start),
        "previous_mtd_end_j": format_jalali(previous_mtd_end) if previous_mtd_end >= previous_mtd_start else "—",
        "top_keys": top_keys,
        "price_history": (history := _price_history()) if include_evaluations else [],
        "evaluations": (
            _latest_price_evaluations(as_of, history=history)
            if include_evaluations else []
        ),
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
    """Lightweight dashboard card: avoid MTD, price-history and 10-day scans."""
    as_of = as_of or date.today()
    prev_date = _previous_jalali_same_day(as_of)
    current_day = _aggregate(as_of, as_of)
    previous_day = _aggregate(prev_date, prev_date)
    top_keys = _top_previous_month_keys(as_of, 20)
    return {
        "pricing_monitor": {
            "as_of_j": format_jalali(as_of),
            "previous_day_j": format_jalali(prev_date),
            "is_partial_day": as_of == date.today(),
            "rows": _combined_rows(
                current_day, previous_day,
                partial=as_of == date.today(), top_keys=top_keys,
            )[:8],
            "current_total": current_day["total"],
            "previous_total": previous_day["total"],
        }
    }


def _requested_as_of(request):
    raw = (request.GET.get("date") or "").strip()
    if not raw:
        return date.today(), ""
    try:
        value = parse_jalali_date(raw)
    except ValueError:
        return date.today(), "تاریخ نامعتبر بود؛ گزارش امروز نمایش داده شد."
    if value > date.today():
        return date.today(), "تاریخ آینده قابل گزارش نیست؛ گزارش امروز نمایش داده شد."
    return value, ""


@login_required
def pricing_monitor(request):
    as_of, date_warning = _requested_as_of(request)
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
    return render(request, "core/pricing_monitor_v88.html", data)


def _comparison_sheet_rows(rows):
    result = []
    for r in rows:
        result.append([
            r["code"], r["size"], r["pack_qty"],
            r["current"]["packs"], r["previous"]["packs"],
            r["packs_delta"]["value"], r["packs_delta"]["pct"],
            r["current"]["gross"], r["previous"]["gross"],
            r["gross_delta"]["value"], r["gross_delta"]["pct"],
            r["current"]["profit"], r["previous"]["profit"],
            r["profit_delta"]["value"], r["profit_delta"]["pct"],
            r["current"]["margin"], r["previous"]["margin"], r["margin_delta_pp"],
            r["current"]["avg_pack_price"], r["previous"]["avg_pack_price"],
            r["current"]["avg_short_price"], r["previous"]["avg_short_price"],
            r["current_share"], r["previous_share"], r["share_delta_pp"],
        ])
    return result


@login_required
def pricing_monitor_xlsx(request):
    as_of, _ = _requested_as_of(request)
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
        ["روز مشابه ماه قبل", data["previous_day_j"]],
        ["وضعیت روز جاری", "در حال تکمیل" if data["is_partial_day"] else "کامل"],
        ["بازه تجمعی فعلی", f'{data["mtd_start_j"]} تا {data["mtd_end_j"]}'],
        ["بازه تجمعی قبل", f'{data["previous_mtd_start_j"]} تا {data["previous_mtd_end_j"]}'],
        ["بهای فعلی هر شورت دارما", data["current_cost"]],
        ["مبنای سود", "sale_line_metrics + SaleSnapshot تاریخی"],
        ["فروش اعتباری", data["credit_note"]],
        ["قاعده روز جاری", "عدد خام نمایش داده می‌شود ولی درصد مقایسه روز ناقص تا پایان روز محاسبه نمی‌شود."],
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

    sheets = [
        Sheet("خلاصه مدیریتی", ["شاخص", "مقدار"], summary, widths=(34, 92), money_columns=(2,)),
        Sheet("مقایسه روز مشابه", headers, _comparison_sheet_rows(day_rows),
              widths=(18,12,12,14,14,14,14,20,20,20,16,20,20,20,16,14,14,18,22,22,20,20,16,16,18),
              money_columns=(8,9,10,12,13,14,19,20,21,22),
              percent_columns=(7,11,15,16,17,18,23,24,25)),
        Sheet("مقایسه تجمعی", headers, _comparison_sheet_rows(mtd_rows),
              widths=(18,12,12,14,14,14,14,20,20,20,16,20,20,20,16,14,14,18,22,22,20,20,16,16,18),
              money_columns=(8,9,10,12,13,14,19,20,21,22),
              percent_columns=(7,11,15,16,17,18,23,24,25)),
        Sheet("تاریخچه قیمت", ["کد","سایز","تعداد در پک","تاریخ اجرا","قیمت قبلی","قیمت جدید","تغییر ٪"],
              history_rows, widths=(20,12,14,18,22,22,16), money_columns=(5,6), percent_columns=(7,)),
        Sheet("ارزیابی ۱۰ روزه", [
            "کد","سایز","شروع قیمت","روز کامل","پک فعلی","پک قبل","تغییر پک ٪",
            "سود واقعی فعلی","سود واقعی قبل","تغییر سود واقعی ٪",
            "سود قبل با هزینه فعلی","تغییر سود تعدیل‌شده ٪","وضعیت",
        ], evaluation_rows, widths=(18,12,18,14,14,14,16,22,22,18,24,20,28),
           money_columns=(8,9,11), percent_columns=(7,10,12)),
    ]
    payload = make_workbook(sheets)
    response = HttpResponse(
        payload,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="darma-pricing-monitor.xlsx"'
    response["Cache-Control"] = "no-store"
    return response
