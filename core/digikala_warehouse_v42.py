from django.core.cache import cache
from django.utils import timezone

from .digikala_shared_v44 import get_commitment_rows, get_inventory_rows


WAREHOUSE_CACHE_KEY = "digikala-v42-free-warehouse"
WAREHOUSE_CACHE_SECONDS = 300


def _int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _extract_size(title):
    known = {
        "M", "L", "XL", "XXL", "3XL", "4XL",
        "36-38", "38-40", "40-42", "42-44", "44-46", "46-48",
    }
    for part in (title or "").split("|"):
        value = part.strip()
        if value in known:
            return value
    return "—"


def _commitment_map(*, force=False):
    result = {}
    for row in get_commitment_rows(force=force):
        variant_id = _int(row.get("variantId"))
        if not variant_id:
            continue
        commitment = row.get("commitment")
        commitment = commitment if isinstance(commitment, dict) else {}
        result[variant_id] = _int(commitment.get("all"))
    return result


def get_free_warehouse_board(*, force=False):
    """Return current free/sellable Digikala warehouse stock without internal writes."""
    if not force:
        cached = cache.get(WAREHOUSE_CACHE_KEY)
        if cached is not None:
            return cached

    commitments = _commitment_map(force=force)
    inventories = get_inventory_rows(force=force)

    rows = []
    sellable_total = 0
    reserved_total = 0
    free_total = 0
    reserve_over_stock_total = 0

    for item in inventories:
        variant_id = _int(item.get("product_variant_id"))
        if not variant_id:
            continue

        marketplace = _int(item.get("marketplace_seller_stock"))
        available = _int(item.get("available"))
        reserve = _int(item.get("reserve"))
        seller_commitment = commitments.get(variant_id, 0)

        sellable_stock = max(0, available - marketplace + reserve)
        requested_dk_reserve = max(0, reserve - seller_commitment)
        reserved_from_stock = min(sellable_stock, requested_dk_reserve)
        free_stock = max(0, sellable_stock - reserved_from_stock)
        reserve_over_stock = max(0, requested_dk_reserve - sellable_stock)

        if sellable_stock <= 0:
            continue

        title = str(item.get("title") or "—")
        row = {
            "variant_id": variant_id,
            "supplier_code": item.get("supplier_code") or "—",
            "title": title,
            "size": _extract_size(title),
            "product_image": item.get("img_src") or "",
            "product_link": item.get("product_url") or "",
            "sellable_stock": sellable_stock,
            "reserved_stock": reserved_from_stock,
            "free_stock": free_stock,
            "requested_dk_reserve": requested_dk_reserve,
            "reserve_over_stock": reserve_over_stock,
            "seller_commitment": seller_commitment,
            "raw_reserve": reserve,
            "warehouse_stock": _int(item.get("warehouse_stock")),
            "status": "free" if free_stock > 0 else "zero",
        }
        rows.append(row)
        sellable_total += sellable_stock
        reserved_total += reserved_from_stock
        free_total += free_stock
        reserve_over_stock_total += reserve_over_stock

    rows.sort(
        key=lambda row: (
            0 if row["free_stock"] > 0 else 1,
            -row["free_stock"],
            -row["sellable_stock"],
            str(row["supplier_code"]),
            str(row["title"]),
        )
    )

    board = {
        "rows": rows,
        "sellable_total": sellable_total,
        "reserved_total": reserved_total,
        "free_total": free_total,
        "variant_count": len(rows),
        "free_variant_count": sum(1 for row in rows if row["free_stock"] > 0),
        "zero_variant_count": sum(1 for row in rows if row["free_stock"] == 0),
        "reserve_over_stock_total": reserve_over_stock_total,
        "inventory_rows_scanned": len(inventories),
        "commitment_variant_count": len(commitments),
        "updated_at": timezone.localtime().isoformat(),
    }
    cache.set(WAREHOUSE_CACHE_KEY, board, WAREHOUSE_CACHE_SECONDS)
    return board
