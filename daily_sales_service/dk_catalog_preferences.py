"""Per-variant administrative presentation and reversible removal for sister DigiKala.

Source product identities, history, inventory and marketplace imports must not be
deleted or rewritten. The owner's delete action archives only this catalog
listing; the restore action is available on the Removed tab.
"""
from datetime import datetime, timezone
from urllib.parse import urlencode

from .engine import ImportErrorDetail, money

SCHEMA = """
CREATE TABLE IF NOT EXISTS dk_catalog_preferences (
 variant_id INTEGER PRIMARY KEY REFERENCES products(variant_id),
 display_title TEXT,
 display_price_toman INTEGER CHECK(display_price_toman IS NULL OR display_price_toman > 0),
 archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),
 updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dk_catalog_pref_archived ON dk_catalog_preferences(archived);
"""

def ensure_catalog_preferences(conn):
    conn.executescript(SCHEMA)

def is_archived(conn, variant_id):
    row = conn.execute(
        "SELECT archived FROM dk_catalog_preferences WHERE variant_id=?",
        (int(variant_id),)).fetchone()
    return bool(row and row["archived"])

def _variant_exists(conn, variant_id):
    try:
        vid = int(variant_id)
    except (TypeError, ValueError):
        raise ImportErrorDetail("شناسه تنوع نامعتبر است.")
    if not conn.execute("SELECT 1 FROM products WHERE variant_id=?", (vid,)).fetchone():
        raise ImportErrorDetail("این تنوع دیجی‌کالا پیدا نشد.")
    return vid

def _save(conn, vid, title, price, archived):
    stamp = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        INSERT INTO dk_catalog_preferences(variant_id,display_title,display_price_toman,archived,updated_at)
        VALUES(?,?,?,?,?)
        ON CONFLICT(variant_id) DO UPDATE SET
        display_title=excluded.display_title,
        display_price_toman=excluded.display_price_toman,
        archived=excluded.archived,
        updated_at=excluded.updated_at
    """, (vid, title, price, archived, stamp))

def update_display(conn, variant_id, display_title, display_price):
    vid = _variant_exists(conn, variant_id)
    title = str(display_title or "").strip()
    if not title or len(title) > 220:
        raise ImportErrorDetail("عنوان محصول باید بین ۱ تا ۲۲۰ نویسه باشد.")
    price = None if str(display_price or "").strip() == "" else money(display_price)
    if price is not None and price <= 0:
        raise ImportErrorDetail("قیمت نمایشی باید بزرگ‌تر از صفر باشد.")
    conn.execute("BEGIN IMMEDIATE")
    try:
        pref = conn.execute(
            "SELECT archived FROM dk_catalog_preferences WHERE variant_id=?", (vid,)).fetchone()
        if pref and pref["archived"]:
            raise ImportErrorDetail("محصول حذف‌شده را ابتدا بازیابی کن.")
        source = conn.execute("SELECT title FROM products WHERE variant_id=?", (vid,)).fetchone()
        _save(conn, vid, None if title == source["title"] else title, price, 0)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

def set_archived(conn, variant_id, archived):
    vid = _variant_exists(conn, variant_id)
    conn.execute("BEGIN IMMEDIATE")
    try:
        pref = conn.execute(
            "SELECT display_title,display_price_toman FROM dk_catalog_preferences WHERE variant_id=?",
            (vid,)).fetchone()
        _save(conn, vid,
              pref["display_title"] if pref else None,
              pref["display_price_toman"] if pref else None,
              1 if archived else 0)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

def catalog_redirect(status, q, page_no):
    valid = {"all", "connected", "unmapped", "removed"}
    state = status if status in valid else "all"
    query = str(q or "")[:120]
    try: page = max(1, min(int(page_no), 10000))
    except (ValueError, TypeError): page = 1
    return "/daily-sales/catalog?" + urlencode({"status": state, "q": query, "page_no": page})
