"""Effective-dated replacement-cost rules; stock is valued as of the requested day.

Prior sold quantities retain posted cost snapshots. Updating a future rule does
not change current stock value until midnight Asia/Tehran on effective_date.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo
from .engine import ImportErrorDetail, money
from .master_engine import CATEGORIES, now

TEHRAN = ZoneInfo("Asia/Tehran")
BASELINE = "1900-01-01"
SCHEMA = """
CREATE TABLE IF NOT EXISTS master_cost_history(
 category TEXT NOT NULL, subtype TEXT NOT NULL DEFAULT '', size TEXT NOT NULL DEFAULT '*',
 effective_date TEXT NOT NULL,
 cost_toman INTEGER NOT NULL CHECK(cost_toman>=0),
 recorded_at TEXT NOT NULL,
 PRIMARY KEY(category,subtype,size,effective_date)
);
CREATE INDEX IF NOT EXISTS idx_master_cost_dates
 ON master_cost_history(category,subtype,size,effective_date);
"""

def today():
    return datetime.now(TEHRAN).date().isoformat()

def valid_date(value):
    try:
        result=date.fromisoformat(str(value))
    except (ValueError,TypeError):
        raise ImportErrorDetail("تاریخ اجرا باید میلادی و در قالب YYYY-MM-DD باشد.")
    return result.isoformat()

def ensure_cost_history(conn):
    conn.executescript(SCHEMA)
    # Transition: retain old central costs from V2 as a dated baseline only.
    # Never overwrite an already established historical price.
    conn.execute("""INSERT OR IGNORE INTO master_cost_history
       (category,subtype,size,effective_date,cost_toman,recorded_at)
       SELECT category,subtype,size,?,cost_toman,updated_at FROM master_cost_rules""",
       (BASELINE,))

def key_for(category,subtype,size):
    from .master_v2_logic import BODY_TYPES,SIZES
    category=str(category or "").strip()
    if category not in CATEGORIES:raise ImportErrorDetail("دسته‌بندی نامعتبر است.")
    subtype=str(subtype or "").strip()
    if category=="بادیگارد":
        if subtype not in BODY_TYPES:raise ImportErrorDetail("برای بادیگارد نوع اسلیپ یا پادار را انتخاب کن.")
    elif subtype:
        raise ImportErrorDetail("زیرگروه اضافی برای این محصول مجاز نیست.")
    if category=="قالب":
        if size not in SIZES["قالب"]:raise ImportErrorDetail("اندازه قالب باید کوچک، متوسط یا بزرگ باشد.")
    else:
        size="*"
    return category,subtype,size

def schedule_cost(conn,category,subtype,size,cost,effective_date):
    category,subtype,size=key_for(category,subtype,size)
    effective=valid_date(effective_date)
    if effective<today():
        raise ImportErrorDetail("برای حفظ گزارش و قیمت تمام‌شده فروش‌های گذشته، تاریخ اجرا نمی‌تواند قبل از امروز باشد.")
    value=money(cost)
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("""INSERT INTO master_cost_history(category,subtype,size,effective_date,cost_toman,recorded_at)
          VALUES(?,?,?,?,?,?) ON CONFLICT(category,subtype,size,effective_date)
          DO UPDATE SET cost_toman=excluded.cost_toman,recorded_at=excluded.recorded_at""",
          (category,subtype,size,effective,value,now()))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK");raise
    return value

def dated_cost(conn,sku,as_of=None):
    date_key=valid_date(as_of or today())
    category,subtype,size=sku["category"],sku.get("subtype",""),sku["size"]
    # Explicit size-specific cost > default "*" rule, using most recent effective date.
    for candidate in (size,"*"):
        r=conn.execute("""SELECT cost_toman FROM master_cost_history WHERE
             category=? AND subtype=? AND size=? AND effective_date<=?
             ORDER BY effective_date DESC LIMIT 1""",
             (category,subtype,candidate,date_key)).fetchone()
        if r is not None:return int(r[0])
    return sku.get("cost_toman")

def dated_rows(conn,as_of=None):
    date_key=valid_date(as_of or today())
    result=[]
    for row in conn.execute("SELECT * FROM master_products"):
        sku=dict(row)
        qty=int(sku["seller_stock"])+int(sku["khorshid_stock"])
        cost=dated_cost(conn,sku,date_key)
        result.append({**sku,"quantity":qty,"effective_cost":cost,
            "value":(qty*cost if cost is not None else None)})
    return result

def capital_snapshot(conn,as_of=None):
    # Historical stock quantities are NOT reconstructed. A past date uses
    # current quantities valued at past rates, and must be labeled as such.
    date_key=valid_date(as_of or today())
    rows=dated_rows(conn,date_key)
    categories={}
    total=0;units=0;unknown_count=0;unknown_units=0
    for row in rows:
        cat=categories.setdefault(row["category"],{"quantity":0,"known_value":0,"missing_cost_units":0})
        qty=row["quantity"]
        cat["quantity"]+=qty;units+=qty
        if qty and row["effective_cost"] is None:
            cat["missing_cost_units"]+=qty;unknown_units+=qty;unknown_count+=1
        elif row["value"] is not None:
            cat["known_value"]+=row["value"];total+=row["value"]
    return {"as_of":date_key,"stock_as_of":today(),"units":units,
            "known_value":total,"unknown_units":unknown_units,"unknown_sku_count":unknown_count,
            "total_value":total if unknown_units==0 else None,
            "categories":categories}
