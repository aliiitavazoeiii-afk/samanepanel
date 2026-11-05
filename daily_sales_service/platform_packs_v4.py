"""Six-slot platform bundles, per-size variants and atomic shared SKU sales.

V3 single-SKU listings/sales are preserved unchanged for audit and backwards
compatibility. V4 selling prices attach to a platform listing SIZE, not to a
generic physical SKU. Components resolve to exact stock SKUs at definition.
"""
import json
import uuid
from collections import Counter, defaultdict

from .engine import ImportErrorDetail, money
from .master_engine import CATEGORIES, now
from .effective_costs import dated_cost, today, valid_date
def family_title(sku):
    # Keep the display-only grouping independent from the FastAPI UI import
    # to avoid circular imports during SQLite schema initialization.
    label=str(sku["title"])
    color=str(sku["color"])
    suffix=" - "+color
    return label[:-len(suffix)] if color not in ("","-") and label.endswith(suffix) else label

from .platform_catalog import SALE_CHANNELS, PLATFORMS

SCHEMA = """
CREATE TABLE IF NOT EXISTS platform_bundle_models (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 channel TEXT NOT NULL,
 category TEXT NOT NULL,
 subtype TEXT NOT NULL DEFAULT '',
 model_title TEXT NOT NULL,
 title TEXT NOT NULL,
 pack_qty INTEGER NOT NULL CHECK(pack_qty BETWEEN 1 AND 6),
 colors_json TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS platform_bundle_variants (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 bundle_id INTEGER NOT NULL REFERENCES platform_bundle_models(id),
 size TEXT NOT NULL,
 price_toman INTEGER CHECK(price_toman IS NULL OR price_toman > 0),
 active INTEGER NOT NULL DEFAULT 1,
 updated_at TEXT NOT NULL,
 UNIQUE(bundle_id,size)
);
CREATE TABLE IF NOT EXISTS platform_bundle_parts (
 variant_id INTEGER NOT NULL REFERENCES platform_bundle_variants(id),
 position INTEGER NOT NULL CHECK(position BETWEEN 1 AND 6),
 master_id INTEGER NOT NULL REFERENCES master_products(id),
 PRIMARY KEY(variant_id,position)
);
CREATE INDEX IF NOT EXISTS idx_bundle_parts_master ON platform_bundle_parts(master_id);
CREATE TABLE IF NOT EXISTS platform_bundle_sales (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 channel TEXT NOT NULL,
 variant_id INTEGER NOT NULL REFERENCES platform_bundle_variants(id),
 sale_date TEXT NOT NULL,
 external_ref TEXT,
 packs INTEGER NOT NULL CHECK(packs>0),
 units INTEGER NOT NULL CHECK(units>0),
 warehouse TEXT NOT NULL CHECK(warehouse IN ('home','khorshid')),
 price_per_pack INTEGER NOT NULL CHECK(price_per_pack>0),
 gross_toman INTEGER NOT NULL,
 cogs_toman INTEGER,
 commission_toman INTEGER,
 created_at TEXT NOT NULL,
 UNIQUE(channel,external_ref)
);
CREATE TABLE IF NOT EXISTS platform_bundle_sale_parts (
 sale_id INTEGER NOT NULL REFERENCES platform_bundle_sales(id),
 master_id INTEGER NOT NULL REFERENCES master_products(id),
 units INTEGER NOT NULL CHECK(units>0),
 cost_each_toman INTEGER,
 PRIMARY KEY(sale_id,master_id)
);
"""

def ensure_bundle_schema(conn):
    conn.executescript(SCHEMA)

def model_key(category,subtype,title):
    return json.dumps([category,subtype,title],ensure_ascii=False,separators=(",",":"))

def available_skus(conn,category):
    if category not in CATEGORIES:raise ImportErrorDetail("دسته‌بندی معتبر نیست.")
    return [dict(row) for row in conn.execute(
        "SELECT * FROM master_products WHERE active=1 AND category=? ORDER BY title,color,size,id",
        (category,))]

def available_models(conn,category):
    skus=available_skus(conn,category)
    groups={}
    for sku in skus:
        label=family_title(sku)
        sub=sku.get("subtype","")
        key=model_key(category,sub,label)
        entry=groups.setdefault(key,{"key":key,"title":label,"subtype":sub,"sizes":set(),"colors":set()})
        entry["sizes"].add(sku["size"])
        entry["colors"].add(sku["color"])
    return [{**x,"sizes":sorted(x["sizes"]),"colors":sorted(x["colors"])}
            for x in sorted(groups.values(),key=lambda v:(v["title"],v["subtype"]))]

def _validate_input(conn,channel,category,key,pack_qty,colors,sizes,title):
    if channel not in SALE_CHANNELS:raise ImportErrorDetail("پلتفرم نامعتبر است.")
    if category not in CATEGORIES:raise ImportErrorDetail("دسته‌بندی نامعتبر است.")
    if channel=="mold" and category!="قالب":raise ImportErrorDetail("پلتفرم قالب‌ها فقط دسته قالب را قبول می‌کند.")
    try:count=int(pack_qty)
    except (TypeError,ValueError):raise ImportErrorDetail("تعداد داخل بسته معتبر نیست.")
    if count<1 or count>6:raise ImportErrorDetail("تعداد داخل بسته باید بین ۱ تا ۶ عدد باشد.")
    if isinstance(colors,str):
        try:colors=json.loads(colors)
        except (ValueError,TypeError):raise ImportErrorDetail("رنگ‌های بسته معتبر نیست.")
    if not isinstance(colors,(list,tuple)) or len(colors)!=count or any(not isinstance(c,str) for c in colors):
        raise ImportErrorDetail("برای هر عدد داخل بسته دقیقاً یک رنگ انتخاب کن.")
    if not isinstance(sizes,(list,tuple)) or not sizes or len(set(sizes))!=len(sizes):
        raise ImportErrorDetail("حداقل یک سایز یکتا را انتخاب کن.")
    if len(sizes)>25:raise ImportErrorDetail("تعداد سایز انتخابی بیش از حد مجاز است.")
    all_models={m["key"]:m for m in available_models(conn,category)}
    group=all_models.get(key)
    if group is None:raise ImportErrorDetail("مدل انتخاب‌شده در تعریف محصولات موجود نیست.")
    if any(c not in group["colors"] for c in colors):
        raise ImportErrorDetail("یک یا چند رنگ در این مدل تعریف نشده‌اند.")
    if any(s not in group["sizes"] or not isinstance(s,str) for s in sizes):
        raise ImportErrorDetail("یک یا چند سایز برای این مدل تعریف نشده‌اند.")
    text=str(title or "").strip() or f'{group["title"]} - پک {count} عددی'
    if len(text)>220:raise ImportErrorDetail("عنوان طولانی است.")
    # Require an exact unambiguous SKU for each (size, slot color).
    skus=available_skus(conn,category)
    by_color_size=defaultdict(list)
    for sku in skus:
        if family_title(sku)==group["title"] and sku.get("subtype","")==group["subtype"]:
            by_color_size[(sku["color"],sku["size"])].append(sku["id"])
    components={}
    for size in sizes:
        mids=[]
        for color in colors:
            matches=by_color_size.get((color,size),[])
            if len(matches)!=1:
                if not matches:raise ImportErrorDetail(f"برای رنگ «{color}» و سایز «{size}» کالای موجودی تعریف نشده است.")
                raise ImportErrorDetail(f"رنگ «{color}» و سایز «{size}» بیش از یک SKU دارد؛ ابتدا تعاریف تکراری را رفع کن.")
            mids.append(matches[0])
        components[size]=mids
    return group,count,text,components

def define_bundle(conn,channel,category,key,pack_qty,colors,sizes,title=""):
    group,count,title,components=_validate_input(conn,channel,category,key,pack_qty,colors,sizes,title)
    conn.execute("BEGIN IMMEDIATE")
    try:
        code=conn.execute("""INSERT INTO platform_bundle_models
          (channel,category,subtype,model_title,title,pack_qty,colors_json,created_at)
          VALUES(?,?,?,?,?,?,?,?)""",
          (channel,category,group["subtype"],group["title"],title,count,
           json.dumps(list(colors),ensure_ascii=False),now()))
        bundle_id=int(code.lastrowid)
        result=[]
        for size,mids in components.items():
            v=conn.execute("""INSERT INTO platform_bundle_variants(bundle_id,size,updated_at)
               VALUES(?,?,?)""",(bundle_id,size,now()))
            vid=int(v.lastrowid)
            conn.executemany("""INSERT INTO platform_bundle_parts(variant_id,position,master_id)
               VALUES(?,?,?)""",[(vid,pos,mid) for pos,mid in enumerate(mids,1)])
            result.append(vid)
        conn.execute("COMMIT")
        return {"bundle_id":bundle_id,"variant_ids":result}
    except Exception:
        conn.execute("ROLLBACK");raise

def list_bundle_groups(conn,channel,q="",limit=300):
    if channel not in SALE_CHANNELS:raise ImportErrorDetail("پلتفرم نامعتبر است.")
    sql="""SELECT b.*, COUNT(v.id) size_count,
          GROUP_CONCAT(v.size, ' · ') sizes,
          SUM(CASE WHEN v.price_toman IS NOT NULL THEN 1 ELSE 0 END) priced_count
          FROM platform_bundle_models b
          LEFT JOIN platform_bundle_variants v ON v.bundle_id=b.id
          WHERE b.channel=?"""
    args=[channel]
    if q:
        sql+=" AND (b.title LIKE ? OR b.model_title LIKE ? OR b.category LIKE ?)"
        args.extend([f"%{q}%"]*3)
    sql+=" GROUP BY b.id ORDER BY b.id DESC LIMIT ?";args.append(limit)
    result=[]
    for x in conn.execute(sql,args):
        r=dict(x);r["colors"]=json.loads(r["colors_json"])
        result.append(r)
    return result

def list_bundle_variants(conn,channel,query=""):
    if channel not in SALE_CHANNELS:raise ImportErrorDetail("پلتفرم نامعتبر است.")
    sql="""SELECT v.id AS variant_id, v.bundle_id,v.size,v.price_toman,v.active AS variant_active,
        b.channel,b.title,b.category,b.model_title,b.subtype,b.pack_qty,
        b.colors_json,b.active AS bundle_active
        FROM platform_bundle_variants v
        JOIN platform_bundle_models b ON b.id=v.bundle_id
        WHERE b.channel=?"""
    args=[channel]
    if query:
        sql+=" AND (b.title LIKE ? OR b.category LIKE ? OR b.model_title LIKE ? OR v.size LIKE ?)"
        args.extend([f"%{query}%"]*4)
    sql+=" ORDER BY b.id DESC,v.id LIMIT 1000"
    result=[]
    for row in conn.execute(sql,args):
        v=dict(row);v["colors"]=json.loads(v["colors_json"])
        result.append(v)
    return result

def save_variant_prices(conn,channel,prices):
    if channel not in SALE_CHANNELS:raise ImportErrorDetail("پلتفرم نامعتبر است.")
    if not prices:raise ImportErrorDetail("حداقل یک قیمت وارد کن.")
    conn.execute("BEGIN IMMEDIATE")
    try:
        validated=[]
        for vid,price in prices.items():
            item=conn.execute("""SELECT v.id FROM platform_bundle_variants v
              JOIN platform_bundle_models b ON b.id=v.bundle_id
              WHERE v.id=? AND b.channel=? AND b.active=1 AND v.active=1""",(int(vid),channel)).fetchone()
            if item is None:raise ImportErrorDetail("قیمت مربوط به کالای تعریف‌شده در این پلتفرم نیست.")
            val=money(price)
            if val<=0:raise ImportErrorDetail("قیمت فروش هر پک باید بیشتر از صفر باشد.")
            validated.append((val,now(),int(vid)))
        conn.executemany("UPDATE platform_bundle_variants SET price_toman=?,updated_at=? WHERE id=?",validated)
        conn.execute("COMMIT")
        return len(validated)
    except Exception:
        conn.execute("ROLLBACK");raise

def book_bundle_sale(conn,channel,variant_id,packs,warehouse,sale_date,order_ref=""):
    if channel not in SALE_CHANNELS:raise ImportErrorDetail("پلتفرم نامعتبر است.")
    if warehouse not in ("home","khorshid"):raise ImportErrorDetail("محل موجودی نامعتبر است.")
    day=valid_date(sale_date)
    if day>today():raise ImportErrorDetail("فروش در تاریخ آینده مجاز نیست.")
    try:
        vid=int(variant_id);n=int(packs)
    except (ValueError,TypeError):raise ImportErrorDetail("شناسه یا تعداد پک نامعتبر است.")
    if n<1 or n>100000:raise ImportErrorDetail("تعداد بسته باید مثبت باشد.")
    ref=str(order_ref or "").strip() or None
    if ref and len(ref)>100:raise ImportErrorDetail("شماره سفارش بیش از حد طولانی است.")
    column="seller_stock" if warehouse=="home" else "khorshid_stock"
    conn.execute("BEGIN IMMEDIATE")
    try:
        row=conn.execute("""SELECT v.*,b.channel,b.pack_qty,b.active AS bundle_active
           FROM platform_bundle_variants v JOIN platform_bundle_models b ON b.id=v.bundle_id
           WHERE v.id=? AND b.channel=?""",(vid,channel)).fetchone()
        if row is None or not row["active"] or not row["bundle_active"]:
            raise ImportErrorDetail("تنوع محصول پلتفرم موجود یا فعال نیست.")
        price=row["price_toman"]
        if price is None or int(price)<=0:
            raise ImportErrorDetail("اول قیمت فروش همین سایز را در قیمت‌گذاری پلتفرم وارد کن.")
        if ref and (conn.execute("SELECT id FROM platform_bundle_sales WHERE channel=? AND external_ref=?",
                                (channel,ref)).fetchone() or
                    conn.execute("SELECT id FROM platform_sales WHERE channel=? AND external_ref=?",
                                (channel,ref)).fetchone()):
            raise ImportErrorDetail("این شماره سفارش قبلاً ثبت شده است؛ موجودی دوباره کسر نشد.")
        parts=list(conn.execute("""SELECT p.position,m.* FROM platform_bundle_parts p
          JOIN master_products m ON m.id=p.master_id
          WHERE p.variant_id=? ORDER BY p.position""",(vid,)))
        if len(parts)!=int(row["pack_qty"]):
            raise ImportErrorDetail("ترکیب رنگ‌های این بسته ناقص است.")
        quantities=Counter(p["id"] for p in parts)
        all_costs={};cost_total=0
        for sku in parts:
            mid=sku["id"]
            if not sku["active"]:raise ImportErrorDetail("یکی از رنگ‌ها یا سایزهای داخل پک غیرفعال شده است.")
            amount=quantities[mid]*n
            if int(sku[column])<amount:
                raise ImportErrorDetail(f'موجودی رنگ {sku["color"]}، سایز {sku["size"]} برای {n} پک کافی نیست.')
            unit=dated_cost(conn,dict(sku),day)
            all_costs[mid]=unit
            if unit is None:cost_total=None
            elif cost_total is not None:cost_total+=int(unit)
        cur=conn.execute("""INSERT INTO platform_bundle_sales
          (channel,variant_id,sale_date,external_ref,packs,units,warehouse,
           price_per_pack,gross_toman,cogs_toman,commission_toman,created_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
          (channel,vid,day,ref,n,n*len(parts),warehouse,int(price),n*int(price),
           n*cost_total if cost_total is not None else None,None,now()))
        sale_id=int(cur.lastrowid)
        for mid,qty_per_pack in quantities.items():
            amount=qty_per_pack*n
            old=conn.execute(f"SELECT {column} FROM master_products WHERE id=?",(mid,)).fetchone()
            if old is None or int(old[0])<amount:
                raise ImportErrorDetail("موجودی حین ثبت تغییر کرد؛ کل فروش لغو شد.")
            after=int(old[0])-amount
            conn.execute(f"UPDATE master_products SET {column}=?,updated_at=? WHERE id=?",(after,now(),mid))
            conn.execute("""INSERT INTO master_stock_events
             (occurred_at,master_id,source,delta,balance_after,reference)
             VALUES(?,?,?,?,?,?)""",(now(),mid,warehouse,-amount,after,f"platform-v4:{channel}:{sale_id}"))
            conn.execute("""INSERT INTO platform_bundle_sale_parts
               (sale_id,master_id,units,cost_each_toman) VALUES(?,?,?,?)""",
               (sale_id,mid,amount,all_costs[mid]))
        conn.execute("COMMIT")
        return {"sale_id":sale_id,"packs":n,"units":n*len(parts),"gross":n*int(price),
                "cogs":n*cost_total if cost_total is not None else None}
    except Exception:
        conn.execute("ROLLBACK");raise

def new_sale_summary(conn,from_date=None,to_date=None):
    sql="""SELECT channel,COUNT(*) orders,SUM(packs) packs,SUM(units) units,
       SUM(gross_toman) gross,SUM(cogs_toman) known_cogs,
       COUNT(*)-COUNT(cogs_toman) unknown_cogs
       FROM platform_bundle_sales WHERE 1=1"""
    args=[]
    if from_date:sql+=" AND sale_date>=?";args.append(valid_date(from_date))
    if to_date:sql+=" AND sale_date<=?";args.append(valid_date(to_date))
    sql+=" GROUP BY channel"
    return {r["channel"]:dict(r) for r in conn.execute(sql,args)}
