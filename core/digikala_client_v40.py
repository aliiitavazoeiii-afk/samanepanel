import fcntl
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request

from django.core.cache import cache
from django.utils import timezone


BASE_URL = "https://seller.digikala.com"
SECRET_DIR = Path(os.environ.get("DIGIKALA_SECRET_DIR", "/run/secrets/digikala"))
ACCESS_TOKEN_FILE = SECRET_DIR / "access_token.txt"
REFRESH_TOKEN_FILE = SECRET_DIR / "refresh_token.txt"
TOKEN_META_FILE = SECRET_DIR / "token_meta.json"
REFRESH_LOCK_FILE = SECRET_DIR / ".refresh.lock"
SUMMARY_CACHE_KEY = "digikala-v40-summary"
SUMMARY_CACHE_SECONDS = 30


class DigikalaAPIError(RuntimeError):
    def __init__(self, message, *, status_code=None, payload=None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def _read_secret(path):
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise DigikalaAPIError(f"فایل امن دیجی‌کالا پیدا نشد: {path.name}") from exc
    if not value:
        raise DigikalaAPIError(f"فایل امن دیجی‌کالا خالی است: {path.name}")
    return value


def _atomic_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _decode_json(raw):
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"message": raw.decode("utf-8", errors="replace")[:500]}


def _request_once(method, path, *, token=None, payload=None, timeout=5):
    url = f"{BASE_URL}{path}"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "DARMA-General-Digikala-V40/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib_request.urlopen(req, timeout=timeout) as response:
            return response.status, _decode_json(response.read())
    except urllib_error.HTTPError as exc:
        return exc.code, _decode_json(exc.read())
    except (urllib_error.URLError, TimeoutError, OSError) as exc:
        raise DigikalaAPIError(f"ارتباط با API دیجی‌کالا برقرار نشد: {exc}") from exc


def _refresh_access_token(failed_token=None):
    SECRET_DIR.mkdir(parents=True, exist_ok=True)
    with open(REFRESH_LOCK_FILE, "a+", encoding="utf-8") as lock_handle:
        os.chmod(REFRESH_LOCK_FILE, 0o600)
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)

        current_access = _read_secret(ACCESS_TOKEN_FILE)
        if failed_token and current_access != failed_token:
            return current_access

        refresh_token = _read_secret(REFRESH_TOKEN_FILE)
        status, response = _request_once(
            "POST",
            "/open-api/v1/auth/refresh-token",
            payload={
                "access_token": current_access,
                "refresh_token": refresh_token,
            },
            timeout=8,
        )
        data = response.get("data") if isinstance(response, dict) else None
        data = data if isinstance(data, dict) else {}
        new_access = data.get("access_token")
        new_refresh = data.get("refresh_token")
        if status != 200 or not new_access or not new_refresh:
            message = response.get("message") if isinstance(response, dict) else None
            errors = response.get("errors") if isinstance(response, dict) else None
            detail = message or errors or f"HTTP {status}"
            raise DigikalaAPIError(
                f"رفرش توکن دیجی‌کالا ناموفق بود: {detail}",
                status_code=status,
                payload=response,
            )

        _atomic_write(ACCESS_TOKEN_FILE, str(new_access))
        _atomic_write(REFRESH_TOKEN_FILE, str(new_refresh))
        _atomic_write(
            TOKEN_META_FILE,
            json.dumps(
                {
                    "access_token_expires_at": data.get("access_token_expires_at"),
                    "refresh_token_expires_at": data.get("refresh_token_expires_at"),
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        cache.delete(SUMMARY_CACHE_KEY)
        return str(new_access)


def get_json(path, *, timeout=5):
    token = _read_secret(ACCESS_TOKEN_FILE)
    status, response = _request_once("GET", path, token=token, timeout=timeout)
    if status == 401:
        token = _refresh_access_token(failed_token=token)
        status, response = _request_once("GET", path, token=token, timeout=timeout)

    if status != 200:
        message = response.get("message") if isinstance(response, dict) else None
        errors = response.get("errors") if isinstance(response, dict) else None
        detail = message or errors or f"HTTP {status}"
        raise DigikalaAPIError(
            f"درخواست دیجی‌کالا ناموفق بود: {detail}",
            status_code=status,
            payload=response,
        )
    if isinstance(response, dict) and response.get("status") == "error":
        raise DigikalaAPIError(
            f"API دیجی‌کالا خطا برگرداند: {response.get('message') or response.get('errors')}",
            status_code=status,
            payload=response,
        )
    return response


def put_json(path, payload, *, timeout=10):
    """Authenticated JSON PUT with the same single-refresh behavior as get_json.

    This helper is intentionally narrow. Callers must supply the exact endpoint and payload;
    no retry is performed for non-auth failures so a remote mutation is never repeated blindly.
    """
    token = _read_secret(ACCESS_TOKEN_FILE)
    status, response = _request_once(
        "PUT",
        path,
        token=token,
        payload=payload,
        timeout=timeout,
    )
    if status == 401:
        token = _refresh_access_token(failed_token=token)
        status, response = _request_once(
            "PUT",
            path,
            token=token,
            payload=payload,
            timeout=timeout,
        )

    if status != 200:
        message = response.get("message") if isinstance(response, dict) else None
        errors = response.get("errors") if isinstance(response, dict) else None
        detail = message or errors or f"HTTP {status}"
        raise DigikalaAPIError(
            f"درخواست تغییردهنده دیجی‌کالا ناموفق بود: {detail}",
            status_code=status,
            payload=response,
        )
    if isinstance(response, dict) and response.get("status") == "error":
        raise DigikalaAPIError(
            f"API دیجی‌کالا خطا برگرداند: {response.get('message') or response.get('errors')}",
            status_code=status,
            payload=response,
        )
    return response


def _data(response):
    if not isinstance(response, dict):
        return {}
    value = response.get("data")
    return value if isinstance(value, dict) else {}


def _pager_total(response):
    pager = _data(response).get("pager")
    if not isinstance(pager, dict):
        return 0
    try:
        return int(pager.get("total_rows") or 0)
    except (TypeError, ValueError):
        return 0


def _number(value):
    if value in (None, ""):
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _store_title(profile_response):
    store = _data(profile_response).get("store")
    if not isinstance(store, dict):
        return ""
    for key in ("name", "title", "store_name", "seller_name"):
        if store.get(key):
            return str(store[key])
    return ""


def get_token_meta():
    try:
        data = json.loads(TOKEN_META_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def get_summary(*, force=False):
    if not force:
        cached = cache.get(SUMMARY_CACHE_KEY)
        if cached:
            return cached

    endpoints = {
        "orders": "/open-api/v1/orders?page=1&size=1",
        "statistics": "/open-api/v1/orders/statistics",
        "inventory": "/open-api/v1/inventories?page=1&size=1",
        "profile": "/open-api/v1/profile",
        "commitments": "/open-api/v1/commitments?page=1&size=1",
        "commitment_meta": "/open-api/v1/commitments/metadata",
        "invoices": "/open-api/v1/invoices?page=1&size=1&order=desc",
    }
    responses = {}
    errors = {}
    with ThreadPoolExecutor(max_workers=len(endpoints)) as executor:
        futures = {executor.submit(get_json, path, timeout=5): name for name, path in endpoints.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                responses[name] = future.result()
            except Exception as exc:  # External API errors must not break the business dashboard.
                errors[name] = str(exc)

    stats = _data(responses.get("statistics", {}))
    commitment_summary = _data(responses.get("commitment_meta", {})).get("summary_statistics")
    commitment_summary = commitment_summary if isinstance(commitment_summary, dict) else {}
    token_meta = get_token_meta()

    summary = {
        "connected": bool(responses),
        "orders_total": _pager_total(responses.get("orders", {})),
        "inventory_total": _pager_total(responses.get("inventory", {})),
        "invoices_total": _pager_total(responses.get("invoices", {})),
        "commitments_total": _number(
            commitment_summary.get("totalCommitments")
            or _pager_total(responses.get("commitments", {}))
        ),
        "effective_commitments": _number(commitment_summary.get("effectiveCommitments")),
        "non_effective_commitments": _number(commitment_summary.get("nonEffectiveCommitments")),
        "total_penalty_rial": _number(commitment_summary.get("totalPenalty")),
        "all_shipped_by_dk": _number(stats.get("all_shipped_by_dk")),
        "shipped_by_seller_count": _number(stats.get("shipped_by_seller_count")),
        "nearby_orders": _number(stats.get("seller_nearby_stores_order_count")),
        "nearby_pending": _number(stats.get("seller_nearby_stores_pending_order_count")),
        "store_title": _store_title(responses.get("profile", {})),
        "access_token_expires_at": token_meta.get("access_token_expires_at"),
        "refresh_token_expires_at": token_meta.get("refresh_token_expires_at"),
        "updated_at": timezone.localtime().isoformat(),
        "errors": errors,
    }
    cache.set(SUMMARY_CACHE_KEY, summary, SUMMARY_CACHE_SECONDS)
    return summary
