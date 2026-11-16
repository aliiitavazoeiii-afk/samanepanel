"""Dated sale-price schedule for exact DigiKala variant/pack IDs.

The daily import uses the rate effective on the chosen sale date, not the
calendar date on which the Excel file happens to be uploaded. A sale already
committed to the ledger retains its posted historical price snapshot.
"""
from .engine import ImportErrorDetail,money
from .effective_costs import today,valid_date
from .master_engine import now

SCHEMA = """
CREATE TABLE IF NOT EXISTS dk_dated_sale_prices (
    variant_id INTEGER NOT NULL REFERENCES products(variant_id),
    effective_date TEXT NOT NULL,
    price_toman INTEGER NOT NULL CHECK(price_toman>0),
    recorded_at TEXT NOT NULL,
    PRIMARY KEY(variant_id,effective_date)
);
CREATE INDEX IF NOT EXISTS idx_dk_dated_price_date
    ON dk_dated_sale_prices(effective_date,variant_id);
"""

def ensure_dated_prices(conn):
    conn.executescript(SCHEMA)

def effective_price(conn,variant_id,as_of=None):
    day=valid_date(as_of or today())
    row=conn.execute("""SELECT price_toman,effective_date
        FROM dk_dated_sale_prices WHERE variant_id=? AND effective_date<=?
        ORDER BY effective_date DESC LIMIT 1""",(int(variant_id),day)).fetchone()
    if row is None:return None
    return int(row["price_toman"]),str(row["effective_date"])

def save_dated_prices(conn,values,effective_date):
    day=valid_date(effective_date)
    if day<today():
        raise ImportErrorDetail("تاریخ شروع قیمت نمی‌تواند قبل از امروز باشد؛ قیمت فروش ثبت‌شده قبلی محفوظ است.")
    if not values or len(values)>100:
        raise ImportErrorDetail("حداقل یک قیمت و حداکثر ۱۰۰ قیمت در هر بار ثبت مجاز است.")
    parsed={}
    for variant_id,raw_price in values.items():
        try:vid=int(variant_id)
        except (TypeError,ValueError):raise ImportErrorDetail("کد تنوع نامعتبر است.")
        price=money(raw_price)
        if price<=0:raise ImportErrorDetail("قیمت فروش هر بسته باید بیشتر از صفر باشد.")
        parsed[vid]=price
    conn.execute("BEGIN IMMEDIATE")
    try:
        query="SELECT variant_id,active FROM products WHERE variant_id IN ("+",".join("?" for _ in parsed)+")"
        valid={int(row["variant_id"]):bool(row["active"]) for row in conn.execute(query,list(parsed))}
        if any(not valid.get(vid) for vid in parsed):
            raise ImportErrorDetail("یک یا چند کد تنوع وجود ندارد یا غیرفعال است.")
        hidden={int(x["variant_id"]) for x in conn.execute(
            "SELECT variant_id FROM dk_catalog_preferences WHERE archived=1")}
        if hidden.intersection(parsed):
            raise ImportErrorDetail("قیمت‌گذاری کد حذف‌شده مجاز نیست؛ ابتدا بازیابی کن.")
        for vid,price in parsed.items():
            conn.execute("""INSERT INTO dk_dated_sale_prices(
                variant_id,effective_date,price_toman,recorded_at)
                VALUES(?,?,?,?)
                ON CONFLICT(variant_id,effective_date) DO UPDATE SET
                    price_toman=excluded.price_toman,
                    recorded_at=excluded.recorded_at""",
                (vid,day,price,now()))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(parsed)
