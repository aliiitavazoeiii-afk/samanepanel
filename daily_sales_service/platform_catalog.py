"""Marketplace listings are selling units linked to one canonical physical SKU.

A pack is a quantity multiplier, never another inventory balance. All sales
withdraw from the same master_products home/KhorShid balances transactionally.
"""
import uuid
from .engine import ImportErrorDetail, money
from .master_engine import CATEGORIES, now
from .master_v2_logic import CHANNELS, channel_price_for
from .effective_costs import dated_cost, today, valid_date

PLATFORMS = {"digikala":"دیجی‌کالا","basalam":"باسلام","site":"سایت","mold":"قالب‌ها"}
SALE_CHANNELS = ("basalam","site","mold")
SCHEMA = """
CREATE TABLE IF NOT EXISTS platform_listings (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 channel TEXT NOT NULL,
 listing_code TEXT NOT NULL,
 title TEXT NOT NULL,
 master_id INTEGER NOT NULL REFERENCES master_products(id),
 pack_qty INTEGER NOT NULL CHECK(pack_qty>=1 AND pack_qty<=100),
 active INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(channel,listing_code)
);
CREATE INDEX IF NOT EXISTS idx_platform_listing_stock ON platform_listings(master_id);
CREATE TABLE IF NOT EXISTS platform_sales (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 channel TEXT NOT NULL,
 listing_id INTEGER NOT NULL REFERENCES platform_listings(id),
 sale_date TEXT NOT NULL,
 external_ref TEXT,
 packs INTEGER NOT NULL CHECK(packs>0),
 units INTEGER NOT NULL CHECK(units>0),
 warehouse TEXT NOT NULL,
 unit_sale_price INTEGER NOT NULL CHECK(unit_sale_price>=0),
 cost_per_unit INTEGER,
 gross_toman INTEGER NOT NULL,
 cogs_toman INTEGER,
 commission_toman INTEGER,
 created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS unique_platform_order
 ON platform_sales(channel,external_ref) WHERE external_ref IS NOT NULL;
"""

def ensure_platforms(conn):
    conn.executescript(SCHEMA)

def create_listing(conn,channel,master_id,title,pack_qty):
    if channel not in SALE_CHANNELS:raise ImportErrorDetail("پلتفرم نامعتبر است.")
    try:mid=int(master_id);packs=int(pack_qty)
    except (ValueError,TypeError):raise ImportErrorDetail("کالا یا تعداد پک نامعتبر است.")
    if packs<1 or packs>100:raise ImportErrorDetail("تعداد هر پک باید بین ۱ تا ۱۰۰ عدد باشد.")
    master=conn.execute("SELECT * FROM master_products WHERE id=? AND active=1",(mid,)).fetchone()
    if master is None:raise ImportErrorDetail("کالای پایه در تعریف محصولات وجود ندارد یا غیرفعال است.")
    if channel=="mold" and master["category"]!="قالب":
        raise ImportErrorDetail("در پلتفرم قالب‌ها فقط قالب قابل ثبت است.")
    title=str(title or "").strip() or str(master["title"])
    if len(title)>220:raise ImportErrorDetail("نام محصول بیش از حد طولانی است.")
    code="PL-"+uuid.uuid4().hex[:14]
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur=conn.execute("""INSERT INTO platform_listings
          (channel,listing_code,title,master_id,pack_qty,created_at,updated_at)
          VALUES (?,?,?,?,?,?,?)""",(channel,code,title,mid,packs,now(),now()))
        conn.execute("COMMIT")
        return int(cur.lastrowid)
    except Exception:
        conn.execute("ROLLBACK");raise

def list_listings(conn,channel,query="",category="",max_rows=300):
    if channel not in SALE_CHANNELS:raise ImportErrorDetail("پلتفرم نامعتبر است.")
    sql="""SELECT l.*,m.category,m.subtype,m.title AS master_title,m.color,m.size,
      m.seller_stock,m.khorshid_stock,m.active AS master_active,
      cp.price_toman AS unit_price
      FROM platform_listings l
      JOIN master_products m ON m.id=l.master_id
      LEFT JOIN master_channel_prices cp ON cp.master_id=m.id AND cp.channel=l.channel
      WHERE l.channel=?"""
    params=[channel]
    if category in CATEGORIES:sql+=" AND m.category=?";params.append(category)
    if query:
        sql+=" AND (l.title LIKE ? OR l.listing_code LIKE ? OR m.title LIKE ? OR m.color LIKE ? OR m.size LIKE ?)"
        params.extend(["%"+query+"%"]*5)
    sql+=" ORDER BY l.id DESC LIMIT ?";params.append(max_rows)
    return [dict(r) for r in conn.execute(sql,params)]

def set_listing_active(conn,listing_id,channel,active):
    if channel not in SALE_CHANNELS:raise ImportErrorDetail("پلتفرم نامعتبر است.")
    row=conn.execute("UPDATE platform_listings SET active=?,updated_at=? WHERE id=? AND channel=?",
        (int(bool(active)),now(),int(listing_id),channel))
    if not row.rowcount:raise ImportErrorDetail("محصول پلتفرم پیدا نشد.")

def book_sale(conn,channel,listing_id,packs,warehouse,sale_date,order_ref=""):
    if channel not in SALE_CHANNELS:raise ImportErrorDetail("پلتفرم نامعتبر است.")
    if warehouse not in ("home","khorshid"):raise ImportErrorDetail("انبار نامعتبر است.")
    date_key=valid_date(sale_date)
    if date_key>today():raise ImportErrorDetail("فروش آینده مجاز نیست.")
    try:n=int(packs);lid=int(listing_id)
    except (TypeError,ValueError):raise ImportErrorDetail("تعداد بسته نامعتبر است.")
    if n<=0 or n>100000:raise ImportErrorDetail("تعداد بسته باید مثبت باشد.")
    order_ref=str(order_ref or "").strip() or None
    if order_ref and len(order_ref)>100:raise ImportErrorDetail("شناسه سفارش بیش از حد طولانی است.")
    col={"home":"seller_stock","khorshid":"khorshid_stock"}[warehouse]
    conn.execute("BEGIN IMMEDIATE")
    try:
        row=conn.execute("""SELECT l.*,m.category,m.subtype,m.size,m.cost_toman,m.title AS master_title,
            m.active AS master_active FROM platform_listings l
            JOIN master_products m ON m.id=l.master_id
            WHERE l.id=? AND l.channel=?""",(lid,channel)).fetchone()
        if row is None or not row["active"] or not row["master_active"]:
            raise ImportErrorDetail("محصول پلتفرم پیدا نشد یا غیرفعال است.")
        if order_ref and conn.execute("SELECT 1 FROM platform_sales WHERE channel=? AND external_ref=?",
            (channel,order_ref)).fetchone():
            raise ImportErrorDetail("این شماره سفارش قبلاً ثبت شده است؛ موجودی دوباره کسر نشد.")
        unit_price=channel_price_for(conn,row["master_id"],channel)
        if unit_price is None or unit_price<=0:
            raise ImportErrorDetail("ابتدا قیمت فروش این کالا را در قیمت‌گذاری مشخص کن.")
        per_unit_cost=dated_cost(conn,dict(row),date_key)
        units=n*int(row["pack_qty"])
        current=conn.execute(f"SELECT {col} FROM master_products WHERE id=?",(row["master_id"],)).fetchone()
        if current is None or int(current[0])<units:
            raise ImportErrorDetail("موجودی انبار انتخابی برای این تعداد بسته کافی نیست.")
        after=int(current[0])-units
        conn.execute(f"UPDATE master_products SET {col}=?,updated_at=? WHERE id=?",(after,now(),row["master_id"]))
        cur=conn.execute("""INSERT INTO platform_sales
          (channel,listing_id,sale_date,external_ref,packs,units,warehouse,
           unit_sale_price,cost_per_unit,gross_toman,cogs_toman,commission_toman,created_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (channel,lid,date_key,order_ref,n,units,warehouse,unit_price,
           per_unit_cost,units*unit_price,units*per_unit_cost if per_unit_cost is not None else None,
           None,now()))
        conn.execute("""INSERT INTO master_stock_events
          (occurred_at,master_id,source,delta,balance_after,reference)
          VALUES(?,?,?,?,?,?)""",
          (now(),row["master_id"],warehouse,-units,after,f"platform:{channel}:{cur.lastrowid}"))
        conn.execute("COMMIT")
        return {"sale_id":cur.lastrowid,"units":units,"gross":units*unit_price}
    except Exception:
        conn.execute("ROLLBACK");raise

def sale_summary(conn,from_date=None,to_date=None):
    sql="SELECT channel,COUNT(*) orders,SUM(packs) packs,SUM(units) units,SUM(gross_toman) gross,SUM(cogs_toman) known_cogs,COUNT(*)-COUNT(cogs_toman) unknown_cogs FROM platform_sales WHERE 1=1"
    params=[]
    if from_date:sql+=" AND sale_date>=?";params.append(valid_date(from_date))
    if to_date:sql+=" AND sale_date<=?";params.append(valid_date(to_date))
    sql+=" GROUP BY channel"
    return {r["channel"]:dict(r) for r in conn.execute(sql,params)}
