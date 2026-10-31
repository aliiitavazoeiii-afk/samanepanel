import os
import time
from collections import defaultdict
from urllib.parse import urlencode

from django.core.cache import cache
from django.db import transaction
from django.db.models import Sum

from .brand_colors import colors_for_brand, norm
from .daily_order_import_v8 import _resolve_size
from .digikala_client_v40 import DigikalaAPIError, _request_once, get_json
from .models import AppSetting, Brand, Color, ProductSize, Size, StockBalance, StockLocation
from .special_darma_products_v66 import variable_color_names
from .title_product_resolver_v27 import resolve_product_from_title
from .variant_sale_v12 import (
    TITLE_COLORS,
    VARIANT_PRODUCT_CODE,
    is_variable_color_product_code,
    resolve_variable_product_color,
)


ZERO_STATE_PREFIX = "digikala_zero_guard_v65:"
VARIANT_ROWS_CACHE_KEY = "digikala-zero-guard-v65-variants"
VARIANT_ROWS_CACHE_SECONDS = 300
VARIANT_READ_TIMEOUTS = (15, 30, 45)
VARIANT_PAGE_SIZE = 50
VARIANT_SEARCH_TERM = "دارما"
CHECK_SECONDS_DEFAULT = 60
HEALTH_PATH = "/open-api/v1/"
DARMA_SIZE_NAMES = ("M", "L", "XL", "XXL", "3XL", "4XL")


def _env_int(name, default):
    try:
        return int(str(os.getenv(name, default)).strip())
    except Exception:
        return int(default)


def zero_guard_check_seconds():
    return max(30, _env_int("DIGIKALA_ZERO_GUARD_CHECK_SECONDS", CHECK_SECONDS_DEFAULT))


def _marker_key(size_id, color_id):
    return f"{ZERO_STATE_PREFIX}{int(size_id)}:{int(color_id)}"


def _darma():
    return Brand.objects.get(name="دارما")


def _darma_sizes():
    by_name = {
        size.name: size
        for size in Size.objects.filter(name__in=DARMA_SIZE_NAMES).order_by("sort_order", "id")
    }
    return [by_name[name] for name in DARMA_SIZE_NAMES if name in by_name]


def _darma_colors():
    return list(colors_for_brand(_darma()))


def stock_cell_total(size_id, color_id):
    brand = _darma()
    size = Size.objects.get(id=int(size_id))
    color = Color.objects.get(id=int(color_id))
    locations = {
        row["location__key"]: int(row["qty"] or 0)
        for row in (
            StockBalance.objects.filter(brand=brand, size=size, color=color)
            .values("location__key")
            .annotate(qty=Sum("qty"))
        )
    }
    home = int(locations.get(StockLocation.HOME, 0))
    khorshid = int(locations.get(StockLocation.KHORSHID, 0))
    return {
        "brand": brand,
        "size": size,
        "color": color,
        "home": home,
        "khorshid": khorshid,
        "total": home + khorshid,
    }


@transaction.atomic
def scan_zero_transitions(*, bootstrap=False):
    """Persist only zero/positive state changes and return new transitions to zero.

    The first scan after a fresh deployment should pass bootstrap=True so existing
    zero cells are seeded silently. Later positive->zero transitions are notified.
    """
    brand = _darma()
    sizes = _darma_sizes()
    colors = _darma_colors()
    totals = defaultdict(int)
    for row in (
        StockBalance.objects.filter(brand=brand, size__in=sizes, color__in=colors)
        .values("size_id", "color_id")
        .annotate(qty=Sum("qty"))
    ):
        totals[(int(row["size_id"]), int(row["color_id"]))] = int(row["qty"] or 0)

    existing = {
        obj.key: obj
        for obj in AppSetting.objects.select_for_update().filter(key__startswith=ZERO_STATE_PREFIX)
    }

    transitions = []
    for color in colors:
        for size in sizes:
            total = int(totals.get((size.id, color.id), 0))
            state = "zero" if total <= 0 else "positive"
            key = _marker_key(size.id, color.id)
            obj = existing.get(key)

            if obj is None:
                AppSetting.objects.create(
                    key=key,
                    value=state,
                    label=f"DK zero guard {color.name} / {size.name}",
                )
                if state == "zero" and not bootstrap:
                    transitions.append(stock_cell_total(size.id, color.id))
                continue

            old_state = str(obj.value or "").strip().lower()
            if old_state == state:
                continue
            obj.value = state
            obj.label = f"DK zero guard {color.name} / {size.name}"
            obj.save(update_fields=["value", "label", "updated_at"])
            if state == "zero":
                transitions.append(stock_cell_total(size.id, color.id))

    return transitions


def get_api_health(*, timeout=10):
    """Read Digikala Open API health/rate-limit state without an auth token.

    This endpoint is read-only and is used to avoid hammering /variants while the
    seller API rate-limit window is already exhausted.
    """
    status, response = _request_once("GET", HEALTH_PATH, timeout=timeout)
    if status != 200:
        message = response.get("message") if isinstance(response, dict) else None
        errors = response.get("errors") if isinstance(response, dict) else None
        detail = message or errors or f"HTTP {status}"
        raise DigikalaAPIError(
            f"خواندن health دیجی‌کالا ناموفق بود: {detail}",
            status_code=status,
            payload=response,
        )

    data = response.get("data") if isinstance(response, dict) else None
    data = data if isinstance(data, dict) else {}
    rate = data.get("rate_limit")
    rate = rate if isinstance(rate, dict) else {}
    reset = rate.get("resetTime")
    reset = reset if isinstance(reset, dict) else {}

    try:
        limit_max = int(rate.get("max") or 0)
    except (TypeError, ValueError):
        limit_max = 0
    try:
        current = int(rate.get("current") or 0)
    except (TypeError, ValueError):
        current = 0

    return {
        "status": str(response.get("status") or ""),
        "mode": str(data.get("mode") or ""),
        "time": str(data.get("time") or ""),
        "max": limit_max,
        "current": current,
        "remaining": max(limit_max - current, 0) if limit_max > 0 else None,
        "reset_at": str(reset.get("date") or ""),
        "reset_timezone": str(reset.get("timezone") or ""),
        "routes": list(data.get("routes") or []) if isinstance(data.get("routes"), list) else [],
    }


def _rate_limit_exhausted(health):
    maximum = int(health.get("max") or 0)
    current = int(health.get("current") or 0)
    return maximum > 0 and current >= maximum


def _variant_page(path, *, timeout):
    response = get_json(path, timeout=timeout)
    data = response.get("data") if isinstance(response, dict) else None
    data = data if isinstance(data, dict) else {}
    pager = data.get("pager")
    pager = pager if isinstance(pager, dict) else {}
    items = data.get("items")
    items = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    meta = data.get("meta_data")
    meta = meta if isinstance(meta, dict) else {}
    rate = meta.get("rate_limit")
    rate = rate if isinstance(rate, dict) else {}
    reset = rate.get("resetTime")
    reset = reset if isinstance(reset, dict) else {}

    try:
        total_pages = max(int(pager.get("total_pages") or 1), 1)
    except (TypeError, ValueError):
        total_pages = 1
    try:
        maximum = int(rate.get("max") or 0)
    except (TypeError, ValueError):
        maximum = 0
    try:
        current = int(rate.get("current") or 0)
    except (TypeError, ValueError):
        current = 0

    endpoint_rate = {
        "max": maximum,
        "current": current,
        "remaining": max(maximum - current, 0) if maximum > 0 else None,
        "reset_at": str(reset.get("date") or ""),
        "reset_timezone": str(reset.get("timezone") or ""),
    }
    return items, total_pages, endpoint_rate


def _variant_page_path(page, size=VARIANT_PAGE_SIZE):
    query = urlencode(
        {
            "page": int(page),
            "size": int(size),
            "search[search_term]": VARIANT_SEARCH_TERM,
        }
    )
    return f"/open-api/v1/variants?{query}"


def _insufficient_variant_quota(rate, pages_left):
    remaining = rate.get("remaining")
    return remaining is not None and int(remaining) < int(pages_left)


def get_variant_rows(*, force=False):
    if not force:
        cached = cache.get(VARIANT_ROWS_CACHE_KEY)
        if cached is not None:
            return cached

    last_error = None
    first_items = None
    total_pages = None
    endpoint_rate = None

    # First request is always a single Darma-filtered page at the production-confirmed safe size.
    # The API-side search term only narrows the candidate set; title-only resolution below remains
    # authoritative and fail-closed. Some accounts omit meta_data.rate_limit on successful reads;
    # when it is absent we page serially and stop safely on the first 429.
    for attempt, timeout in enumerate(VARIANT_READ_TIMEOUTS, start=1):
        try:
            first_items, total_pages, endpoint_rate = _variant_page(
                _variant_page_path(1),
                timeout=timeout,
            )
            break
        except DigikalaAPIError as exc:
            last_error = exc
            if exc.status_code == 429:
                raise DigikalaAPIError(
                    "Digikala /variants پاسخ 429 Too Many Requests داد؛ "
                    "هیچ retry فوری انجام نشد و هیچ تغییری در Digikala انجام نشد.",
                    status_code=429,
                    payload=exc.payload,
                ) from exc
            if attempt >= len(VARIANT_READ_TIMEOUTS):
                raise DigikalaAPIError(
                    "خواندن صفحه اول تنوع‌های دیجی‌کالا بعد از چند تلاش GET-only ناموفق بود؛ "
                    f"هیچ تغییری در Digikala انجام نشد. آخرین خطا: {last_error}"
                ) from last_error
            time.sleep(attempt * 2)

    rows = list(first_items or [])
    total_pages = int(total_pages or 1)
    endpoint_rate = endpoint_rate or {}
    pages_left = max(total_pages - 1, 0)

    if total_pages > 30:
        raise DigikalaAPIError(
            f"تعداد صفحات /variants برابر {total_pages} است و از سقف امن 30 بیشتر است؛ "
            "خواندن متوقف شد و هیچ تغییری در Digikala انجام نشد."
        )

    if _insufficient_variant_quota(endpoint_rate, pages_left):
        raise DigikalaAPIError(
            "سهمیه واقعی endpoint /variants برای خواندن کامل کافی نیست؛ "
            f"current={endpoint_rate.get('current')} / max={endpoint_rate.get('max')} / "
            f"remaining={endpoint_rate.get('remaining')} / pages_left={pages_left} / "
            f"reset={endpoint_rate.get('reset_at') or '—'}. "
            "فقط صفحه اول خوانده شد و هیچ تغییری در Digikala انجام نشد.",
            status_code=429,
            payload={"variant_rate_limit": endpoint_rate, "total_pages": total_pages},
        )

    for page in range(2, total_pages + 1):
        try:
            items, observed_total_pages, endpoint_rate = _variant_page(
                _variant_page_path(page),
                timeout=30,
            )
        except DigikalaAPIError as exc:
            if exc.status_code == 429:
                raise DigikalaAPIError(
                    f"Digikala هنگام خواندن صفحه {page} از /variants پاسخ 429 داد؛ "
                    "خواندن همان‌جا متوقف شد، retry فوری انجام نشد و هیچ تغییری در Digikala انجام نشد.",
                    status_code=429,
                    payload=exc.payload,
                ) from exc
            raise

        if int(observed_total_pages or total_pages) != total_pages:
            raise DigikalaAPIError(
                "تعداد صفحات /variants حین خواندن تغییر کرد؛ برای جلوگیری از mapping ناقص عملیات متوقف شد."
            )
        rows.extend(items)

        remaining_pages = total_pages - page
        if _insufficient_variant_quota(endpoint_rate, remaining_pages):
            raise DigikalaAPIError(
                "سهمیه /variants حین خواندن برای صفحات باقی‌مانده کافی نیست؛ "
                f"page={page} current={endpoint_rate.get('current')} / max={endpoint_rate.get('max')} / "
                f"remaining={endpoint_rate.get('remaining')} / pages_left={remaining_pages} / "
                f"reset={endpoint_rate.get('reset_at') or '—'}. "
                "mapping ناقص پذیرفته نشد و هیچ تغییری در Digikala انجام نشد.",
                status_code=429,
                payload={"variant_rate_limit": endpoint_rate, "page": page, "total_pages": total_pages},
            )

    cache.set(VARIANT_ROWS_CACHE_KEY, rows, VARIANT_ROWS_CACHE_SECONDS)
    return rows


def _row_titles(row):
    values = []
    for key in ("title", "product_title"):
        value = str(row.get(key) or "").strip()
        if value and value not in values:
            values.append(value)
    return values


def _resolved_identity(row):
    """Resolve only from Digikala title fields. Seller code never identifies product."""
    for title in _row_titles(row):
        product = resolve_product_from_title(title)
        size_name = _resolve_size(title)
        if product is not None and size_name:
            return product, size_name, title

    titles = _row_titles(row)
    if len(titles) == 2:
        combined = f"{titles[1]} | {titles[0]}"
        product = resolve_product_from_title(combined)
        size_name = _resolve_size(combined)
        if product is not None and size_name:
            return product, size_name, combined
    return None, None, ""


def _product_uses_color(product, title, color):
    if is_variable_color_product_code(product.code):
        resolved = resolve_variable_product_color(product.code, title)
        return bool(resolved and norm(resolved) == norm(color.name))
    return product.composition.filter(color=color, qty__gt=0).exists()


def affected_variants_for_cell(size_id, color_id, *, rows=None, force=False):
    cell = stock_cell_total(size_id, color_id)
    size = cell["size"]
    color = cell["color"]

    local_products = list(
        ProductSize.objects.filter(
            product__brand__name="دارما",
            product__active=True,
            active=True,
            size=size,
        )
        .select_related("product", "size")
        .prefetch_related("product__composition__color")
        .order_by("product__code")
    )
    local_expected_codes = []
    for ps in local_products:
        if is_variable_color_product_code(ps.product.code):
            allowed = (
                TITLE_COLORS
                if ps.product.code == VARIANT_PRODUCT_CODE
                else variable_color_names(ps.product.code)
            )
            if norm(color.name) in {norm(name) for name in allowed}:
                local_expected_codes.append(ps.product.code)
            continue
        if any(comp.color_id == color.id and int(comp.qty or 0) > 0 for comp in ps.product.composition.all()):
            local_expected_codes.append(ps.product.code)

    source_rows = list(rows) if rows is not None else get_variant_rows(force=force)
    affected = []
    unresolved_darma_like = 0
    seen = set()

    for row in source_rows:
        product, size_name, title_used = _resolved_identity(row)
        titles_text = " ".join(_row_titles(row))
        if product is None or not size_name:
            if "دارما" in titles_text:
                unresolved_darma_like += 1
            continue
        if product.brand.name != "دارما" or size_name != size.name:
            continue
        if not _product_uses_color(product, title_used, color):
            continue
        if not ProductSize.objects.filter(product=product, size=size, active=True).exists():
            continue

        seller_variant_id = int(row.get("id") or 0)
        dkpc = int(row.get("product_variant_id") or row.get("variantId") or 0)
        identity = seller_variant_id or dkpc
        if not identity or identity in seen:
            continue
        seen.add(identity)
        affected.append(
            {
                "seller_variant_id": seller_variant_id,
                "dkpc": dkpc,
                "supplier_code": str(row.get("supplier_code") or "—"),
                "product_code": product.code,
                "size": size.name,
                "title": str(row.get("title") or row.get("product_title") or title_used or "—"),
                "active": bool(row.get("active")),
                "seller_stock": int(row.get("marketplace_seller_stock") or 0),
                "warehouse_stock": int(row.get("warehouse_stock") or 0),
                "on_the_way_stock": int(row.get("on_the_way_stock") or 0),
            }
        )

    affected.sort(key=lambda x: (x["product_code"], x["seller_variant_id"], x["dkpc"]))
    return {
        "cell": cell,
        "local_expected_codes": sorted(set(local_expected_codes)),
        "affected": affected,
        "active_affected": [row for row in affected if row["active"]],
        "inactive_affected": [row for row in affected if not row["active"]],
        "unresolved_darma_like": unresolved_darma_like,
        "source_variant_count": len(source_rows),
        "write_enabled": False,
    }


def format_preview(preview, *, max_rows=30):
    cell = preview["cell"]
    affected = preview["affected"]
    active = preview["active_affected"]
    lines = [
        "🔎 پیش‌نمایش امن Digikala — فقط خواندنی",
        f"{cell['color'].name} / {cell['size'].name}",
        f"خانه: {cell['home']} | خورشید: {cell['khorshid']} | کل: {cell['total']}",
        "",
        f"کدهای داخلی وابسته: {', '.join(preview['local_expected_codes']) or '—'}",
        f"DKPCهای تطبیق‌شده: {len(affected)} | فعال: {len(active)}",
    ]
    if preview["unresolved_darma_like"]:
        lines.append(
            f"⚠️ {preview['unresolved_darma_like']} ردیف Darma از API با title resolver فعلی resolve نشد؛ "
            "برای ایمنی هیچ حدسی روی آنها زده نمی‌شود."
        )

    for row in affected[:max_rows]:
        state = "فعال" if row["active"] else "غیرفعال"
        lines.append(
            f"• {row['product_code']} | {row['size']} | DKPC {row['dkpc'] or '—'} | "
            f"variant {row['seller_variant_id'] or '—'} | {state} | "
            f"seller={row['seller_stock']} | DKwh={row['warehouse_stock']} | "
            f"DKway={row['on_the_way_stock']}"
        )
    if len(affected) > max_rows:
        lines.append(f"… و {len(affected) - max_rows} مورد دیگر")

    lines.extend(
        [
            "",
            "🔎 این صفحه فقط پیش‌نمایش است و با باز کردن آن هیچ تغییری در Digikala انجام نمی‌شود.",
            "هر write احتمالی فقط در gate جداگانه V68 و بعد از تأیید نهایی کاربر انجام می‌شود.",
        ]
    )
    return "\n".join(lines)
