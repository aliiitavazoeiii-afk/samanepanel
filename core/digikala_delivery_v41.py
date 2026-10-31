from urllib.parse import urlencode

from django.core.cache import cache

from .digikala_client_v40 import DigikalaAPIError, get_json


DELIVERY_CACHE_KEY = "digikala-v41-delivery-board"
DELIVERY_CACHE_SECONDS = 30


def _int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _data(response):
    if not isinstance(response, dict):
        return {}
    value = response.get("data")
    return value if isinstance(value, dict) else {}


def _extract_size(title):
    known = {"M", "L", "XL", "XXL", "3XL", "4XL", "36-38", "38-40", "40-42", "42-44", "44-46"}
    for part in (title or "").split("|"):
        value = part.strip()
        if value in known:
            return value
    return "—"


def _commitment_rows():
    page = 1
    rows = []
    while True:
        query = urlencode({
            "page": page,
            "size": 50,
            "sort": "variant_id",
            "order": "asc",
        })
        response = get_json(f"/open-api/v1/commitments?{query}")
        data = _data(response)
        items = data.get("items")
        if isinstance(items, list):
            rows.extend(items)
        pager = data.get("pager") if isinstance(data.get("pager"), dict) else {}
        total_pages = max(_int(pager.get("total_pages")), 1)
        if page >= total_pages:
            break
        page += 1
        if page > 20:
            raise DigikalaAPIError("تعداد صفحات تعهدات دیجی‌کالا غیرمنتظره است؛ خواندن متوقف شد.")
    return rows


def get_delivery_board(*, force=False):
    if not force:
        cached = cache.get(DELIVERY_CACHE_KEY)
        if cached:
            return cached

    metadata = _data(get_json("/open-api/v1/commitments/metadata"))
    summary = metadata.get("summary_statistics")
    summary = summary if isinstance(summary, dict) else {}
    rows = _commitment_rows()

    delivery_rows = []
    future_total = 0
    today_total = 0
    delayed_total = 0
    all_rows_total = 0

    for row in rows:
        if not isinstance(row, dict):
            continue
        commitment = row.get("commitment")
        commitment = commitment if isinstance(commitment, dict) else {}
        future = _int(commitment.get("nextDays"))
        today = _int(commitment.get("today"))
        delayed = _int(commitment.get("delayed"))
        all_qty = _int(commitment.get("all"))
        due = future + today

        future_total += future
        today_total += today
        delayed_total += delayed
        all_rows_total += all_qty

        if due <= 0:
            continue

        title = str(row.get("titleFa") or "—")
        delivery_rows.append({
            "variant_id": row.get("variantId"),
            "supplier_code": row.get("supplierCode") or "—",
            "title": title,
            "size": _extract_size(title),
            "due_qty": due,
            "future_qty": future,
            "today_qty": today,
            "delayed_qty": delayed,
            "orders": _int(row.get("orders")),
            "on_the_way": _int(row.get("onTheWay")),
            "product_image": row.get("product_image") or "",
            "product_link": row.get("product_link") or "",
        })

    delivery_rows.sort(key=lambda item: (-item["due_qty"], str(item["supplier_code"]), str(item["variant_id"])))

    effective_total = _int(summary.get("effectiveCommitments"))
    total_commitments = _int(summary.get("totalCommitments")) or all_rows_total
    non_effective_total = _int(summary.get("nonEffectiveCommitments"))
    actionable_rows_total = future_total + today_total

    board = {
        "effective_total": effective_total or actionable_rows_total,
        "total_commitments": total_commitments,
        "non_effective_total": non_effective_total,
        "future_total": future_total,
        "today_total": today_total,
        "delayed_total": delayed_total,
        "actionable_rows_total": actionable_rows_total,
        "variant_count": len(delivery_rows),
        "rows": delivery_rows,
        "counts_match": (effective_total == 0 or effective_total == actionable_rows_total),
        "commitment_dates": metadata.get("commitment_dates") if isinstance(metadata.get("commitment_dates"), list) else [],
        "effective_last_updated": summary.get("effectiveLastUpdated"),
    }
    cache.set(DELIVERY_CACHE_KEY, board, DELIVERY_CACHE_SECONDS)
    return board
