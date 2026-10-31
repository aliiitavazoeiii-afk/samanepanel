from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlencode

from django.core.cache import cache

from .digikala_client_v40 import DigikalaAPIError, get_json


INVENTORY_ROWS_CACHE_KEY = "digikala-v44-inventory-rows"
COMMITMENT_ROWS_CACHE_KEY = "digikala-v44-commitment-rows"
INVENTORY_ROWS_CACHE_SECONDS = 600
COMMITMENT_ROWS_CACHE_SECONDS = 180
MAX_PAGE_WORKERS = 3


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
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _pager(response):
    value = _data(response).get("pager")
    return value if isinstance(value, dict) else {}


def _path_with_query(path, params):
    query = urlencode(params or {})
    if not query:
        return path
    separator = "&" if "?" in path else "?"
    return f"{path}{separator}{query}"


def paginated_get(
    path,
    *,
    params=None,
    size=50,
    max_pages=30,
    timeout=7,
    workers=MAX_PAGE_WORKERS,
):
    """Read one paginated Digikala endpoint with bounded parallel page requests."""
    base_params = dict(params or {})

    def fetch_page(page):
        query = dict(base_params)
        query["page"] = page
        query["size"] = size
        response = get_json(_path_with_query(path, query), timeout=timeout)
        return page, response

    _page, first = fetch_page(1)
    pager = _pager(first)
    total_pages = max(_int(pager.get("total_pages")), 1)
    if total_pages > max_pages:
        raise DigikalaAPIError(
            f"تعداد صفحات {total_pages} بیشتر از سقف امن {max_pages} است؛ خواندن متوقف شد."
        )

    pages = {1: _items(first)}
    if total_pages > 1:
        with ThreadPoolExecutor(max_workers=min(max(1, workers), total_pages - 1)) as executor:
            futures = {executor.submit(fetch_page, page): page for page in range(2, total_pages + 1)}
            for future in as_completed(futures):
                page, response = future.result()
                pages[page] = _items(response)

    rows = []
    for page in range(1, total_pages + 1):
        rows.extend(pages.get(page, []))
    return rows


def get_inventory_rows(*, force=False):
    if not force:
        cached = cache.get(INVENTORY_ROWS_CACHE_KEY)
        if cached is not None:
            return cached
    rows = paginated_get(
        "/open-api/v1/inventories",
        size=100,
        max_pages=30,
        timeout=8,
        workers=3,
    )
    cache.set(INVENTORY_ROWS_CACHE_KEY, rows, INVENTORY_ROWS_CACHE_SECONDS)
    return rows


def get_commitment_rows(*, force=False):
    if not force:
        cached = cache.get(COMMITMENT_ROWS_CACHE_KEY)
        if cached is not None:
            return cached
    rows = paginated_get(
        "/open-api/v1/commitments",
        params={"sort": "variant_id", "order": "asc"},
        size=50,
        max_pages=20,
        timeout=7,
        workers=2,
    )
    cache.set(COMMITMENT_ROWS_CACHE_KEY, rows, COMMITMENT_ROWS_CACHE_SECONDS)
    return rows
