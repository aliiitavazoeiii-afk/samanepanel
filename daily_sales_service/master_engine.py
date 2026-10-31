"""Single SKU master and stock ledger for the isolated sister business.

DigiKala variants are external identifiers; master_products are physical SKUs.
Every committed sale adjusts master stock, never the legacy DigiKala catalog stock.
Existing tables/sales remain intact. SQLite writes use BEGIN IMMEDIATE.
"""
from collections import defaultdict
from datetime import date, datetime, timezone
import hashlib
import json
import uuid

from .engine import (ImportErrorDetail, fee_unit, money, normalize,
                     parse_sales_xlsx, settings_for)

CATEGORIES = (
    "زیرپوش دارما", "شورت زنانه دارما", "شورت زنانه دیا",
    "بادیگارد", "قالب",
)

MASTER_SCHEMA = """
CREATE TABLE IF NOT EXISTS master_products (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 category TEXT NOT NULL,
 code TEXT NOT NULL,
 title TEXT NOT NULL,
 size TEXT NOT NULL DEFAULT '-',
 color TEXT NOT NULL DEFAULT '-',
 sale_price_toman INTEGER NOT NULL DEFAULT 0 CHECK(sale_price_toman>=0),
 cost_toman INTEGER CHECK(cost_toman>=0),
 seller_stock INTEGER NOT NULL DEFAULT 0 CHECK(seller_stock>=0),
 digikala_stock INTEGER NOT NULL DEFAULT 0 CHECK(digikala_stock>=0),
 active INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(category,code,size,color)
);
CREATE INDEX IF NOT EXISTS idx_master_category ON master_products(category);
CREATE TABLE IF NOT EXISTS master_stock_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 occurred_at TEXT NOT NULL,
 master_id INTEGER NOT NULL REFERENCES master_products(id),
 source TEXT NOT NULL,
 delta INTEGER NOT NULL,
 balance_after INTEGER NOT NULL,
 reference TEXT NOT NULL
);
"""

def now():
    return datetime.now(timezone.utc).isoformat()

def ensure_schema(conn):
    conn.executescript(MASTER_SCHEMA)
    fields = {x["name"] for x in conn.execute("PRAGMA table_info(products)")}
    if "master_id" not in fields:
        conn.execute("ALTER TABLE products ADD COLUMN master_id INTEGER REFERENCES master_products(id)")
    if "sale_price_toman" not in fields:
        conn.execute("ALTER TABLE products ADD COLUMN sale_price_toman INTEGER")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dk_master_id ON products(master_id)")

def add_master(conn, category, code, title, size="-", color="-", sale_price=0, cost=None):
    category = str(category or "").strip()
    code = str(code or "").strip()
    title = str(title or "").strip()
    size = str(size or "-").strip() or "-"
    color = str(color or "-").strip() or "-"
    if category not in CATEGORIES:
        raise ImportErrorDetail("دسته‌بندی محصول نامعتبر است.")
    if not code or not title or len(code)>90 or len(title)>220 or len(size)>60 or len(color)>60:
        raise ImportErrorDetail("کد، عنوان، رنگ یا سایز محصول نامعتبر است.")
    price = money(sale_price)
    unit_cost = None if cost in (None, "") else money(cost)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """INSERT INTO master_products(category,code,title,size,color,sale_price_toman,cost_toman,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (category, code, title, size, color, price, unit_cost, now(), now()),
        )
        conn.execute("COMMIT")
        return row.lastrowid
    except Exception as exc:
        if conn.in_transaction: conn.execute("ROLLBACK")
        if "UNIQUE constraint failed" in str(exc):
            raise ImportErrorDetail("این کد با همین دسته، رنگ و سایز قبلاً ثبت شده است.") from exc
        raise

def update_master(conn, master_id, title, price, cost, active=True):
    title = str(title or "").strip()
    if not title or len(title)>220: raise ImportErrorDetail("عنوان نامعتبر است.")
    price = money(price)
    cost = None if cost in (None, "") else money(cost)
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("UPDATE master_products SET title=?,sale_price_toman=?,cost_toman=?,active=?,updated_at=? WHERE id=?",
            (title, price, cost, 1 if active else 0, now(), master_id))
        if not row.rowcount: raise ImportErrorDetail("محصول پیدا نشد.")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK"); raise

def adjust_master_stock(conn, master_id, source, new_stock, reason):
    if source not in ("seller", "digikala"):
        raise ImportErrorDetail("محل موجودی نامعتبر است.")
    stock = money(new_stock)
    reason = str(reason or "").strip()
    if len(reason)<3: raise ImportErrorDetail("علت اصلاح موجودی باید مشخص باشد.")
    column = "seller_stock" if source=="seller" else "digikala_stock"
    conn.execute("BEGIN IMMEDIATE")
    try:
        old = conn.execute(f"SELECT {column} FROM master_products WHERE id=?", (master_id,)).fetchone()
        if old is None: raise ImportErrorDetail("محصول تعریف نشده است.")
        delta = stock-int(old[0])
        conn.execute(f"UPDATE master_products SET {column}=?,updated_at=? WHERE id=?",(stock,now(),master_id))
        conn.execute("""INSERT INTO master_stock_events(occurred_at,master_id,source,delta,balance_after,reference)
                         VALUES (?,?,?,?,?,?)""", (now(),master_id,source,delta,"manual:"+reason[:200]))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK");raise
    return delta

def map_variant(conn, variant_id, master_id, sale_price):
    price = None if sale_price in ("",None) else money(sale_price)
    conn.execute("BEGIN IMMEDIATE")
    try:
        variant = conn.execute("SELECT master_id FROM products WHERE variant_id=?", (variant_id,)).fetchone()
        master = conn.execute("SELECT id,active FROM master_products WHERE id=?", (master_id,)).fetchone()
        if not variant: raise ImportErrorDetail("کد تنوع دیجی‌کالا پیدا نشد.")
        if not master or not master["active"]: raise ImportErrorDetail("محصول اصلی تعریف نشده یا غیرفعال است.")
        existing = conn.execute("SELECT 1 FROM sales WHERE variant_id=? LIMIT 1", (variant_id,)).fetchone()
        if existing and variant["master_id"]!=master_id:
            raise ImportErrorDetail("این تنوع فروش ثبت‌شده دارد؛ برای تغییر اتصال، ابتدا سوابق فروش و موجودی باید تطبیق داده شوند.")
        conn.execute("UPDATE products SET master_id=?,sale_price_toman=? WHERE variant_id=?",
                     (master_id,price,variant_id))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK");raise

def strict_preview(conn,sale_date,source,files):
    try: date.fromisoformat(sale_date)
    except ValueError: raise ImportErrorDetail("تاریخ باید YYYY-MM-DD باشد.")
    if source not in ("seller","digikala"): raise ImportErrorDetail("مبدأ موجودی نامعتبر است.")
    variants={int(r["variant_id"]):r for r in conn.execute("SELECT * FROM products")}
    masters={int(r["id"]):r for r in conn.execute("SELECT * FROM master_products")}
    by_title=defaultdict(list)
    for v in variants.values(): by_title[v["title_key"]].append(v)
    entries={}; errors=[]; ignored=0; fallback=0
    sha=hashlib.sha256()
    for filename,data in files:
        sha.update(filename.encode()); sha.update(data)
        parsed,skipped=parse_sales_xlsx(data);ignored+=skipped
        for row in parsed:
            var=None
            if row["variant_id"]:
                try: var=variants.get(int(row["variant_id"]))
                except ValueError: pass
            elif row["title"]:
                hits=by_title[normalize(row["title"])]
                if len(hits)==1: var=hits[0]
            if var is None:
                errors.append(f"{filename} ردیف {row['row']}: کد تنوع ناشناخته یا عنوان مبهم است.")
                continue
            mid=var["master_id"]
            master=masters.get(int(mid)) if mid is not None else None
            if not var["active"] or master is None or not master["active"]:
                errors.append(f"کد تنوع {var['variant_id']} هنوز به یک محصول فعال در «تعریف محصولات» متصل نیست.")
                continue
            price=row["price"]
            if price is None:
                price=var["sale_price_toman"] if var["sale_price_toman"] is not None else master["sale_price_toman"]
                fallback+=1
            if price<=0:
                errors.append(f"کد {var['variant_id']}: قیمت فروش تعریف نشده است.")
                continue
            key=(int(var["variant_id"]),price)
            entries[key]=entries.get(key,0)+row["qty"]
    if errors:return {"errors":errors,"rows":[],"ignored":ignored,"fallback_prices":fallback}
    by_variant=defaultdict(list)
    for (vid,p),qty in entries.items():by_variant[vid].append((p,qty))
    if any(len(v)>1 for v in by_variant.values()):
        return {"errors":["یک کد تنوع با چند قیمت در فایل وارد شده است."],"rows":[],"ignored":ignored,"fallback_prices":fallback}
    existing={r["variant_id"]:r for r in conn.execute("SELECT * FROM sales WHERE sale_date=? AND source=?",(sale_date,source))}
    cfg=settings_for(conn);prepared=[]
    for vid,items in sorted(by_variant.items()):
        price,qty=items[0];master=masters[int(variants[vid]["master_id"])]
        fee=fee_unit(price,master["category"],cfg)
        prepared.append({"variant_id":vid,"master_id":master["id"],
                         "title":master["title"]+" / "+master["color"]+" / "+master["size"],
                         "category":master["category"],"qty":qty,"price":price,
                         "cost":master["cost_toman"],**fee})
    old_per=defaultdict(int);new_per=defaultdict(int)
    for vid,old in existing.items():
        variant=variants.get(vid)
        if not variant or variant["master_id"] is None:
            errors.append(f"فروش قبلی کد {vid} بدون اتصال محصول است؛ اصلاح خودکار موجودی امن نیست.")
            continue
        old_per[int(variant["master_id"])]+=int(old["qty"])
    for item in prepared:new_per[int(item["master_id"])]+=int(item["qty"])
    col="seller_stock" if source=="seller" else "digikala_stock"
    changes=[]
    for mid in set(old_per)|set(new_per):
        master=masters.get(mid)
        if master is None:
            errors.append(f"محصول اصلی {mid} پیدا نشد.");continue
        remaining=int(master[col])+old_per[mid]-new_per[mid]
        if remaining<0:
            errors.append(f"موجودی ناکافی: {master['code']} / {master['color']} / {master['size']}؛ موجود {master[col]}، فروش جدید {new_per[mid]}.")
        changes.append({"master_id":mid,"delta":old_per[mid]-new_per[mid],"stock_after":remaining})
    return {"errors":errors,"rows":prepared,"sale_date":sale_date,"source":source,
            "ignored":ignored,"fallback_prices":fallback,"files_count":len(files),
            "files_sha256":sha.hexdigest(),
            "known_cost_count":sum(1 for r in prepared if r["cost"] is not None),
            "stock_changes":changes}

def strict_commit(conn,token):
    conn.execute("BEGIN IMMEDIATE")
    try:
        found=conn.execute("SELECT * FROM previews WHERE token=?",(token,)).fetchone()
        if found is None:raise ImportErrorDetail("پیش‌نمایش پیدا نشد یا قبلاً ثبت شده است.")
        created=datetime.fromisoformat(found["created_at"])
        if (datetime.now(timezone.utc)-created).total_seconds()>1800:
            raise ImportErrorDetail("اعتبار پیش‌نمایش تمام شده؛ دوباره بارگذاری کن.")
        p=json.loads(found["payload"])
        if p.get("errors"):raise ImportErrorDetail("پیش‌نمایش معتبر نیست.")
        day,source=p["sale_date"],p["source"]
        if source not in ("seller","digikala"):raise ImportErrorDetail("مبدأ نامعتبر است.")
        old={r["variant_id"]:r for r in conn.execute("SELECT * FROM sales WHERE sale_date=? AND source=?",(day,source))}
        new={r["variant_id"]:r for r in p["rows"]}
        old_per=defaultdict(int);new_per=defaultdict(int)
        all_variants=set(old)|set(new)
        links={}
        for vid in all_variants:
            link=conn.execute("SELECT master_id FROM products WHERE variant_id=?",(vid,)).fetchone()
            if link is None or link["master_id"] is None:
                raise ImportErrorDetail(f"کد {vid} به محصول اصلی متصل نیست.")
            links[vid]=int(link["master_id"])
            if vid in new and int(new[vid]["master_id"])!=links[vid]:
                raise ImportErrorDetail(f"اتصال محصول {vid} تغییر کرده؛ پیش‌نمایش جدید بگیر.")
            if vid in old:old_per[links[vid]]+=int(old[vid]["qty"])
            if vid in new:new_per[links[vid]]+=int(new[vid]["qty"])
        col="seller_stock" if source=="seller" else "digikala_stock"
        adjustments={}
        for mid in set(old_per)|set(new_per):
            row=conn.execute(f"SELECT {col} FROM master_products WHERE id=?",(mid,)).fetchone()
            delta=old_per[mid]-new_per[mid]
            if row is None or int(row[0])+delta<0:
                raise ImportErrorDetail("موجودی یا اتصال کالا تغییر کرده؛ پیش‌نمایش جدید بگیر.")
            adjustments[mid]=(delta,int(row[0])+delta)
        for mid,(delta,balance) in adjustments.items():
            if not delta:continue
            conn.execute(f"UPDATE master_products SET {col}=?,updated_at=? WHERE id=?",
                         (balance,now(),mid))
            conn.execute("""INSERT INTO master_stock_events(occurred_at,master_id,source,delta,balance_after,reference)
                VALUES (?,?,?,?,?,?)""", (now(),mid,source,delta,f"digikala:{day}:{source}:{token}"))
        conn.execute("DELETE FROM sales WHERE sale_date=? AND source=?",(day,source))
        for x in p["rows"]:
            conn.execute("""INSERT INTO sales(sale_date,source,variant_id,qty,price_toman,commission_toman,processing_toman,vat_toman,fee_toman,cost_toman)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (day,source,x["variant_id"],x["qty"],x["price"],x["commission"],x["processing"],x["vat"],x["fee"],x["cost"]))
        conn.execute("""INSERT INTO import_audit(committed_at,sale_date,source,file_sha256,item_count,line_count)
            VALUES (?,?,?,?,?,?)""",
            (now(),day,source,p["files_sha256"],sum(x["qty"] for x in p["rows"]),len(p["rows"])))
        conn.execute("DELETE FROM previews WHERE token=?",(token,))
        conn.execute("COMMIT")
        return {"date":day,"source":source,"units":sum(x["qty"] for x in p["rows"]),"lines":len(p["rows"])}
    except Exception:
        if conn.in_transaction: conn.execute("ROLLBACK")
        raise
