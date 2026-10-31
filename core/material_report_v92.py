from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import jdatetime
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from . import material_report_v23 as v23
from .models import MaterialReportBlock


JALALI_MONTH_NAMES = {
    1: "فروردین",
    2: "اردیبهشت",
    3: "خرداد",
    4: "تیر",
    5: "مرداد",
    6: "شهریور",
    7: "مهر",
    8: "آبان",
    9: "آذر",
    10: "دی",
    11: "بهمن",
    12: "اسفند",
}


def _decimal(value):
    raw = str(value or "").strip().replace("٬", "").replace(",", ".")
    if not raw:
        return Decimal("0")
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _jalali_month_context(today=None):
    today = today or date.today()
    current = jdatetime.date.fromgregorian(date=today)
    start_j = jdatetime.date(current.year, current.month, 1)
    if current.month == 12:
        next_j = jdatetime.date(current.year + 1, 1, 1)
    else:
        next_j = jdatetime.date(current.year, current.month + 1, 1)
    return {
        "year": int(current.year),
        "month": int(current.month),
        "key": f"{current.year:04d}/{current.month:02d}",
        "label": f"{JALALI_MONTH_NAMES[current.month]} {current.year}",
        "start": start_j.togregorian(),
        "next": next_j.togregorian(),
    }


def _format_weight(value):
    value = Decimal(value or 0).quantize(Decimal("0.001"))
    text = format(value, "f").rstrip("0").rstrip(".")
    return text or "0"


def _summarize_month_blocks(blocks):
    fabric_codes = set()
    uncoded_rolls = 0
    total_weight = Decimal("0")
    total_cut = 0
    total_delivered = 0
    total_applied = 0
    # Net overproduction and shortages between ROLLS of the SAME color.
    # Different colors or brands must not silently settle each other.
    by_brand_color = {}

    for block in blocks:
        active_keys = v23._active_model_keys(block)
        registered = _registered_output_by_key(block)
        block_cut = 0

        for key in active_keys:
            values = (block.input_data or {}).get(key, {}) or {}
            code = str(values.get("fabric_code") or "").strip()
            weight = max(_decimal(values.get("weight")), Decimal("0"))
            cut = max(0, v23.v20._int(values.get("cut")))

            if code:
                fabric_codes.add(code)
            elif weight > 0:
                # A positive-weight row without a fabric code still represents
                # one delivered roll for the monthly operational summary.
                uncoded_rolls += 1

            total_weight += weight
            block_cut += cut
            group = (getattr(block.brand, "name", ""), key)
            prev_cut, prev_received = by_brand_color.get(group, (0, 0))
            by_brand_color[group] = (
                prev_cut + cut, prev_received + registered.get(key, 0)
            )

        block_delivered = sum(registered.values())
        block_applied = sum(
            max(0, int(row.quantity or 0))
            for row in block.output_applications.all()
        )
        total_cut += block_cut
        total_delivered += block_delivered
        total_applied += block_applied

    total_pending = sum(
        max(0, cut - received) for cut, received in by_brand_color.values()
    )
    total_surplus = sum(
        max(0, received - cut) for cut, received in by_brand_color.values()
    )
    return {
        "roll_count": len(fabric_codes) + uncoded_rolls,
        "weight": total_weight,
        "weight_display": _format_weight(total_weight),
        "minimum_delivery": int(total_cut),
        "delivered": int(total_delivered),
        "applied": int(total_applied),
        "pending": int(total_pending),
        "surplus": int(total_surplus),
        "block_count": len(blocks),
    }


def _fabric_not_applied(block, key):
    """True only for a real fabric-input row without a positive color-specific consumption."""
    values = (block.input_data or {}).get(key, {}) or {}
    meaningful = (
        str(values.get("fabric_code") or "").strip()
        or _decimal(values.get("weight")) > 0
        or v23.v20._int(values.get("cut")) > 0
    )
    if not meaningful:
        return False
    return not any(
        row.kind == v23.FABRIC
        and row.material_key == key
        and _decimal(row.quantity) > 0
        for row in block.stock_consumptions.all()
    )


def _registered_output_by_key(block):
    """Saved delivery entries, even before stock/output synchronization.

    Output applications are separately reported. A delivery the operator
    entered is not automatically 'applied', and must not disappear from
    physical-delivery progress simply because synchronization is pending.
    """
    brand = block.brand
    sizes = v23._output_sizes_for_brand(brand)
    keys = v23._active_model_keys(block)
    values = block.output_data or {}
    return {
        key: sum(
            max(0, v23.v20._int((values.get(key) or {}).get(size_key)))
            for size_key, _ in sizes
        )
        for key in keys
    }


def _color_delivery_unsynced(block, key):
    """Even equal grand totals can hide a wrong-size pending stock update."""
    values = (block.output_data or {}).get(key) or {}
    applied_by_size = {
        row.size_key: max(0, int(row.quantity or 0))
        for row in block.output_applications.all()
        if row.model_key == key
    }
    return any(
        max(0, v23.v20._int(values.get(size_key))) != applied_by_size.get(size_key, 0)
        for size_key, _ in v23._output_sizes_for_brand(block.brand)
    )


def _block_operational_status(block):
    """Unfinished material or delivery work carries into the next Jalali month.

    Do not 'close' a previous sheet only because some other color's
    materials were applied. Do not use the month of stock sync: the sheet
    date is the accounting period; open sheets carry until finished.
    """
    keys = v23._active_model_keys(block)
    registered = _registered_output_by_key(block)
    for key in keys:
        cut = max(0, v23.v20._int(((block.input_data or {}).get(key) or {}).get("cut")))
        if cut > registered.get(key, 0):
            return True
        if _color_delivery_unsynced(block, key):
            return True
        if _fabric_not_applied(block, key):
            return True
    return False


def _operational_month_blocks(blocks, month):
    """Current Jalali month + only unfinished sheets carried from older months."""
    start, next_month = month["start"], month["next"]
    return [
        block for block in blocks
        if (start <= block.date < next_month)
        or (block.date < start and _block_operational_status(block))
    ]


def _net_color_progress(blocks):
    """Net signed shortfalls/surpluses ACROSS sheets before zero-clamping.

    Example: two pink rolls each cut 750; deliveries 998 and 540.
    Net target=1500, received=1538, pending=0, surplus=38.
    The prior per-sheet max(0, cut-delivered) incorrectly said 210 pending.
    """
    result = {}
    for key, _ in v23.BASE_MODELS:
        cut = registered = applied = 0
        open_blocks = 0
        for block in blocks:
            if getattr(block.brand, "name", "") != "دارما":
                continue
            values = (block.input_data or {}).get(key, {}) or {}
            expected_row = max(0, v23.v20._int(values.get("cut")))
            registered_row = _registered_output_by_key(block).get(key, 0)
            applied_row = sum(
                max(0, int(a.quantity or 0))
                for a in block.output_applications.all()
                if a.model_key == key
            )
            cut += expected_row
            registered += registered_row
            applied += applied_row
            if (expected_row > registered_row or _color_delivery_unsynced(block, key)
                    or _fabric_not_applied(block, key)):
                open_blocks += 1
        balance = registered - cut
        result[key] = {
            "expected": cut,
            "delivered": registered,
            "applied": applied,
            "pending": max(0, -balance),
            "surplus": max(0, balance),
            "net_delta": balance,
            "open_blocks": open_blocks,
        }
    return result


BASE_COLOR_PROGRESS = tuple(v23.BASE_MODELS)


def _summarize_open_base_colors(blocks):
    """Five Darma cards: unique unapplied fabric codes and all-time input weight.

    A roll is eligible only when its saved color row has a nonempty fabric
    code and NO positive, recorded FABRIC consumption for that same block and
    color. A sewing output application does not mark raw materials as used.
    The total entered weight is an independent all-time input figure and must
    include both applied and unapplied sheets (but never another brand).

    Existing expected/delivered/pending output-work metrics are unchanged.
    """
    rows = []
    for key, label in BASE_COLOR_PROGRESS:
        expected = delivered = pending = open_blocks = 0
        unapplied_codes = set()
        missing_codes = 0
        total_weight = Decimal("0")
        for block in blocks:
            if getattr(block.brand, "name", "") != "دارما":
                continue
            values = ((block.input_data or {}).get(key) or {})
            code = str(values.get("fabric_code") or "").strip()
            cut = max(0, v23.v20._int(values.get("cut")))
            weight = max(_decimal(values.get("weight")), Decimal("0"))
            total_weight += weight

            # Material-report stock-consumption records are color-specific.
            # Do not conflate applying delivered finished goods with applying
            # fabric input, and do not exclude an entire multi-color report
            # just because ANOTHER color's raw materials were applied.
            fabric_applied = any(
                row.kind == v23.FABRIC
                and row.material_key == key
                and _decimal(row.quantity) > 0
                for row in block.stock_consumptions.all()
            )
            if not fabric_applied:
                if code:
                    unapplied_codes.add(code)
                elif weight > 0 or cut > 0:
                    missing_codes += 1

            applied = sum(
                max(0, int(item.quantity or 0))
                for item in block.output_applications.all()
                if item.model_key == key
            )
            if cut <= applied:
                continue
            expected += cut
            delivered += applied
            pending += cut - applied
            open_blocks += 1

        rows.append({
            "key": key,
            "label": label,
            "roll_count": len(unapplied_codes),
            "rolls_without_code": int(missing_codes),
            "total_weight": total_weight,
            "total_weight_display": _format_weight(total_weight),
            "expected": int(expected),
            "delivered": int(delivered),
            "pending": int(pending),
            "open_blocks": int(open_blocks),
        })
    return rows

def _current_unapplied_material_metrics(blocks):
    """Read-side metrics: only current-month colors with raw fabric NOT applied.

    Shortfalls/surpluses net across rolls of the same brand/color only.
    """
    rows = {}
    for block in blocks:
        brand = getattr(block.brand, "name", "")
        registered = _registered_output_by_key(block)
        for key in v23._active_model_keys(block):
            if not _fabric_not_applied(block, key):
                continue
            values = (block.input_data or {}).get(key, {}) or {}
            group = rows.setdefault((brand, key), {
                "codes": set(), "uncoded": 0, "weight": Decimal("0"),
                "cut": 0, "delivered": 0, "applied": 0, "cut_entries": 0,
            })
            code = str(values.get("fabric_code") or "").strip()
            weight = max(_decimal(values.get("weight")), Decimal("0"))
            cut = max(0, v23.v20._int(values.get("cut")))
            if code:
                group["codes"].add(code)
            elif weight > 0:
                group["uncoded"] += 1
            group["weight"] += weight
            group["cut"] += cut
            group["delivered"] += registered.get(key, 0)
            group["applied"] += sum(
                max(0, int(row.quantity or 0))
                for row in block.output_applications.all()
                if row.model_key == key
            )
            group["cut_entries"] += int(cut > 0)

    empty = {"codes": set(), "uncoded": 0, "weight": Decimal("0"),
             "cut": 0, "delivered": 0, "applied": 0, "cut_entries": 0}
    summary = {
        "roll_count": sum(len(x["codes"]) + x["uncoded"] for x in rows.values()),
        "weight": sum((x["weight"] for x in rows.values()), Decimal("0")),
        "minimum_delivery": sum(x["cut"] for x in rows.values()),
        "delivered": sum(x["delivered"] for x in rows.values()),
        "applied": sum(x["applied"] for x in rows.values()),
        "pending": sum(max(0, x["cut"] - x["delivered"]) for x in rows.values()),
        "surplus": sum(max(0, x["delivered"] - x["cut"]) for x in rows.values()),
    }
    summary["weight_display"] = _format_weight(summary["weight"])
    base = {}
    for key, _ in v23.BASE_MODELS:
        x = rows.get(("دارما", key), empty)
        signed = x["delivered"] - x["cut"]
        base[key] = {
            "roll_count": len(x["codes"]),
            "rolls_without_code": x["uncoded"],
            "total_weight": x["weight"],
            "total_weight_display": _format_weight(x["weight"]),
            "expected": x["cut"], "delivered": x["delivered"],
            "applied": x["applied"],
            "pending": max(0, -signed), "surplus": max(0, signed),
            "net_delta": signed, "open_blocks": x["cut_entries"],
        }
    base_rows = [rows.get(("دارما", key), empty) for key, _ in v23.BASE_MODELS]
    cut_total = sum(x["cut"] for x in base_rows)
    count = sum(x["cut_entries"] for x in base_rows)
    average = (
        int((Decimal(cut_total) / Decimal(count)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )) if count else 0
    )
    return summary, base, {
        "average_cut": average, "cut_entry_count": count, "cut_total": cut_total,
    }


def _all_time_cut_summary(blocks):
    """Average saved cut per Darma base-color for the supplied sheet scope.

    V122 calls this with current month + unfinished older sheets only.
    Historical roll weight and number code auditing remains independent.
    """
    total = 0
    count = 0
    allowed = set(v23.BASE_KEYS)
    for block in blocks:
        if getattr(block.brand, "name", "") != "دارما":
            continue
        input_data = block.input_data or {}
        for key in allowed:
            values = input_data.get(key, {}) or {}
            cut = max(0, v23.v20._int(values.get("cut")))
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
    return {
        "average_cut": average,
        "cut_entry_count": count,
        "cut_total": total,
    }


def _all_month_color_delivery_metrics(blocks):
    """Live as-of-now cut and delivered amounts for ALL colors of this month.

    Unlike top-of-page material-unapplied KPIs, this separate archived-month
    breakdown includes already-applied fabric: applying fabric must NOT erase
    an outstanding sewing delivery from the historic month's report.
    Net quantities across rolls of the same color before clamping, never
    allow a surplus in a different color to cover a deficit.
    """
    groups = {}
    for block in blocks:
        if getattr(block.brand, "name", "") != "دارما":
            continue
        received = _registered_output_by_key(block)
        output_applied = {}
        for row in block.output_applications.all():
            output_applied[row.model_key] = (
                output_applied.get(row.model_key, 0)
                + max(0, int(row.quantity or 0))
            )
        for key in v23._active_model_keys(block):
            values = (block.input_data or {}).get(key, {}) or {}
            cut = max(0, v23.v20._int(values.get("cut")))
            entered = received.get(key, 0)
            applied = output_applied.get(key, 0)
            if not cut and not entered and not applied:
                continue
            entry = groups.setdefault(key, {
                "key": key, "label": v23._material_label(key),
                "expected": 0, "delivered": 0, "applied": 0,
            })
            entry["expected"] += cut
            entry["delivered"] += entered
            entry["applied"] += applied

    results = []
    for row in groups.values():
        delta = row["delivered"] - row["expected"]
        row["pending"] = max(0, -delta)
        row["surplus"] = max(0, delta)
        results.append(row)
    order = {key: idx for idx, (key, _) in enumerate(v23.BASE_MODELS)}
    results.sort(key=lambda row: (order.get(row["key"], len(order)), row["label"]))
    return {
        "rows": results,
        "expected": sum(x["expected"] for x in results),
        "delivered": sum(x["delivered"] for x in results),
        "applied": sum(x["applied"] for x in results),
        "pending": sum(x["pending"] for x in results),
        "surplus": sum(x["surplus"] for x in results),
    }


def _selected_month_context(requested_key, current_month, blocks):
    """Accept only months belonging to a saved sheet, never arbitrary URL dates."""
    available = {row["month_key"] for row in blocks if row.get("month_key")}
    if not requested_key or requested_key == current_month["key"]:
        return current_month
    if requested_key not in available or requested_key > current_month["key"]:
        return current_month
    try:
        jy, jm = (int(value) for value in requested_key.split("/"))
        first_day = jdatetime.date(jy, jm, 1).togregorian()
    except (ValueError, TypeError, OverflowError):
        return current_month
    return _jalali_month_context(first_day)


def _decorate_block_month(row):
    parts = str(row.get("jalali_date") or "").split("/")
    if len(parts) >= 2:
        try:
            year = int(parts[0])
            month = int(parts[1])
        except (TypeError, ValueError):
            return row
        row["month_key"] = f"{year:04d}/{month:02d}"
        row["month_label"] = f"{JALALI_MONTH_NAMES.get(month, month)} {year}"
    return row


@login_required
def material_report(request):
    """V92: V23 material report with current-month KPIs and previous-month UI archive."""
    if request.method == "POST":
        # Creation semantics stay exactly on V23.
        return v23.material_report(request)

    v23._reset_request_caches()
    brands = v23.v20._material_brands()
    current_month = _jalali_month_context()

    queryset = MaterialReportBlock.objects.select_related("brand").prefetch_related(
        "output_applications", "stock_consumptions"
    )
    objects = list(queryset.all())
    blocks = [_decorate_block_month(v23._view_block(obj)) for obj in objects]
    month = _selected_month_context(
        (request.GET.get("report_month") or "").strip(), current_month, blocks
    )

    # Keep V123's strict single-month/unapplied-fabric KPI definition, but
    # permit an explicitly selected archived month. Nothing carries into NOW.
    selected_month_objects = [
        obj for obj in objects if month["start"] <= obj.date < month["next"]
    ]
    summary, by_color, cut_summary = _current_unapplied_material_metrics(
        selected_month_objects
    )
    summary["month_label"] = month["label"]
    is_archived = month["key"] != current_month["key"]
    archive_deliveries = (
        _all_month_color_delivery_metrics(selected_month_objects)
        if is_archived else None
    )
    base_color_progress = [
        {"key": key, "label": label, **by_color[key]}
        for key, label in v23.BASE_MODELS
    ]

    return render(
        request,
        "core/material_report_v92.html",
        {
            "blocks": blocks,
            "brands": brands,
            "today_j": v23.v20._today_jalali(),
            "sewing_wage_rate": v23.v20._dozen_wage(),
            "material_month_summary": summary,
            "material_cut_summary": cut_summary,
            "material_base_color_progress": base_color_progress,
            "material_current_month_key": current_month["key"],
            "material_current_month_label": current_month["label"],
            "material_selected_month_key": month["key"],
            "material_selected_month_label": month["label"],
            "material_selected_is_archive": is_archived,
            "material_archive_deliveries": archive_deliveries,
        },
    )
