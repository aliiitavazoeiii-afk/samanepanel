"""Supplier purchases for physical Dia, Darma and Bodyguard inventory.

Separate from Mehr's mold ledger. Purchases and payments are atomic and
idempotent; correcting stock counts does not create supplier obligations.
All amounts are integer Toman; persisted dates use ISO Gregorian.
"""
import uuid
from .engine import ImportErrorDetail, money
from .effective_costs import today, valid_date
from .master_engine import now

CATEGORIES = ("زیرپوش دارما", "شورت زنانه دارما", "شورت زنانه دیا", "بادیگارد")
SCHEMA = """
CREATE TABLE IF NOT EXISTS sister_purchase_suppliers (
 id INTEGER PRIMARY KEY,
 name TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sister_purchase_orders (
 id INTEGER PRIMARY KEY,
 supplier_id INTEGER NOT NULL REFERENCES sister_purchase_suppliers(id),
 purchase_date TEXT NOT NULL,
 warehouse TEXT NOT NULL CHECK(warehouse IN ('home','khorshid')),
 supplier_invoice TEXT NOT NULL DEFAULT '',
 notes TEXT NOT NULL DEFAULT '',
 total_toman INTEGER NOT NULL CHECK(total_toman>0),
 request_key TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sister_purchase_lines (
 id INTEGER PRIMARY KEY,
 purchase_id INTEGER NOT NULL REFERENCES sister_purchase_orders(id),
 master_id INTEGER NOT NULL REFERENCES master_products(id),
 quantity INTEGER NOT NULL CHECK(quantity>0),
 unit_cost_toman INTEGER NOT NULL CHECK(unit_cost_toman>0),
 UNIQUE(purchase_id,master_id)
);
CREATE TABLE IF NOT EXISTS sister_purchase_payments (
 id INTEGER PRIMARY KEY,
 supplier_id INTEGER NOT NULL REFERENCES sister_purchase_suppliers(id),
 bank_id INTEGER NOT NULL REFERENCES sister_finance_accounts(id),
 paid_on TEXT NOT NULL,
 amount_toman INTEGER NOT NULL CHECK(amount_toman>0),
 notes TEXT NOT NULL DEFAULT '',
 request_key TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sister_purchase_supplier
 ON sister_purchase_orders(supplier_id,purchase_date);
CREATE INDEX IF NOT EXISTS idx_sister_purchase_payment_supplier
 ON sister_purchase_payments(supplier_id,paid_on);
"""

def ensure_schema(conn):
    conn.executescript(SCHEMA)

def _clean(value,limit=300):
    result=str(value or "").strip()
    if len(result)>limit:raise ImportErrorDetail("متن واردشده طولانی‌تر از حد مجاز است.")
    return result

def _day(day):
    value=valid_date(day)
    if value>today():raise ImportErrorDetail("ثبت خرید یا پرداخت با تاریخ آینده مجاز نیست.")
    return value

def supplier_totals(conn,supplier_id):
    sid=int(supplier_id)
    row=conn.execute("SELECT id,name FROM sister_purchase_suppliers WHERE id=?",(sid,)).fetchone()
    if row is None:raise ImportErrorDetail("تأمین‌کننده پیدا نشد.")
    purchased=int(conn.execute("""SELECT COALESCE(SUM(total_toman),0)
        FROM sister_purchase_orders WHERE supplier_id=?""",(sid,)).fetchone()[0])
    paid=int(conn.execute("""SELECT COALESCE(SUM(amount_toman),0)
        FROM sister_purchase_payments WHERE supplier_id=?""",(sid,)).fetchone()[0])
    return {"id":sid,"name":row["name"],"purchased":purchased,"paid":paid,"due":purchased-paid}

def suppliers(conn):
    return [supplier_totals(conn,r["id"]) for r in conn.execute(
        "SELECT id FROM sister_purchase_suppliers ORDER BY name")]

def _supplier_id(conn,name):
    name=_clean(name,120)
    if len(name)<2:raise ImportErrorDetail("نام تأمین‌کننده را وارد کن.")
    if "".join(name.split()).replace("ي","ی").replace("ك","ک")=="مهر":
        raise ImportErrorDetail("خرید قالب از «مه هر» فقط در بخش خرید مخصوص مه هر ثبت می‌شود.")
    conn.execute("""INSERT INTO sister_purchase_suppliers(name,created_at)
      VALUES (?,?) ON CONFLICT(name) DO NOTHING""",(name,now()))
    return conn.execute("SELECT id FROM sister_purchase_suppliers WHERE name=?",(name,)).fetchone()[0]

def register_purchase(conn,supplier,purchase_date,warehouse,items,request_key,
                      supplier_invoice="",notes=""):
    """Each row: (exact master SKU id, quantity, purchase cost per physical unit).

    Does not schedule/rewrite dated COGS rules: historical sales retain their
    original cost snapshots. Does not touch the old DigiKala 'products' table.
    """
    day=_day(purchase_date)
    if warehouse not in ("home","khorshid"):raise ImportErrorDetail("انبار مقصد نامعتبر است.")
    key=_clean(request_key,100)
    if not key:raise ImportErrorDetail("شناسه درخواست خرید الزامی است.")
    if not isinstance(items,(list,tuple)) or not items or len(items)>20:
        raise ImportErrorDetail("بین ۱ تا ۲۰ ردیف کالای خریداری‌شده وارد کن.")
    normalized=[];seen=set()
    for item in items:
        try:master_id,quantity,unit_cost=item
        except (TypeError,ValueError):raise ImportErrorDetail("اطلاعات ردیف خرید نامعتبر است.")
        try:mid=int(master_id)
        except (TypeError,ValueError):raise ImportErrorDetail("کد کالای خرید معتبر نیست.")
        qty=money(quantity);cost=money(unit_cost)
        if qty<1 or qty>100000:raise ImportErrorDetail("تعداد هر ردیف باید بین ۱ تا ۱۰۰٬۰۰۰ باشد.")
        if cost<1:raise ImportErrorDetail("قیمت خرید هر عدد باید بزرگ‌تر از صفر باشد.")
        if mid in seen:raise ImportErrorDetail("کالای تکراری را در یک ردیف با تعداد جمع‌شده ثبت کن.")
        seen.add(mid);normalized.append((mid,qty,cost))
    reference=_clean(supplier_invoice,100)
    notes=_clean(notes,500)
    column="seller_stock" if warehouse=="home" else "khorshid_stock"
    conn.execute("BEGIN IMMEDIATE")
    try:
        if conn.execute("SELECT 1 FROM sister_purchase_orders WHERE request_key=?",(key,)).fetchone():
            raise ImportErrorDetail("این خرید قبلاً ثبت شده است؛ موجودی دوباره اضافه نشد.")
        selected=[]
        for mid,qty,cost in normalized:
            sku=conn.execute("""SELECT id,category,active,seller_stock,khorshid_stock
                    FROM master_products WHERE id=?""",(mid,)).fetchone()
            if sku is None or not sku["active"] or sku["category"] not in CATEGORIES:
                raise ImportErrorDetail("فقط کالای فعال دیا، دارما و بادیگارد را با کد فیزیکی دقیق انتخاب کن.")
            selected.append((sku,qty,cost))
        sid=_supplier_id(conn,supplier)
        total=sum(qty*cost for _,qty,cost in selected)
        cur=conn.execute("""INSERT INTO sister_purchase_orders
          (supplier_id,purchase_date,warehouse,supplier_invoice,notes,total_toman,request_key,created_at)
          VALUES (?,?,?,?,?,?,?,?)""",(sid,day,warehouse,reference,notes,total,key,now()))
        purchase_id=int(cur.lastrowid)
        for sku,qty,cost in selected:
            mid=int(sku["id"])
            after=int(sku[column])+qty
            conn.execute("UPDATE master_products SET "+column+"=?,updated_at=? WHERE id=?",
                         (after,now(),mid))
            conn.execute("""INSERT INTO sister_purchase_lines
                  (purchase_id,master_id,quantity,unit_cost_toman)
                  VALUES (?,?,?,?)""",(purchase_id,mid,qty,cost))
            conn.execute("""INSERT INTO master_stock_events
                  (occurred_at,master_id,source,delta,balance_after,reference)
                  VALUES (?,?,?,?,?,?)""",(now(),mid,warehouse,qty,after,
                                           "supplier-purchase:"+str(purchase_id)))
        conn.execute("COMMIT")
        return purchase_id
    except Exception:
        conn.execute("ROLLBACK");raise

def register_supplier_payment(conn,supplier_id,bank_id,amount,paid_on,request_key,notes=""):
    day=_day(paid_on);val=money(amount)
    if val<1:raise ImportErrorDetail("مبلغ پرداخت باید مثبت باشد.")
    key=_clean(request_key,100)
    if not key:raise ImportErrorDetail("شناسه ثبت پرداخت الزامی است.")
    try:sid=int(supplier_id);bid=int(bank_id)
    except (ValueError,TypeError):raise ImportErrorDetail("حساب یا تأمین‌کننده نامعتبر است.")
    note=_clean(notes,500)
    conn.execute("BEGIN IMMEDIATE")
    try:
        if conn.execute("SELECT 1 FROM sister_purchase_payments WHERE request_key=?",(key,)).fetchone():
            raise ImportErrorDetail("این پرداخت قبلاً ثبت شده است.")
        bank=conn.execute("SELECT id FROM sister_finance_accounts WHERE id=? AND active=1",(bid,)).fetchone()
        if bank is None:raise ImportErrorDetail("حساب بانکی فعال انتخاب کن.")
        balance=supplier_totals(conn,sid)
        if val>balance["due"]:raise ImportErrorDetail("مبلغ پرداخت از بدهی ثبت‌شده بیشتر است.")
        row=conn.execute("""INSERT INTO sister_purchase_payments
          (supplier_id,bank_id,paid_on,amount_toman,notes,request_key,created_at)
          VALUES (?,?,?,?,?,?,?)""",(sid,bid,day,val,note,key,now()))
        payment_id=int(row.lastrowid)
        party_code="supplier-purchase-"+str(sid)
        party_title="تأمین‌کننده خرید: "+balance["name"]
        conn.execute("""INSERT INTO sister_finance_parties(code,title,is_platform,created_at)
          VALUES (?,?,0,?) ON CONFLICT(code) DO NOTHING""",(party_code,party_title,now()))
        pid=conn.execute("SELECT id FROM sister_finance_parties WHERE code=?",(party_code,)).fetchone()[0]
        conn.execute("""INSERT INTO sister_finance_movements
          (kind,party_id,account_id,movement_date,amount_toman,reference,note,created_at)
          VALUES ('payment',?,?,?,?,?,?,?)""",
          (pid,bid,day,val,"supplier-purchase-payment:"+str(payment_id),
           "پرداخت خرید کالا به "+balance["name"]+"؛ "+note,now()))
        conn.execute("COMMIT")
        return payment_id
    except Exception:
        conn.execute("ROLLBACK");raise

def purchase_history(conn,limit=100):
    return [dict(r) for r in conn.execute("""SELECT p.*,s.name AS supplier_name
      FROM sister_purchase_orders p JOIN sister_purchase_suppliers s ON s.id=p.supplier_id
      ORDER BY p.id DESC LIMIT ?""",(limit,))]

def supplier_history(conn,supplier_id):
    sid=int(supplier_id)
    supplier_totals(conn,sid)
    purchases=[dict(r) for r in conn.execute("""SELECT * FROM sister_purchase_orders
                WHERE supplier_id=? ORDER BY id DESC""",(sid,))]
    payments=[dict(r) for r in conn.execute("""SELECT * FROM sister_purchase_payments
                WHERE supplier_id=? ORDER BY id DESC""",(sid,))]
    return purchases,payments

def purchase_detail(conn,purchase_id):
    p=conn.execute("""SELECT p.*,s.name supplier_name FROM sister_purchase_orders p
             JOIN sister_purchase_suppliers s ON s.id=p.supplier_id WHERE p.id=?""",(int(purchase_id),)).fetchone()
    if p is None:raise ImportErrorDetail("سند خرید پیدا نشد.")
    lines=[dict(r) for r in conn.execute("""SELECT l.*,m.category,m.title,m.color,m.size,m.subtype
             FROM sister_purchase_lines l JOIN master_products m ON m.id=l.master_id
             WHERE l.purchase_id=? ORDER BY l.id""",(purchase_id,))]
    return dict(p),lines
