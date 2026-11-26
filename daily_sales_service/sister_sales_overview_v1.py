"""Read-only, single-source sales aggregates for the sister panel.

All channels come from sister_finance_logic.sale_lines, including dispatched
mold invoices. Unknown cost makes profit unknown, never an invented zero.
Amounts are Toman. No inventory, sale, or finance record is mutated here.
"""
from collections import defaultdict

from .effective_costs import valid_date
from .sister_finance_logic import PLATFORM_KEYS, sale_lines

FIELDS = ("orders", "packs", "units", "gross", "fees", "net", "cogs_known", "unknown_cost_lines")
LABELS = {"digikala": "دیجی‌کالا", "site": "سایت", "basalam": "باسلام", "mold": "قالب و فاکتور"}


def _empty():
    return {**{field: 0 for field in FIELDS}, "profit": 0}


def _accumulate(total, line):
    total["orders"] += 1
    total["packs"] += int(line["packs"])
    total["units"] += int(line["units"])
    total["gross"] += int(line["gross"])
    total["fees"] += int(line["fees"])
    total["net"] += int(line["net"])
    if line["cogs"] is None:
        total["unknown_cost_lines"] += 1
    else:
        total["cogs_known"] += int(line["cogs"])


def _finish(total):
    total["profit"] = (
        None if total["unknown_cost_lines"]
        else total["net"] - total["cogs_known"]
    )
    return total


def sales_overview(conn, start, end, channel=""):
    start = valid_date(start)
    end = valid_date(end)
    if start > end:
        raise ValueError("تاریخ شروع بعد از تاریخ پایان است.")
    if channel and channel not in PLATFORM_KEYS:
        raise ValueError("پلتفرم نامعتبر است.")

    source_lines = sale_lines(
        conn, channel=channel or None, from_date=start, to_date=end,
        include_invoices=True
    )
    total = _empty()
    channels = defaultdict(_empty)
    days = defaultdict(_empty)
    day_channels = defaultdict(_empty)
    for line in source_lines:
        source = line["source"]
        day = line["sale_date"]
        _accumulate(total, line)
        _accumulate(channels[source], line)
        _accumulate(days[day], line)
        _accumulate(day_channels[(day, source)], line)

    return {
        "start": start,
        "end": end,
        "channel": channel,
        "total": _finish(total),
        "channels": [
            {"source": key, "label": LABELS[key], **_finish(value)}
            for key, value in sorted(channels.items())
        ],
        "days": [
            {"date": key, **_finish(value)}
            for key, value in sorted(days.items())
        ],
        "day_channels": [
            {"date": day, "source": source, "label": LABELS[source], **_finish(value)}
            for (day, source), value in sorted(day_channels.items(), reverse=True)
        ],
    }
