from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

import jdatetime
from django.core.cache import cache
from django.utils import timezone

from .digikala_client_v40 import DigikalaAPIError, get_json
from .digikala_shared_v44 import get_commitment_rows, get_inventory_rows, paginated_get


ORDERS_CACHE_KEY = "digikala-v44-daily-orders"
PACKAGES_CACHE_KEY = "digikala-v44-packages"
SALES_CACHE_KEY = "digikala-v44-sales"
RETURNS_CACHE_KEY = "digikala-v44-returns"
PRODUCTS_CACHE_KEY = "digikala-v44-products"
ORDERS_CACHE_SECONDS = 180
PACKAGES_CACHE_SECONDS = 600
SALES_CACHE_SECONDS = 600
RETURNS_CACHE_SECONDS = 600
PRODUCTS_CACHE_SECONDS = 600


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


def _items(response):
    value = _data(response).get("items")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _extract_size(title):
    known = {
        "S", "M", "L", "XL", "XXL", "3XL", "4XL",
        "36-38", "38-40", "40-42", "42-44", "44-46", "46-48",
    }
    for part in str(title or "").split("|"):
        value = part.strip()
        if value in known:
            return value
    return "—"


def _product_name(title, supplier_code=None):
    text = str(title or "").strip()
    if text:
        first = text.split("|", 1)[0].strip()
        if first:
            return first
    return str(supplier_code or "کالا")


def _jalali_label(value):
    if not isinstance(value, date):
        return "—"
    j = jdatetime.date.fromgregorian(date=value)
    return f"{j.year:04d}/{j.month:02d}/{j.day:02d}"


def _commitment_all_map(rows):
    result = {}
    for row in rows:
        variant_id = _int(row.get("variantId"))
        if not variant_id:
            continue
        commitment = row.get("commitment") if isinstance(row.get("commitment"), dict) else {}
        result[variant_id] = _int(commitment.get("all"))
    return result


def _filtered_commitments(cutoff):
    # Important: do NOT combine is_effective=true with a future cutoff. The official
    # API defines is_effective relative to today's performance date, which suppresses
    # future commitments and previously made tomorrow/day-after appear empty.
    return paginated_get(
        "/open-api/v1/commitments",
        params={
            "sort": "variant_id",
            "order": "asc",
            "search[to_commitment_date]": cutoff.isoformat(),
        },
        size=50,
        max_pages=20,
        timeout=7,
        workers=2,
    )


def _group_products(variant_rows, quantity_key):
    products = {}
    for row in variant_rows:
        qty = _int(row.get(quantity_key))
        if qty <= 0:
            continue
        product_id = _int(row.get("product_id"))
        variant_id = _int(row.get("variant_id"))
        product_key = product_id or f"variant-{variant_id}"
        product = products.get(product_key)
        if product is None:
            product = {
                "product_id": product_id,
                "name": row.get("product_name") or row.get("title") or "کالا",
                "image": row.get("product_image") or "",
                "link": row.get("product_link") or "",
                "total": 0,
                "variants": [],
            }
            products[product_key] = product
        product["total"] += qty
        product["variants"].append({
            "variant_id": variant_id,
            "supplier_code": row.get("supplier_code") or "—",
            "size": row.get("size") or "—",
            "title": row.get("title") or "—",
            "qty": qty,
        })
    result = list(products.values())
    for product in result:
        product["variants"].sort(
            key=lambda x: (str(x["size"]), str(x["supplier_code"]), x["variant_id"])
        )
    result.sort(key=lambda x: (-x["total"], x["name"]))
    return result


def get_daily_orders_center(*, force=False):
    if not force:
        cached = cache.get(ORDERS_CACHE_KEY)
        if cached is not None:
            return cached

    today = timezone.localdate()
    tomorrow = today + timedelta(days=1)
    day_after = today + timedelta(days=2)

    base_rows = get_commitment_rows(force=force)
    # Base row already gives delayed/today/nextDays. Only two future cumulative
    # reads are needed. Run them concurrently to cut page latency.
    maps = {}
    split_error = ""
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(_filtered_commitments, tomorrow): "tomorrow",
                executor.submit(_filtered_commitments, day_after): "day_after",
            }
            for future in as_completed(futures):
                maps[futures[future]] = _commitment_all_map(future.result())
    except DigikalaAPIError as exc:
        split_error = str(exc)
        maps = {}

    tomorrow_map = maps.get("tomorrow", {})
    day_after_map = maps.get("day_after", {})
    date_split_ok = not bool(split_error)
    split_issues = []
    variants = []

    for row in base_rows:
        variant_id = _int(row.get("variantId"))
        if not variant_id:
            continue
        commitment = row.get("commitment") if isinstance(row.get("commitment"), dict) else {}
        next_days = _int(commitment.get("nextDays"))
        today_qty = _int(commitment.get("today"))
        delayed_qty = _int(commitment.get("delayed"))
        all_qty = _int(commitment.get("all"))
        if next_days <= 0 and today_qty <= 0 and delayed_qty <= 0:
            continue

        if split_error:
            tomorrow_qty = 0
            day_after_qty = 0
            later_qty = next_days
        else:
            # all - nextDays is the cumulative past+today part already present in
            # the unfiltered row; this avoids a third filtered API scan.
            through_today = max(0, all_qty - next_days)
            through_tomorrow = tomorrow_map.get(variant_id, through_today)
            through_day_after = day_after_map.get(variant_id, through_tomorrow)
            tomorrow_qty = max(0, through_tomorrow - through_today)
            day_after_qty = max(0, through_day_after - through_tomorrow)
            if tomorrow_qty + day_after_qty > next_days:
                date_split_ok = False
                split_issues.append(variant_id)
                tomorrow_qty = 0
                day_after_qty = 0
                later_qty = next_days
            else:
                later_qty = max(0, next_days - tomorrow_qty - day_after_qty)

        title = str(row.get("titleFa") or "—")
        supplier_code = row.get("supplierCode") or "—"
        variants.append({
            "product_id": _int(row.get("productId")),
            "variant_id": variant_id,
            "supplier_code": supplier_code,
            "title": title,
            "product_name": _product_name(title, supplier_code),
            "size": _extract_size(title),
            "product_image": row.get("product_image") or "",
            "product_link": row.get("product_link") or "",
            "today_qty": today_qty,
            "tomorrow_qty": tomorrow_qty,
            "day_after_qty": day_after_qty,
            "later_qty": later_qty,
            "delayed_qty": delayed_qty,
            "future_qty": next_days,
        })

    board = {
        "today_date": today.isoformat(),
        "tomorrow_date": tomorrow.isoformat(),
        "day_after_date": day_after.isoformat(),
        "today_jalali": _jalali_label(today),
        "tomorrow_jalali": _jalali_label(tomorrow),
        "day_after_jalali": _jalali_label(day_after),
        "today_total": sum(x["today_qty"] for x in variants),
        "tomorrow_total": sum(x["tomorrow_qty"] for x in variants),
        "day_after_total": sum(x["day_after_qty"] for x in variants),
        "later_total": sum(x["later_qty"] for x in variants),
        "delayed_total": sum(x["delayed_qty"] for x in variants),
        "future_total": sum(x["future_qty"] for x in variants),
        "today_products": _group_products(variants, "today_qty"),
        "tomorrow_products": _group_products(variants, "tomorrow_qty"),
        "day_after_products": _group_products(variants, "day_after_qty"),
        "later_products": _group_products(variants, "later_qty"),
        "delayed_products": _group_products(variants, "delayed_qty"),
        "variant_count": len(variants),
        "date_split_ok": date_split_ok,
        "date_split_error": split_error,
        "split_issue_variants": split_issues[:20],
        "updated_at": timezone.localtime().isoformat(),
    }
    cache.set(ORDERS_CACHE_KEY, board, ORDERS_CACHE_SECONDS)
    return board


def _package_status(item):
    value = item.get("status")
    if isinstance(value, dict):
        return value.get("title") or value.get("text_fa") or value.get("key") or "—"
    return str(value or item.get("status_title") or item.get("package_status") or "—")


def _package_id(item):
    for key in ("package_id", "id", "packageId"):
        value = _int(item.get(key))
        if value:
            return value
    return 0


def _warehouse_title(value):
    if isinstance(value, dict):
        return str(value.get("title") or value.get("warehouse_title") or value.get("name") or "—")
    return str(value or "—")


def _try_paginated_candidates(candidates, *, size=50, max_pages=30):
    errors = []
    for path, params in candidates:
        try:
            rows = paginated_get(
                path,
                params=params,
                size=size,
                max_pages=max_pages,
                timeout=7,
                workers=3,
            )
            return path, rows, ""
        except DigikalaAPIError as exc:
            errors.append(f"{path}: {exc}")
    return "", [], " | ".join(errors)


def get_packages_board(*, force=False):
    if not force:
        cached = cache.get(PACKAGES_CACHE_KEY)
        if cached is not None:
            return cached

    source, rows, error = _try_paginated_candidates(
        [
            ("/open-api/v1/packages", {"sort": "created_at", "order": "desc"}),
            ("/open-api/v1/packages", None),
            ("/api/v3/packages", {"sort": "created_at", "order": "desc"}),
            ("/api/v3/packages", None),
        ],
        size=50,
        max_pages=30,
    )
    packages = []
    for item in rows:
        packages.append({
            "package_id": _package_id(item),
            "package_number": item.get("package_number") or "—",
            "type": _warehouse_title(item.get("type")),
            "status": _package_status(item),
            "created_at": item.get("created_at") or "—",
            "forecast_at": item.get("received_at_forecast") or item.get("delivery_date") or "—",
            "received_at": item.get("received_at") or "—",
            "warehouse": _warehouse_title(item.get("warehouse")),
            "item_count": _int(item.get("item_count") or item.get("items_count") or item.get("variant_count") or item.get("count")),
        })
    board = {
        "available": bool(source),
        "source": source,
        "error": error,
        "rows": packages,
        "total": len(packages),
        "updated_at": timezone.localtime().isoformat(),
    }
    cache.set(PACKAGES_CACHE_KEY, board, PACKAGES_CACHE_SECONDS)
    return board


def get_package_detail(package_id):
    errors = []
    for prefix in ("/open-api/v1/packages", "/api/v3/packages"):
        try:
            response = get_json(f"{prefix}/{int(package_id)}", timeout=7)
            data = _data(response)
            if not data:
                data = response if isinstance(response, dict) else {}
            return {"package_id": int(package_id), "status": _package_status(data), "raw": data, "source": prefix}
        except DigikalaAPIError as exc:
            errors.append(str(exc))
    raise DigikalaAPIError("جزئیات محموله دریافت نشد: " + " | ".join(errors))


def get_products_board(*, force=False):
    if not force:
        cached = cache.get(PRODUCTS_CACHE_KEY)
        if cached is not None:
            return cached
    inventories = get_inventory_rows(force=force)
    products = {}
    for item in inventories:
        product_id = _int(item.get("product_id"))
        variant_id = _int(item.get("product_variant_id"))
        if not product_id and not variant_id:
            continue
        key = product_id or f"variant-{variant_id}"
        title = str(item.get("title") or "—")
        product = products.get(key)
        if product is None:
            product = {
                "product_id": product_id,
                "name": _product_name(title, item.get("supplier_code")),
                "image": item.get("img_src") or "",
                "link": item.get("product_url") or "",
                "variants": [],
                "available_total": 0,
                "warehouse_total": 0,
            }
            products[key] = product
        available = _int(item.get("available"))
        warehouse = _int(item.get("warehouse_stock"))
        product["available_total"] += available
        product["warehouse_total"] += warehouse
        product["variants"].append({
            "variant_id": variant_id,
            "supplier_code": item.get("supplier_code") or "—",
            "size": _extract_size(title),
            "title": title,
            "available": available,
            "warehouse_stock": warehouse,
        })
    rows = list(products.values())
    rows.sort(key=lambda x: x["name"])
    board = {
        "rows": rows,
        "product_count": len(rows),
        "variant_count": len(inventories),
        "updated_at": timezone.localtime().isoformat(),
    }
    cache.set(PRODUCTS_CACHE_KEY, board, PRODUCTS_CACHE_SECONDS)
    return board


def _parse_api_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _order_datetime(row):
    for key in (
        "order_created_at", "created_at", "createdAt", "order_date", "orderDate",
        "warehouse_status_at", "updated_at",
    ):
        dt = _parse_api_datetime(row.get(key))
        if dt:
            return dt
    return None


def _jalali_month_bounds():
    local_today = timezone.localdate()
    jtoday = jdatetime.date.fromgregorian(date=local_today)
    jstart = jdatetime.date(jtoday.year, jtoday.month, 1)
    if jtoday.month == 12:
        jnext = jdatetime.date(jtoday.year + 1, 1, 1)
    else:
        jnext = jdatetime.date(jtoday.year, jtoday.month + 1, 1)
    return jstart.togregorian(), jnext.togregorian(), f"{jtoday.year}/{jtoday.month:02d}"


def get_sales_board(*, force=False):
    if not force:
        cached = cache.get(SALES_CACHE_KEY)
        if cached is not None:
            return cached

    source, rows, error = _try_paginated_candidates(
        [
            ("/open-api/v1/orders/history", None),
            ("/api/v3/orders/history", None),
            # V40 proved this route itself is available. Do not pass speculative
            # sort fields; older V43 did and could trigger validation failure.
            ("/open-api/v1/orders", None),
        ],
        size=100,
        max_pages=30,
    )
    if not source:
        raise DigikalaAPIError(error or "هیچ endpoint خواندنی سفارش پاسخ نداد.")

    start_date, next_month, jalali_month = _jalali_month_bounds()
    selected = []
    for row in rows:
        dt = _order_datetime(row)
        if dt is None:
            continue
        local_date = timezone.localtime(dt).date()
        if start_date <= local_date < next_month:
            selected.append((row, dt))

    products = defaultdict(lambda: {
        "product_id": 0,
        "name": "—",
        "quantity": 0,
        "rows": 0,
        "image": "",
    })
    total_quantity = 0
    for row, _dt in selected:
        qty = _int(row.get("quantity") or row.get("count"))
        if qty <= 0:
            continue
        total_quantity += qty
        product_id = _int(row.get("product_id") or row.get("productId"))
        variant_id = _int(row.get("product_variant_id") or row.get("variantId"))
        key = product_id or f"variant-{variant_id}"
        title = row.get("product_title") or row.get("product_variant_title") or row.get("title") or "—"
        p = products[key]
        p["product_id"] = product_id
        p["name"] = _product_name(title, row.get("product_supplier_code") or row.get("supplier_code"))
        p["quantity"] += qty
        p["rows"] += 1
        p["image"] = p["image"] or row.get("image_src") or row.get("product_image") or row.get("img_src") or row.get("image") or ""

    product_rows = list(products.values())
    product_rows.sort(key=lambda x: (-x["quantity"], x["name"]))
    board = {
        "source": source,
        "jalali_month": jalali_month,
        "start_date": start_date.isoformat(),
        "total_quantity": total_quantity,
        "order_rows": len(selected),
        "product_count": len(product_rows),
        "top_products": product_rows[:10],
        "bottom_products": sorted(product_rows, key=lambda x: (x["quantity"], x["name"]))[:10],
        "source_rows_scanned": len(rows),
        "price_ready": False,
        "updated_at": timezone.localtime().isoformat(),
    }
    cache.set(SALES_CACHE_KEY, board, SALES_CACHE_SECONDS)
    return board


def _return_warehouse_qty(item):
    warehouses = item.get("warehouse")
    values = warehouses.values() if isinstance(warehouses, dict) else warehouses if isinstance(warehouses, list) else []
    total = 0
    titles = []
    for warehouse in values:
        if not isinstance(warehouse, dict):
            continue
        title = str(
            warehouse.get("warehouse_title")
            or warehouse.get("title")
            or warehouse.get("name")
            or ""
        ).strip()
        # User-confirmed physical rule: actual return merchandise is in a warehouse
        # whose title is the return warehouse (e.g. انبار مرجوعی / انبار مرجوعی مرکزی).
        if "مرجوعی" not in title:
            continue
        qty = _int(warehouse.get("count"))
        if qty <= 0:
            qty = _int(warehouse.get("physical_stock"))
        if qty > 0:
            total += qty
            titles.append(title)
    return total, sorted(set(titles))


def get_returns_board(*, force=False):
    if not force:
        cached = cache.get(RETURNS_CACHE_KEY)
        if cached is not None:
            return cached
    inventories = get_inventory_rows(force=force)
    rows = []
    for item in inventories:
        qty, warehouse_titles = _return_warehouse_qty(item)
        if qty <= 0:
            continue
        title = str(item.get("title") or "—")
        rows.append({
            "product_id": _int(item.get("product_id")),
            "variant_id": _int(item.get("product_variant_id")),
            "supplier_code": item.get("supplier_code") or "—",
            "title": title,
            "size": _extract_size(title),
            "return_qty": qty,
            "warehouse_titles": warehouse_titles,
            "image": item.get("img_src") or "",
            "link": item.get("product_url") or "",
        })
    rows.sort(key=lambda x: (-x["return_qty"], str(x["supplier_code"]), x["title"]))
    board = {
        "rows": rows,
        "total": sum(x["return_qty"] for x in rows),
        "variant_count": len(rows),
        "source_rows_scanned": len(inventories),
        "updated_at": timezone.localtime().isoformat(),
    }
    cache.set(RETURNS_CACHE_KEY, board, RETURNS_CACHE_SECONDS)
    return board
