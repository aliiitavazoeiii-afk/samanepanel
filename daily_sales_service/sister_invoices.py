"""Independent, auditable shoe-holder customer invoices and Mehr settlement ledger.

Amounts are integer toman. An invoice is not a second marketplace sale.
Drafts have no stock or supplier impact; dispatch posts exactly once.
"""
import uuid
from .engine import ImportErrorDetail, money
from .effective_costs import today, valid_date
from .master_engine import now

SUPPLIER = "مه هر"
SIZES = ("کوچک", "متوسط", "بزرگ")
SCHEMA = """
CREATE TABLE IF NOT EXISTS sister_invoice_customers (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, phone TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sister_invoices (
 id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES sister_invoice_customers(id),
 invoice_date TEXT NOT NULL, origin TEXT NOT NULL CHECK(origin IN ('home','factory')),
 status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','dispatched')),
 notes TEXT NOT NULL DEFAULT '', posted_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sister_invoice_lines (
 invoice_id INTEGER NOT NULL REFERENCES sister_invoices(id),
 size TEXT NOT NULL CHECK(size IN ('کوچک','متوسط','بزرگ')),
 master_id INTEGER REFERENCES master_products(id),
 qty INTEGER NOT NULL CHECK(qty>=0),
 purchase_unit INTEGER NOT NULL CHECK(purchase_unit>=0),
 sale_unit INTEGER NOT NULL CHECK(sale_unit>=0),
 PRIMARY KEY(invoice_id,size)
);
CREATE TABLE IF NOT EXISTS sister_invoice_receipts (
 id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL REFERENCES sister_invoices(id),
 amount INTEGER NOT NULL CHECK(amount>0),
 destination TEXT NOT NULL CHECK(destination IN ('mine','mehr','check_mehr')),
 account_id INTEGER REFERENCES sister_finance_accounts(id),
 paid_on TEXT NOT NULL, check_date TEXT, notes TEXT NOT NULL DEFAULT '',
 request_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sister_mehr_ledger (
 id INTEGER PRIMARY KEY, occurred_on TEXT NOT NULL,
 debt_delta INTEGER NOT NULL DEFAULT 0, credit_delta INTEGER NOT NULL DEFAULT 0,
 kind TEXT NOT NULL, reference TEXT NOT NULL UNIQUE,
 notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sister_mehr_purchases (
 id INTEGER PRIMARY KEY, master_id INTEGER NOT NULL REFERENCES master_products(id),
 qty INTEGER NOT NULL CHECK(qty>0), unit_cost INTEGER NOT NULL CHECK(unit_cost>=0),
 purchase_date TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
 request_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sister_invoice_customer ON sister_invoices(customer_id,invoice_date);
CREATE INDEX IF NOT EXISTS idx_sister_receipt_invoice ON sister_invoice_receipts(invoice_id);
CREATE TABLE IF NOT EXISTS sister_invoice_submission_keys (
 request_key TEXT PRIMARY KEY, invoice_id INTEGER NOT NULL UNIQUE REFERENCES sister_invoices(id),
 created_at TEXT NOT NULL
);
"""
def ensure_schema(conn):
    conn.executescript(SCHEMA)

def _date(value, allow_future=False):
    value=valid_date(value)
    if not allow_future and value>today():raise ImportErrorDetail("تاریخ ثبت نمی‌تواند در آینده باشد.")
    return value

def _text(value,max_length=350):
    value=str(value or "").strip()
    if len(value)>max_length:raise ImportErrorDetail("طول توضیحات بیش از حد مجاز است.")
    return value

def _ledger(conn,day,debt,credit,kind,reference,notes=""):
    conn.execute("""INSERT INTO sister_mehr_ledger
      (occurred_on,debt_delta,credit_delta,kind,reference,notes,created_at)
      VALUES (?,?,?,?,?,?,?)""",(day,int(debt),int(credit),kind,reference,_text(notes),now()))

def _bank(conn,account_id,kind,amount,day,reference,party_code,party_title):
    if account_id in (None,""):raise ImportErrorDetail("برای پول واریزشده به حساب خودت، حساب مقصد را انتخاب کن.")
    aid=int(account_id)
    if not conn.execute("SELECT 1 FROM sister_finance_accounts WHERE id=? AND active=1",(aid,)).fetchone():
        raise ImportErrorDetail("حساب بانکی انتخاب‌شده نامعتبر است.")
    conn.execute("""INSERT OR IGNORE INTO sister_finance_parties
      (code,title,is_platform,created_at) VALUES (?,?,0,?)""",(party_code,party_title,now()))
    pid=conn.execute("SELECT id FROM sister_finance_parties WHERE code=?",(party_code,)).fetchone()[0]
    conn.execute("""INSERT INTO sister_finance_movements
      (kind,party_id,account_id,movement_date,amount_toman,reference,note,created_at)
      VALUES (?,?,?,?,?,?,?,?)""",(kind,pid,aid,day,amount,reference,"ثبت خودکار فاکتور / حساب مه هر",now()))

def create_invoice(conn,customer_name,phone,invoice_date,origin,lines,notes="",manage_tx=True):
    name=_text(customer_name,120)
    if len(name)<2:raise ImportErrorDetail("نام مشتری را کامل وارد کن.")
    phone=_text(phone,40)
    day=_date(invoice_date)
    if origin not in ("home","factory"):raise ImportErrorDetail("مبدأ ارسال نامعتبر است.")
    normalized={}
    for size in SIZES:
        item=lines.get(size,{})
        qty=money(item.get("qty",0))
        if qty>100000:raise ImportErrorDetail("تعداد یک سایز بیش از حد مجاز است.")
        purchase=money(item.get("purchase",0))
        sale=money(item.get("sale",0))
        master=item.get("master_id")
        if qty and (not purchase or not sale):raise ImportErrorDetail("قیمت خرید و فروش سایز "+size+" را مشخص کن.")
        if qty and origin=="home":
            if master in (None,""):raise ImportErrorDetail("برای ارسال از خانه، کالای واقعی سایز "+size+" را انتخاب کن.")
            sku=conn.execute("SELECT category,size,active FROM master_products WHERE id=?",(int(master),)).fetchone()
            if not sku or sku["category"]!="قالب" or sku["size"]!=size or not sku["active"]:
                raise ImportErrorDetail("شناسه کالای فیزیکی با سایز "+size+" سازگار نیست.")
        normalized[size]=(int(master) if qty and origin=="home" else None,qty,purchase,sale)
    if not any(x[1] for x in normalized.values()):raise ImportErrorDetail("حداقل یک سایز با تعداد مثبت وارد کن.")
    if manage_tx:conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("""INSERT INTO sister_invoice_customers(name,phone,created_at)
          VALUES (?,?,?) ON CONFLICT(name) DO UPDATE SET
          phone=CASE WHEN excluded.phone!='' THEN excluded.phone ELSE sister_invoice_customers.phone END""",(name,phone,now()))
        cid=conn.execute("SELECT id FROM sister_invoice_customers WHERE name=?",(name,)).fetchone()[0]
        cur=conn.execute("""INSERT INTO sister_invoices
          (customer_id,invoice_date,origin,notes,created_at)
          VALUES (?,?,?,?,?)""",(cid,day,origin,_text(notes),now()))
        iid=cur.lastrowid
        for size,(mid,qty,purchase,sale) in normalized.items():
            if qty:
                conn.execute("""INSERT INTO sister_invoice_lines
                 (invoice_id,size,master_id,qty,purchase_unit,sale_unit)
                 VALUES (?,?,?,?,?,?)""",(iid,size,mid,qty,purchase,sale))
        if manage_tx:conn.execute("COMMIT")
        return iid
    except Exception:
        if manage_tx:conn.execute("ROLLBACK")
        raise

def dispatch_invoice(conn,invoice_id,manage_tx=True):
    if manage_tx:conn.execute("BEGIN IMMEDIATE")
    try:
        inv=conn.execute("SELECT * FROM sister_invoices WHERE id=?",(int(invoice_id),)).fetchone()
        if inv is None:raise ImportErrorDetail("فاکتور پیدا نشد.")
        if inv["status"]!="draft":raise ImportErrorDetail("این فاکتور قبلاً ارسال شده؛ موجودی و بدهی دوباره تغییر نمی‌کند.")
        lines=list(conn.execute("SELECT * FROM sister_invoice_lines WHERE invoice_id=?",(invoice_id,)))
        if not lines:raise ImportErrorDetail("فاکتور بدون کالا قابل ارسال نیست.")
        if inv["origin"]=="home":
            for r in lines:
                sku=conn.execute("SELECT seller_stock FROM master_products WHERE id=? AND category='قالب' AND size=? AND active=1",
                                 (r["master_id"],r["size"])).fetchone()
                if sku is None:raise ImportErrorDetail("محصول واقعی حذف یا غیرفعال شده است.")
                after=int(sku[0])-int(r["qty"])
                conn.execute("UPDATE master_products SET seller_stock=?,updated_at=? WHERE id=?",(after,now(),r["master_id"]))
                conn.execute("""INSERT INTO master_stock_events
                  (occurred_at,master_id,source,delta,balance_after,reference)
                  VALUES (?,?,?,?,?,?)""",(now(),r["master_id"],"home",-int(r["qty"]),after,"sister-invoice:"+str(invoice_id)))
        else:
            # Direct factory delivery is a NEW purchase; never touches home stock.
            cost=sum(int(r["qty"])*int(r["purchase_unit"]) for r in lines)
            _ledger(conn,today(),cost,0,"factory_invoice","factory-invoice:"+str(invoice_id))
        conn.execute("UPDATE sister_invoices SET status='dispatched',posted_at=? WHERE id=?",(now(),invoice_id))
        if manage_tx:conn.execute("COMMIT")
    except Exception:
        if manage_tx:conn.execute("ROLLBACK")
        raise

def receive_purchase(conn,master_id,quantity,unit_cost,purchase_date,request_key,notes=""):
    day=_date(purchase_date);qty=money(quantity);cost=money(unit_cost)
    if qty<1 or qty>100000:raise ImportErrorDetail("تعداد خرید باید مثبت باشد.")
    if cost<=0:raise ImportErrorDetail("قیمت خرید هر قالب از مه هر باید مثبت باشد.")
    key=_text(request_key,100)
    if not key:raise ImportErrorDetail("شناسه ثبت خرید لازم است.")
    conn.execute("BEGIN IMMEDIATE")
    try:
        sku=conn.execute("SELECT * FROM master_products WHERE id=? AND category='قالب' AND active=1",(int(master_id),)).fetchone()
        if not sku or sku["size"] not in SIZES:raise ImportErrorDetail("قالب انتخاب‌شده معتبر نیست.")
        if conn.execute("SELECT id FROM sister_mehr_purchases WHERE request_key=?",(key,)).fetchone():
            raise ImportErrorDetail("این خرید قبلاً ثبت شده است.")
        cur=conn.execute("""INSERT INTO sister_mehr_purchases
           (master_id,qty,unit_cost,purchase_date,notes,request_key,created_at)
           VALUES (?,?,?,?,?,?,?)""",(master_id,qty,cost,day,_text(notes),key,now()))
        purchase_id=cur.lastrowid
        after=int(sku["seller_stock"])+qty
        conn.execute("UPDATE master_products SET seller_stock=?,updated_at=? WHERE id=?",(after,now(),master_id))
        conn.execute("""INSERT INTO master_stock_events
          (occurred_at,master_id,source,delta,balance_after,reference)
          VALUES (?,?,?,?,?,?)""",(now(),master_id,"home",qty,after,"mehr-purchase:"+str(purchase_id)))
        _ledger(conn,day,qty*cost,0,"purchase","mehr-purchase:"+str(purchase_id),notes)
        conn.execute("COMMIT");return purchase_id
    except Exception:
        conn.execute("ROLLBACK");raise

def record_receipt(conn,invoice_id,amount,destination,paid_on,request_key,account_id=None,check_date="",notes="",manage_tx=True):
    day=_date(paid_on);val=money(amount)
    if val<=0:raise ImportErrorDetail("مبلغ پرداخت مثبت باشد.")
    if destination not in ("mine","mehr","check_mehr"):raise ImportErrorDetail("نوع پرداخت نامعتبر است.")
    cheque=_date(check_date,allow_future=True) if destination=="check_mehr" and check_date else None
    if destination=="check_mehr" and cheque is None:raise ImportErrorDetail("تاریخ چک را وارد کن.")
    key=_text(request_key,100)
    if not key:raise ImportErrorDetail("شناسه درخواست لازم است.")
    if manage_tx:conn.execute("BEGIN IMMEDIATE")
    try:
        invoice=conn.execute("""SELECT i.*,c.name FROM sister_invoices i JOIN sister_invoice_customers c
            ON c.id=i.customer_id WHERE i.id=?""",(int(invoice_id),)).fetchone()
        if not invoice:raise ImportErrorDetail("فاکتور پیدا نشد.")
        total=conn.execute("""SELECT SUM(qty*sale_unit) FROM sister_invoice_lines WHERE invoice_id=?""",(invoice_id,)).fetchone()[0] or 0
        paid=conn.execute("SELECT COALESCE(SUM(amount),0) FROM sister_invoice_receipts WHERE invoice_id=?",(invoice_id,)).fetchone()[0]
        if val+paid>total:raise ImportErrorDetail("پرداخت از مانده فاکتور بیشتر است.")
        if conn.execute("SELECT 1 FROM sister_invoice_receipts WHERE request_key=?",(key,)).fetchone():
            raise ImportErrorDetail("این پرداخت قبلاً ثبت شده است.")
        cur=conn.execute("""INSERT INTO sister_invoice_receipts
          (invoice_id,amount,destination,account_id,paid_on,check_date,notes,request_key,created_at)
          VALUES (?,?,?,?,?,?,?,?,?)""",(invoice_id,val,destination,int(account_id) if destination=="mine" and account_id else None,
          day,cheque,_text(notes),key,now()))
        rid=cur.lastrowid
        if destination=="mine":
            # An unidentified receiving bank is NOT silently assigned to any account.
            # Finance shows it separately as unallocated cash; receipt is still auditable.
            if account_id not in (None,""):
                _bank(conn,account_id,"receipt",val,day,"invoice-receipt:"+str(rid),
                      "sister-customer-"+str(invoice["customer_id"]),"مشتری فاکتور: "+invoice["name"])
        else:
            _ledger(conn,day,0,val,"customer_to_mehr","invoice-receipt:"+str(rid),
                    ("چک به مه هر، تاریخ "+cheque+"؛ " if cheque else "واریز مشتری به مه هر؛ ")+_text(notes))
        if manage_tx:conn.execute("COMMIT")
        return rid
    except Exception:
        if manage_tx:conn.execute("ROLLBACK")
        raise

def settlement(conn,kind,amount,day,request_key,account_id=None,notes=""):
    if kind not in ("offset","paid_to_mehr","received_from_mehr"):raise ImportErrorDetail("نوع تسویه نامعتبر است.")
    day=_date(day);val=money(amount)
    if val<=0:raise ImportErrorDetail("مبلغ تسویه باید مثبت باشد.")
    key=_text(request_key,100)
    if not key:raise ImportErrorDetail("شناسه تسویه لازم است.")
    conn.execute("BEGIN IMMEDIATE")
    try:
        if conn.execute("SELECT 1 FROM sister_mehr_ledger WHERE reference=?",(key,)).fetchone():
            raise ImportErrorDetail("این تسویه قبلاً ثبت شده است.")
        balance=mehr_balance(conn)
        if kind=="offset":
            if val>min(balance["debt"],balance["credit"]):raise ImportErrorDetail("مبلغ تهاتر از طلب یا بدهی بیشتر است.")
            debt,credit=-val,-val
        elif kind=="paid_to_mehr":
            if val>balance["debt"]:raise ImportErrorDetail("پرداخت از بدهی ثبت‌شده بیشتر است.")
            debt,credit=-val,0
            _bank(conn,account_id,"payment",val,day,key+":bank","mehr-supplier",SUPPLIER)
        else:
            if val>balance["credit"]:raise ImportErrorDetail("دریافت از طلب ثبت‌شده بیشتر است.")
            debt,credit=0,-val
            _bank(conn,account_id,"receipt",val,day,key+":bank","mehr-supplier",SUPPLIER)
        _ledger(conn,day,debt,credit,kind,key,notes)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK");raise

def mehr_balance(conn):
    row=conn.execute("SELECT COALESCE(SUM(debt_delta),0),COALESCE(SUM(credit_delta),0) FROM sister_mehr_ledger").fetchone()
    debt,credit=int(row[0]),int(row[1])
    return {"debt":debt,"credit":credit,"net":credit-debt}


def submit_invoice(conn,customer_name,phone,invoice_date,origin,lines,notes,
                   request_key,initial_amount="0",destination="mine",
                   paid_on="",check_date="",receipt_notes=""):
    """One atomic, idempotent creation + confirmation + optional initial payment.

    Existing invoice/dispatch/receipt operations remain separately supported
    for historical drafts and additional payments.
    """
    key=_text(request_key,100)
    if not key:raise ImportErrorDetail("شناسه ثبت فاکتور لازم است.")
    if origin not in ("home","factory"):raise ImportErrorDetail("مبدأ ارسال نامعتبر است.")
    amount=money(initial_amount or 0)
    if amount<0:raise ImportErrorDetail("مبلغ دریافتی نمی‌تواند منفی باشد.")
    if amount and destination not in ("mine","mehr","check_mehr"):
        raise ImportErrorDetail("دریافت‌کننده وجه نامعتبر است.")
    conn.execute("BEGIN IMMEDIATE")
    try:
        previous=conn.execute("""SELECT invoice_id FROM sister_invoice_submission_keys
            WHERE request_key=?""",(key,)).fetchone()
        if previous:
            conn.execute("COMMIT")
            return int(previous[0])
        normalized={}
        for size in SIZES:
            item=dict(lines.get(size,{}) or {})
            qty=money(item.get("qty") or 0)
            if qty and origin=="home" and not item.get("master_id"):
                rows=list(conn.execute("""SELECT id FROM master_products
                    WHERE category='قالب' AND size=? AND active=1""",(size,)))
                if len(rows)!=1:
                    reason="هیچ کالای فعالی" if not rows else "چند کالای واقعی"
                    raise ImportErrorDetail(
                        f"برای سایز {size} {reason} تعریف شده است؛ انتخاب خودکار امن نیست. "
                        "ابتدا محصولات اصلی قالب را بررسی کن.")
                item["master_id"]=int(rows[0][0])
            normalized[size]=item
        invoice_id=create_invoice(conn,customer_name,phone,invoice_date,origin,
                                  normalized,notes,manage_tx=False)
        dispatch_invoice(conn,invoice_id,manage_tx=False)
        if amount:
            record_receipt(conn,invoice_id,amount,destination,paid_on or invoice_date,
                           "initial:"+key,check_date=check_date,
                           notes=receipt_notes,manage_tx=False)
        conn.execute("""INSERT INTO sister_invoice_submission_keys
           (request_key,invoice_id,created_at) VALUES (?,?,?)""",(key,invoice_id,now()))
        conn.execute("COMMIT")
        return invoice_id
    except Exception:
        if conn.in_transaction:conn.execute("ROLLBACK")
        raise


def open_customer_invoices(conn,limit=100):
    """Confirmed only: unpaid invoices are real receivables, not draft advances."""
    return [dict(r) for r in conn.execute("""
        SELECT i.id,i.invoice_date,c.name,c.phone,
          COALESCE((SELECT SUM(l.qty*l.sale_unit)
                    FROM sister_invoice_lines l WHERE l.invoice_id=i.id),0) AS gross,
          COALESCE((SELECT SUM(r.amount)
                    FROM sister_invoice_receipts r WHERE r.invoice_id=i.id),0) AS paid
        FROM sister_invoices i
        JOIN sister_invoice_customers c ON c.id=i.customer_id
        WHERE i.status='dispatched'
          AND COALESCE((SELECT SUM(l.qty*l.sale_unit)
                         FROM sister_invoice_lines l WHERE l.invoice_id=i.id),0)
              > COALESCE((SELECT SUM(r.amount)
                           FROM sister_invoice_receipts r WHERE r.invoice_id=i.id),0)
        ORDER BY i.invoice_date DESC,i.id DESC LIMIT ?
    """,(int(limit),))]


def invoices(conn,query=""):
    q="%"+str(query or "").strip()+"%"
    return [dict(row) for row in conn.execute("""SELECT i.*,c.name,c.phone,
      COALESCE((SELECT SUM(l.qty*l.sale_unit) FROM sister_invoice_lines l WHERE l.invoice_id=i.id),0) gross,
      COALESCE((SELECT SUM(l.qty*l.purchase_unit) FROM sister_invoice_lines l WHERE l.invoice_id=i.id),0) cogs,
      COALESCE((SELECT SUM(r.amount) FROM sister_invoice_receipts r WHERE r.invoice_id=i.id),0) paid
      FROM sister_invoices i JOIN sister_invoice_customers c ON c.id=i.customer_id
      WHERE c.name LIKE ? ORDER BY i.id DESC LIMIT 200""",(q,))]

def invoice_detail(conn,invoice_id):
    inv=conn.execute("""SELECT i.*,c.name,c.phone FROM sister_invoices i
        JOIN sister_invoice_customers c ON c.id=i.customer_id WHERE i.id=?""",(invoice_id,)).fetchone()
    if not inv:raise ImportErrorDetail("فاکتور پیدا نشد.")
    return dict(inv),[dict(r) for r in conn.execute("SELECT * FROM sister_invoice_lines WHERE invoice_id=? ORDER BY size",(invoice_id,))],\
           [dict(r) for r in conn.execute("SELECT * FROM sister_invoice_receipts WHERE invoice_id=? ORDER BY id",(invoice_id,))]
