from collections import defaultdict
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

import jdatetime
from django.core.cache import cache
from django.utils import timezone

from .digikala_client_v40 import DigikalaAPIError, get_json


ORDERS_CACHE_KEY = "digikala-v43-daily-orders"
PACKAGES_CACHE_KEY = "digikala-v43-packages"
SALES_CACHE_KEY = "digikala-v43-sales"
RETURNS_CACHE_KEY = "digikala-v43-returns"
CENTER_CACHE_SECONDS = 60


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


def _pager(response):
    value = _data(response).get("pager")
    return value if isinstance(value, dict) else {}


def _paginate(path, *, params=None, size=50, max_pages=20):
    page = 1
    rows = []
    params = dict(params or {})
    while True:
        query = dict(params)
        query["page"] = page
        query["size"] = size
        separator = "&" if "?" in path else "?"
        response = get_json(f"{path}{separator}{urlencode(query)}")
        rows.extend(_items(response))
        pager = _pager(response)
        total_pages = max(_int(pager.get("total_pages")), 1)
        if page >= total_pages:
            break
        page += 1
        if page > max_pages:
            raise DigikalaAPIError("تعداد صفحات API دیجی‌کالا غیرمنتظره است؛ خواندن متوقف شد.")
    return rows


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


def _product_name(title, supplier_code):
    title = str(title or "").strip()
    if title:
        first = title.split("|", 1)[0].strip()
        if first:
            return first
    return str(supplier_code or "کالا")


def _jalali_label(value):
    if not isinstance(value, date):
        return "—"
    j = jdatetime.date.fromgregorian(date=value)
    return f"{j.year:04d}/{j.month:02d}/{j.day:02d}"


def _commitment_rows(*, cutoff=None):
    params = {"sort": "variant_id", "order": "asc"}
    if cutoff is not None:
        params["search[is_effective]"] = "true"
        params["search[to_commitment_date]"] = cutoff.isoformat()
    return _paginate("/open-api/v1/commitments", params=params, size=50, max_pages=20)


def _commitment_all_map(rows):
    result = {}
    for row in rows:
        variant_id = _int(row.get("variantId"))
        if not variant_id:
            continue
        commitment = row.get("commitment") if isinstance(row.get("commitment"), dict) else {}
        result[variant_id] = _int(commitment.get("all"))
    return result


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
        product["variants"].sort(key=lambda x: (str(x["size"]), str(x["supplier_code"]), x["variant_id"]))
    result.sort(key=lambda x: (-x["total"], x["name"]))
    return result


def get_daily_orders_center(*, force=False):
    if not force:
        cached = cache.get(ORDERS_CACHE_KEY)
        if cached:
            return cached

    today = timezone.localdate()
    tomorrow = today + timedelta(days=1)
    day_after = today + timedelta(days=2)

    base_rows = _commitment_rows()
    date_split_ok = True
    date_split_error = ""
    try:
        today_map = _commitment_all_map(_commitment_rows(cutoff=today))
        tomorrow_map = _commitment_all_map(_commitment_rows(cutoff=tomorrow))
        day_after_map = _commitment_all_map(_commitment_rows(cutoff=day_after))
    except DigikalaAPIError as exc:
        # The unfiltered commitments list remains the operational source of truth.
        # If Digikala rejects a date filter, fail closed on the split rather than
        # mislabelling future commitments as tomorrow/day-after.
        today_map = {}
        tomorrow_map = {}
        day_after_map = {}
        date_split_ok = False
        date_split_error = str(exc)

    variants = []
    split_issues = []

    for row in base_rows:
        variant_id = _int(row.get("variantId"))
        if not variant_id:
            continue
        commitment = row.get("commitment") if isinstance(row.get("commitment"), dict) else {}
        next_days = _int(commitment.get("nextDays"))
        today_qty = _int(commitment.get("today"))
        delayed_qty = _int(commitment.get("delayed"))
        if next_days <= 0 and today_qty <= 0 and delayed_qty <= 0:
            continue

        if date_split_error:
            tomorrow_qty = 0
            day_after_qty = 0
            later_qty = next_days
        else:
            through_today = today_map.get(variant_id, 0)
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
        "date_split_error": date_split_error,
        "split_issue_variants": split_issues[:20],
        "updated_at": timezone.localtime().isoformat(),
    }
    cache.set(ORDERS_CACHE_KEY, board, CENTER_CACHE_SECONDS)
    return board


def _package_status(item):
    value = item.get("status")
    if isinstance(value, dict):
        return value.get("title") or value.get("text_fa") or value.get("key") or "—"
    return str(value or item.get("status_title") or item.get("package_status") or "—")


def _package_id(item):
    for key in ("id", "package_id", "packageId"):
        value = _int(item.get(key))
        if value:
            return value
    return 0


def get_packages_board(*, force=False):
    if not force:
        cached = cache.get(PACKAGES_CACHE_KEY)
        if cached:
            return cached
    try:
        rows = _paginate(
            "/open-api/v1/packages",
            params={"sort": "id", "order": "desc"},
            size=50,
            max_pages=20,
        )
        available = True
        error = ""
    except DigikalaAPIError as exc:
        rows = []
        available = False
        error = str(exc)

    packages = []
    for item in rows:
        package_id = _package_id(item)
        packages.append({
            "package_id": package_id,
            "status": _package_status(item),
            "created_at": item.get("created_at") or item.get("createdAt") or item.get("date") or "—",
            "delivery_date": item.get("delivery_date") or item.get("deliveryDate") or item.get("commitment_date") or "—",
            "warehouse": item.get("warehouse_title") or item.get("warehouse") or item.get("warehouse_name") or "—",
            "item_count": _int(item.get("item_count") or item.get("items_count") or item.get("variant_count") or item.get("count")),
            "raw": item,
        })
    board = {
        "available": available,
        "error": error,
        "rows": packages,
        "total": len(packages),
        "updated_at": timezone.localtime().isoformat(),
    }
    cache.set(PACKAGES_CACHE_KEY, board, CENTER_CACHE_SECONDS)
    return board


def _walk_lists(obj, path=""):
    if isinstance(obj, dict):
        for key, value in obj.items():
            current = f"{path}.{key}" if path else key
            if isinstance(value, list):
                yield current, value
            yield from _walk_lists(value, current)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from _walk_lists(value, f"{path}[{index}]")


def _variant_from_package_item(item):
    if not isinstance(item, dict):
        return None
    variant_id = _int(item.get("product_variant_id") or item.get("variant_id") or item.get("variantId") or item.get("id"))
    product_id = _int(item.get("product_id") or item.get("productId"))
    quantity = _int(item.get("quantity") or item.get("qty") or item.get("count"))
    title = item.get("title") or item.get("product_title") or item.get("variant_title")
    if not variant_id and not product_id and not title:
        return None
    return {
        "variant_id": variant_id,
        "product_id": product_id,
        "quantity": quantity,
        "title": title or "—",
        "image": item.get("image") or item.get("image_url") or item.get("img_src") or "",
        "size": item.get("size") or _extract_size(title or ""),
    }


def get_package_detail(package_id):
    response = get_json(f"/open-api/v1/packages/{int(package_id)}")
    data = _data(response)
    variants = []
    seen = set()
    for path, values in _walk_lists(data):
        if not any(word in path.lower() for word in ("variant", "item", "product")):
            continue
        for value in values:
            variant = _variant_from_package_item(value)
            if variant is None:
                continue
            key = (variant["variant_id"], variant["product_id"], variant["title"], variant["quantity"])
            if key in seen:
                continue
            seen.add(key)
            variants.append(variant)
    variants.sort(key=lambda x: (x["title"], x["size"], x["variant_id"]))
    return {
        "package_id": int(package_id),
        "status": _package_status(data),
        "variants": variants,
        "total_quantity": sum(v["quantity"] for v in variants),
        "raw": data,
    }


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
    for key in ("warehouse_status_at", "order_date", "orderDate", "created_at", "createdAt", "updated_at"):
        value = _parse_api_datetime(row.get(key))
        if value:
            return value
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
        if cached:
            return cached

    rows = _paginate("/open-api/v1/orders", params={"sort": "id", "order": "desc"}, size=100, max_pages=30)
    start_date, next_month, jalali_month = _jalali_month_bounds()
    selected = []
    for row in rows:
        dt = _order_datetime(row)
        if dt is None:
            continue
        local_date = timezone.localtime(dt).date()
        if start_date <= local_date < next_month:
            selected.append((row, dt))

    products = defaultdict(lambda: {"product_id": 0, "name": "—", "quantity": 0, "rows": 0, "image": ""})
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
        p["name"] = _product_name(title, row.get("supplier_code"))
        p["quantity"] += qty
        p["rows"] += 1
        p["image"] = p["image"] or row.get("product_image") or row.get("img_src") or row.get("image") or ""

    product_rows = list(products.values())
    product_rows.sort(key=lambda x: (-x["quantity"], x["name"]))
    board = {
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
    cache.set(SALES_CACHE_KEY, board, CENTER_CACHE_SECONDS)
    return board


def get_returns_board(*, force=False):
    if not force:
        cached = cache.get(RETURNS_CACHE_KEY)
        if cached:
            return cached
    inventories = _paginate("/open-api/v1/inventories", size=100, max_pages=30)
    rows = []
    for item in inventories:
        return_stock = _int(item.get("return_stock"))
        if return_stock <= 0:
            continue
        title = str(item.get("title") or "—")
        rows.append({
            "product_id": _int(item.get("product_id")),
            "variant_id": _int(item.get("product_variant_id")),
            "supplier_code": item.get("supplier_code") or "—",
            "title": title,
            "size": _extract_size(title),
            "return_stock": return_stock,
            "image": item.get("img_src") or "",
            "link": item.get("product_url") or "",
        })
    rows.sort(key=lambda x: (-x["return_stock"], str(x["supplier_code"]), x["title"]))
    board = {
        "rows": rows,
        "total": sum(x["return_stock"] for x in rows),
        "variant_count": len(rows),
        "source_rows_scanned": len(inventories),
        "updated_at": timezone.localtime().isoformat(),
    }
    cache.set(RETURNS_CACHE_KEY, board, CENTER_CACHE_SECONDS * 2)
    return board
