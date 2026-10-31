"""Sister ERP phase 2: description-only definitions, two warehouses and price rules.

Existing master IDs, external variant links and sale snapshots are preserved.
The previous seller_stock column becomes the HOME balance. A new column holds
KHORSHID; the pre-existing digikala_stock is retained solely for historical
DigiKala-warehouse transactions and is NOT silently reassigned to KhorShid.
"""
import re
import sqlite3
import uuid
from collections import defaultdict

from .engine import ImportErrorDetail, money
from .master_engine import CATEGORIES, now

BODY_TYPES = ("اسلیپ", "پادار")
WAREHOUSES = {"home": "seller_stock", "khorshid": "khorshid_stock"}
CHANNELS = {"site": "فروش سایت", "basalam": "فروش باسلام", "mold": "فروش قالب"}
SIZES = {
    "زیرپوش دارما": ("S","M","L","XL","XXL","3XL","4XL"),
    "شورت زنانه دارما": ("M","L","XL","XXL","3XL","4XL"),
    "شورت زنانه دیا": ("M","L","XL","XXL","3XL","4XL"),
    "بادیگارد": ("S","M","L","XL","2XL","XXL","3XL","4XL"),
    "قالب": ("کوچک","متوسط","بزرگ"),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS master_cost_rules (
 category TEXT NOT NULL,
 subtype TEXT NOT NULL DEFAULT '',
 size TEXT NOT NULL DEFAULT '*',
 cost_toman INTEGER NOT NULL CHECK(cost_toman>=0),
 updated_at TEXT NOT NULL,
 PRIMARY KEY (category,subtype,size)
);
CREATE TABLE IF NOT EXISTS master_channel_prices (
 master_id INTEGER NOT NULL REFERENCES master_products(id),
 channel TEXT NOT NULL,
 price_toman INTEGER NOT NULL CHECK(price_toman>=0),
 updated_at TEXT NOT NULL,
 PRIMARY KEY (master_id,channel)
);
CREATE TABLE IF NOT EXISTS master_transfers (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 occurred_at TEXT NOT NULL,
 master_id INTEGER NOT NULL REFERENCES master_products(id),
 from_location TEXT NOT NULL,
 to_location TEXT NOT NULL,
 quantity INTEGER NOT NULL,
 reference TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_master_history ON master_stock_events(master_id,id);
"""

def ensure_v2(conn):
    conn.executescript(SCHEMA)
    fields={x["name"] for x in conn.execute("PRAGMA table_info(master_products)")}
    if "subtype" not in fields:
        conn.execute("ALTER TABLE master_products ADD COLUMN subtype TEXT NOT NULL DEFAULT ''")
    if "khorshid_stock" not in fields:
        conn.execute("ALTER TABLE master_products ADD COLUMN khorshid_stock INTEGER NOT NULL DEFAULT 0 CHECK(khorshid_stock>=0)")
    # Historical 2026 body.xlsx imports carried slip/padar in the product
    # title/code but no subtype. Backfill only this classification, not balances.
    conn.execute("""UPDATE master_products SET subtype='اسلیپ'
                    WHERE category='بادیگارد' AND subtype=''
                      AND (code LIKE 'BG-SL-%' OR title LIKE '%اسلیپ%')""")
    conn.execute("""UPDATE master_products SET subtype='پادار'
                    WHERE category='بادیگارد' AND subtype=''
                      AND (code LIKE 'BG-PA-%' OR title LIKE '%پادار%')""")

def _clean(value,limit=220):
    value=re.sub(r"\s+"," ",str(value or "").strip())
    if not value or len(value)>limit:raise ImportErrorDetail("عنوان یا گزینه واردشده نامعتبر است.")
    return value

def _normalize_subtype(category,subtype):
    subtype=str(subtype or "").strip()
    if category=="بادیگارد":
        if subtype not in BODY_TYPES:raise ImportErrorDetail("بادیگارد باید اسلیپ یا پادار باشد.")
    elif subtype:
        raise ImportErrorDetail("زیرگروه جداگانه فقط برای بادیگارد تعریف شده است.")
    return subtype

def _split_options(raw,defaults=("-",),limit=60):
    vals=[]
    for part in re.split(r"[,،;؛\n\r]+",str(raw or "")):
        val=part.strip()
        if val and val not in vals:
            vals.append(_clean(val,limit))
    if len(vals)>40:raise ImportErrorDetail("تعداد رنگ یا سایز بیش از حد مجاز است.")
    return tuple(vals or defaults)

def add_model(conn,category,title,subtype="",colors="",sizes=""):
    if category not in CATEGORIES:raise ImportErrorDetail("دسته‌بندی نامعتبر است.")
    title=_clean(title)
    subtype=_normalize_subtype(category,subtype)
    colors=_split_options(colors)
    sizes=_split_options(sizes, SIZES.get(category,("-" ,)))
    if category=="قالب":
        if any(s not in SIZES["قالب"] for s in sizes):
            raise ImportErrorDetail("سایزبندی قالب فقط کوچک، متوسط و بزرگ است.")
    conn.execute("BEGIN IMMEDIATE")
    try:
        # Same model/subtype is idempotently extended with new size/color cells.
        row=conn.execute("""SELECT code FROM master_products WHERE category=? AND title=? AND subtype=?
                            ORDER BY id LIMIT 1""",(category,title,subtype)).fetchone()
        code=row["code"] if row else "AUTO-"+uuid.uuid4().hex[:20]
        created=0
        for color in colors:
            for size in sizes:
                exists=conn.execute("""SELECT id FROM master_products
                    WHERE category=? AND code=? AND color=? AND size=?""",(category,code,color,size)).fetchone()
                if exists:continue
                conn.execute("""INSERT INTO master_products
                    (category,code,title,size,color,subtype,sale_price_toman,cost_toman,
                    seller_stock,digikala_stock,khorshid_stock,active,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,0,NULL,0,0,0,1,?,?)""",
                    (category,code,title,size,color,subtype,now(),now()))
                created+=1
        conn.execute("COMMIT")
        return created
    except Exception:
        conn.execute("ROLLBACK");raise

def rename_model(conn,master_id,title,active):
    title=_clean(title)
    conn.execute("BEGIN IMMEDIATE")
    try:
        row=conn.execute("SELECT category,code FROM master_products WHERE id=?",(master_id,)).fetchone()
        if not row:raise ImportErrorDetail("مدل پیدا نشد.")
        conn.execute("""UPDATE master_products SET title=?, active=?,updated_at=?
                        WHERE category=? AND code=?""",
                     (title,1 if active else 0,now(),row["category"],row["code"]))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK");raise

def list_models(conn,category="",subtype="",q=""):
    query="SELECT category,code,MAX(title) title,MAX(subtype) subtype,MIN(id) representative, COUNT(*) variants,MAX(active) active FROM master_products WHERE 1=1"
    params=[]
    if category in CATEGORIES:
        query+=" AND category=?";params.append(category)
    if subtype in BODY_TYPES:
        query+=" AND subtype=?";params.append(subtype)
    if q:
        query+=" AND (title LIKE ? OR color LIKE ? OR size LIKE ?)"
        params.extend(["%"+q+"%"]*3)
    query+=" GROUP BY category,code ORDER BY category,title,code"
    return [dict(row) for row in conn.execute(query,params)]

def sku_rows(conn,category,model_id=None,subtype="",active_only=True):
    query="SELECT * FROM master_products WHERE category=?";params=[category]
    if active_only:query+=" AND active=1"
    if model_id:
        model=conn.execute("SELECT code,category FROM master_products WHERE id=?",(model_id,)).fetchone()
        if model is None or model["category"]!=category:return []
        query+=" AND code=?";params.append(model["code"])
    if subtype in BODY_TYPES:query+=" AND subtype=?";params.append(subtype)
    query+=" ORDER BY title,color,size,id"
    return [dict(row) for row in conn.execute(query,params)]

def _warehouse_col(location):
    if location not in WAREHOUSES:raise ImportErrorDetail("محل موجودی باید خانه یا خورشید باشد.")
    return WAREHOUSES[location]

def batch_adjust(conn,category,model_id,size,location,values,reason):
    column=_warehouse_col(location)
    reason=_clean(reason,200)
    rows={r["id"]:r for r in sku_rows(conn,category,model_id)}
    pending=[]
    for master_id,target in values.items():
        if master_id not in rows:raise ImportErrorDetail("محصول خارج از فیلتر انتخابی است.")
        row=rows[master_id]
        if row["size"]!=size:raise ImportErrorDetail("سایز محصول با انتخاب تطبیق ندارد.")
        pending.append((master_id,money(target),int(row[column])))
    if not pending:raise ImportErrorDetail("حداقل یک مقدار برای اصلاح وارد کن.")
    conn.execute("BEGIN IMMEDIATE")
    try:
        changed=0
        for mid,target,_ in pending:
            current=conn.execute(f"SELECT {column} FROM master_products WHERE id=?",(mid,)).fetchone()
            if current is None:raise ImportErrorDetail("محصول تغییر کرده است.")
            old=int(current[0])
            if old==target:continue
            conn.execute(f"UPDATE master_products SET {column}=?,updated_at=? WHERE id=?",(target,now(),mid))
            conn.execute("""INSERT INTO master_stock_events
                 (occurred_at,master_id,source,delta,balance_after,reference)
                 VALUES (?,?,?,?,?,?)""",(now(),mid,location,target-old,target,"adjust:"+reason))
            changed+=1
        conn.execute("COMMIT")
        return changed
    except Exception:
        conn.execute("ROLLBACK");raise

def transfer(conn,master_id,source,quantity,reason):
    col_from=_warehouse_col(source)
    destination="khorshid" if source=="home" else "home"
    col_to=_warehouse_col(destination)
    qty=money(quantity)
    if qty<=0:raise ImportErrorDetail("تعداد انتقال باید مثبت باشد.")
    reason=_clean(reason,200)
    conn.execute("BEGIN IMMEDIATE")
    try:
        current=conn.execute(f"SELECT {col_from},{col_to} FROM master_products WHERE id=? AND active=1",(master_id,)).fetchone()
        if current is None:raise ImportErrorDetail("محصول فعال پیدا نشد.")
        old_src,old_dst=int(current[0]),int(current[1])
        if old_src<qty:raise ImportErrorDetail("موجودی مبدأ برای انتقال کافی نیست.")
        conn.execute(f"UPDATE master_products SET {col_from}=?,{col_to}=?,updated_at=? WHERE id=?",
                     (old_src-qty,old_dst+qty,now(),master_id))
        ref="transfer:"+uuid.uuid4().hex
        for loc,delta,balance in ((source,-qty,old_src-qty),(destination,qty,old_dst+qty)):
            conn.execute("""INSERT INTO master_stock_events
                 (occurred_at,master_id,source,delta,balance_after,reference)
                 VALUES (?,?,?,?,?,?)""",(now(),master_id,loc,delta,balance,ref+" "+reason))
        conn.execute("""INSERT INTO master_transfers
          (occurred_at,master_id,from_location,to_location,quantity,reference)
          VALUES (?,?,?,?,?,?)""",(now(),master_id,source,destination,qty,ref))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK");raise

def set_cost_rule(conn,category,subtype,size,cost):
    if category not in CATEGORIES:raise ImportErrorDetail("دسته‌بندی نامعتبر است.")
    subtype=_normalize_subtype(category,subtype)
    size=str(size or "*").strip()
    if category=="قالب" and size not in SIZES["قالب"]:
        raise ImportErrorDetail("برای قالب، اندازه کوچک، متوسط یا بزرگ را مشخص کن.")
    if category not in ("قالب","بادیگارد"):size="*"
    if category=="بادیگارد":size="*"  # per requested slip/padar cost
    price=money(cost)
    conn.execute("""INSERT INTO master_cost_rules(category,subtype,size,cost_toman,updated_at)
       VALUES(?,?,?,?,?) ON CONFLICT(category,subtype,size)
       DO UPDATE SET cost_toman=excluded.cost_toman,updated_at=excluded.updated_at""",
       (category,subtype,size,price,now()))
    return price

def cost_for(conn,sku):
    category,subtype,size=sku["category"],sku.get("subtype",""),sku["size"]
    for sp in (size,"*"):
        r=conn.execute("""SELECT cost_toman FROM master_cost_rules
            WHERE category=? AND subtype=? AND size=?""",(category,subtype,sp)).fetchone()
        if r is not None:return int(r[0])
    return sku.get("cost_toman")

def set_channel_prices(conn,channel,category,subtype,size,price,model_id=None):
    if channel not in CHANNELS:raise ImportErrorDetail("درگاه فروش نامعتبر است.")
    if category not in CATEGORIES:raise ImportErrorDetail("دسته‌بندی نامعتبر است.")
    if channel=="mold" and category!="قالب":raise ImportErrorDetail("فروش قالب فقط برای دسته قالب است.")
    subtype=_normalize_subtype(category,subtype)
    size=str(size or "*").strip()
    value=money(price)
    qs=sku_rows(conn,category,model_id=model_id,subtype=subtype)
    if size!="*":qs=[r for r in qs if r["size"]==size]
    if not qs:raise ImportErrorDetail("برای دسته و سایز انتخاب‌شده محصولی تعریف نشده است.")
    conn.execute("BEGIN IMMEDIATE")
    try:
        for sku in qs:
            conn.execute("""INSERT INTO master_channel_prices(master_id,channel,price_toman,updated_at)
                 VALUES(?,?,?,?) ON CONFLICT(master_id,channel)
                 DO UPDATE SET price_toman=excluded.price_toman,updated_at=excluded.updated_at""",
                 (sku["id"],channel,value,now()))
        conn.execute("COMMIT")
        return len(qs)
    except Exception:
        conn.execute("ROLLBACK");raise

def channel_price_for(conn,master_id,channel):
    if channel not in CHANNELS:raise ImportErrorDetail("درگاه فروش نامعتبر است.")
    r=conn.execute("SELECT price_toman FROM master_channel_prices WHERE master_id=? AND channel=?",
                   (master_id,channel)).fetchone()
    return int(r[0]) if r is not None else None

def batch_transfer(conn,category,model_id,size,source,quantities,reason):
    from_col=_warehouse_col(source)
    to_location="khorshid" if source=="home" else "home"
    to_col=_warehouse_col(to_location)
    reason=_clean(reason,200)
    rows={r["id"]:r for r in sku_rows(conn,category,model_id)}
    pending=[]
    for master_id,raw_qty in quantities.items():
        if master_id not in rows or rows[master_id]["size"]!=size:
            raise ImportErrorDetail("کالای انتقالی خارج از فیلتر انتخاب‌شده است.")
        qty=money(raw_qty)
        if qty>0:pending.append((master_id,qty))
    if not pending:raise ImportErrorDetail("حداقل یک تعداد برای انتقال وارد کن.")
    conn.execute("BEGIN IMMEDIATE")
    try:
        for mid,qty in pending:
            original=conn.execute(f"SELECT {from_col},{to_col} FROM master_products WHERE id=? AND active=1",(mid,)).fetchone()
            if original is None or int(original[0])<qty:
                raise ImportErrorDetail("موجودی مبدأ برای یکی از رنگ‌ها کافی نیست؛ هیچ انتقالی ثبت نشد.")
        reference="bulk-transfer:"+uuid.uuid4().hex
        total=0
        for mid,qty in pending:
            original=conn.execute(f"SELECT {from_col},{to_col} FROM master_products WHERE id=?",(mid,)).fetchone()
            old_src,old_dst=map(int,original)
            conn.execute(f"UPDATE master_products SET {from_col}=?,{to_col}=?,updated_at=? WHERE id=?",
                         (old_src-qty,old_dst+qty,now(),mid))
            for loc,delta,balance in ((source,-qty,old_src-qty),(to_location,qty,old_dst+qty)):
                conn.execute("""INSERT INTO master_stock_events
                     (occurred_at,master_id,source,delta,balance_after,reference)
                     VALUES (?,?,?,?,?,?)""",(now(),mid,loc,delta,balance,reference+" "+reason))
            conn.execute("""INSERT INTO master_transfers
              (occurred_at,master_id,from_location,to_location,quantity,reference)
              VALUES (?,?,?,?,?,?)""",(now(),mid,source,to_location,qty,reference))
            total+=qty
        conn.execute("COMMIT")
        return total
    except Exception:
        conn.execute("ROLLBACK");raise
