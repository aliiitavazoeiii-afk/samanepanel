"""Independent, auditable shoe-holder customer invoices and Mehr settlement ledger.

Amounts are integer toman. An invoice is not a second marketplace sale.
Drafts have no stock or supplier impact; dispatch posts exactly once.
"""
import uuid
import json
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
CREATE TABLE IF NOT EXISTS sister_invoice_audit (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 invoice_id INTEGER NOT NULL,
 action TEXT NOT NULL CHECK(action IN ('edit','cancel','receipt_edit')),
 old_json TEXT NOT NULL,
 new_json TEXT NOT NULL,
 request_key TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sister_invoice_audit_invoice ON sister_invoice_audit(invoice_id,id);
CREATE INDEX IF NOT EXISTS idx_sister_receipt_invoice ON sister_invoice_receipts(invoice_id);
CREATE TABLE IF NOT EXISTS sister_invoice_submission_keys (
 request_key TEXT PRIMARY KEY, invoice_id INTEGER NOT NULL UNIQUE REFERENCES sister_invoices(id),
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sister_mehr_settlement_links (
 reference TEXT PRIMARY KEY REFERENCES sister_mehr_ledger(reference),
 target_type TEXT NOT NULL CHECK(target_type IN ('invoice','purchase','legacy_purchase')),
 target_id INTEGER NOT NULL CHECK(target_id>0)
);
CREATE INDEX IF NOT EXISTS idx_sister_mehr_settlement_target
 ON sister_mehr_settlement_links(target_type,target_id);
"""
def ensure_schema(conn):
    conn.executescript(SCHEMA)
    fields={r["name"] for r in conn.execute("PRAGMA table_info(sister_invoices)")}
    if "is_void" not in fields:
        conn.execute("ALTER TABLE sister_invoices ADD COLUMN is_void INTEGER NOT NULL DEFAULT 0")
    if "version" not in fields:
        conn.execute("ALTER TABLE sister_invoices ADD COLUMN version INTEGER NOT NULL DEFAULT 0")
    if "voided_at" not in fields:
        conn.execute("ALTER TABLE sister_invoices ADD COLUMN voided_at TEXT")


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
        if inv["is_void"]:raise ImportErrorDetail("این فاکتور ابطال شده است.")
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
        if invoice["is_void"]:raise ImportErrorDetail("فاکتور ابطال‌شده دریافت جدید نمی‌پذیرد.")
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

def mehr_open_items(conn):
    """Read-only invoice and supplier-purchase liabilities, no duplicate postings.

    Per-item outstanding is net of customer payments to Mehr and explicitly
    assigned Mehr cash settlements. Legacy unassigned settlements stay in the
    overall net balance only, so users cannot mistake them for a specific item.
    """
    items=[]
    for r in conn.execute("""SELECT i.id,i.invoice_date,c.name,
      COALESCE(SUM(l.qty*l.purchase_unit),0) cost
      FROM sister_invoices i JOIN sister_invoice_customers c ON c.id=i.customer_id
      JOIN sister_invoice_lines l ON l.invoice_id=i.id
      WHERE i.origin='factory' AND i.status='dispatched' AND i.is_void=0
      GROUP BY i.id ORDER BY i.id DESC"""):
        gross=int(r["cost"])
        customer=int(conn.execute("""SELECT COALESCE(SUM(amount),0)
            FROM sister_invoice_receipts WHERE invoice_id=?
              AND destination IN ('mehr','check_mehr')""",(r["id"],)).fetchone()[0])
        linked=int(conn.execute("""SELECT COALESCE(SUM(-l.debt_delta),0)
            FROM sister_mehr_settlement_links a JOIN sister_mehr_ledger l ON l.reference=a.reference
            WHERE a.target_type='invoice' AND a.target_id=? AND l.kind='paid_to_mehr'""",(r["id"],)).fetchone()[0])
        remaining=max(0,gross-customer-linked)
        items.append({"target":"invoice:"+str(r["id"]),"kind":"invoice","id":int(r["id"]),
                      "date":r["invoice_date"],"label":"فاکتور #"+str(r["id"])+" / "+r["name"],
                      "gross":gross,"credit":customer,"paid":linked,"remaining":remaining})
    for r in conn.execute("""SELECT p.id,p.purchase_date,p.supplier_invoice,p.total_toman
        FROM sister_purchase_orders p
        JOIN sister_purchase_suppliers s ON s.id=p.supplier_id
        WHERE s.name='مه هر' ORDER BY p.id DESC"""):
        # A purchase is eligible only if the Mehr ledger actually has its posting.
        has_ledger=conn.execute("""SELECT 1 FROM sister_mehr_ledger
           WHERE kind='purchase_general' AND reference=?""",
           ("supplier-purchase:"+str(r["id"]),)).fetchone()
        if not has_ledger:continue
        paid=int(conn.execute("""SELECT COALESCE(SUM(-l.debt_delta),0)
            FROM sister_mehr_settlement_links a JOIN sister_mehr_ledger l ON l.reference=a.reference
            WHERE a.target_type='purchase' AND a.target_id=? AND l.kind='paid_to_mehr'""",(r["id"],)).fetchone()[0])
        gross=int(r["total_toman"])
        items.append({"target":"purchase:"+str(r["id"]),"kind":"purchase","id":int(r["id"]),
                      "date":r["purchase_date"],"label":"خرید قالب #"+str(r["id"])+
                      (" / "+r["supplier_invoice"] if r["supplier_invoice"] else ""),
                      "gross":gross,"credit":0,"paid":paid,"remaining":max(0,gross-paid)})
    for r in conn.execute("""SELECT p.id,p.purchase_date,p.qty,p.unit_cost,m.size
        FROM sister_mehr_purchases p
        JOIN master_products m ON m.id=p.master_id
        ORDER BY p.id DESC"""):
        if not conn.execute("""SELECT 1 FROM sister_mehr_ledger
           WHERE kind='purchase' AND reference=?""",("mehr-purchase:"+str(r["id"]),)).fetchone():
            continue
        gross=int(r["qty"])*int(r["unit_cost"])
        paid=int(conn.execute("""SELECT COALESCE(SUM(-l.debt_delta),0)
            FROM sister_mehr_settlement_links a JOIN sister_mehr_ledger l ON l.reference=a.reference
            WHERE a.target_type='legacy_purchase' AND a.target_id=?
              AND l.kind='paid_to_mehr'""",(r["id"],)).fetchone()[0])
        items.append({"target":"legacy_purchase:"+str(r["id"]),"kind":"legacy_purchase",
                      "id":int(r["id"]),"date":r["purchase_date"],
                      "label":"خرید قدیمی قالب #"+str(r["id"])+" / "+r["size"],
                      "gross":gross,"credit":0,"paid":paid,"remaining":max(0,gross-paid)})
    return items


def settlement(conn,kind,amount,day,request_key,account_id=None,notes="",target=""):
    """One atomic, idempotent Mehr posting. Optional link reconciles a document.

    Never posts an invoice customer receipt a second time. Offset changes both
    ledger sides equally (net stays unchanged). Bank is optional and never
    invented; unallocated legacy postings are still supported.
    """
    if kind not in ("offset","paid_to_mehr","received_from_mehr"):
        raise ImportErrorDetail("نوع تسویه نامعتبر است.")
    day=_date(day);val=money(amount)
    if val<=0:raise ImportErrorDetail("مبلغ تسویه باید مثبت باشد.")
    key=_text(request_key,100)
    if not key:raise ImportErrorDetail("شناسه تسویه لازم است.")
    target=_text(target,100)
    if target and kind!="paid_to_mehr":
        raise ImportErrorDetail("انتخاب فاکتور فقط برای پرداخت به مهر مجاز است.")
    conn.execute("BEGIN IMMEDIATE")
    try:
        if conn.execute("SELECT 1 FROM sister_mehr_ledger WHERE reference=?",(key,)).fetchone():
            raise ImportErrorDetail("این تسویه قبلاً ثبت شده است.")
        balance=mehr_balance(conn)
        net=int(balance["net"])
        if kind=="offset":
            if val>min(balance["debt"],balance["credit"]):
                raise ImportErrorDetail("مبلغ تهاتر از وجوه مشتری نزد مهر یا بدهی خرید بیشتر است.")
            debt,credit=-val,-val
        elif kind=="paid_to_mehr":
            if val>max(0,-net):
                raise ImportErrorDetail("مبلغ پرداخت از بدهی خالص ثبت‌شده به مهر بیشتر است.")
            if target:
                item=next((r for r in mehr_open_items(conn) if r["target"]==target),None)
                if item is None or item["remaining"]<=0:
                    raise ImportErrorDetail("فاکتور یا خرید انتخابی بدهی باز ندارد.")
                if val>item["remaining"]:
                    raise ImportErrorDetail("مبلغ پرداخت از مانده فاکتور یا خرید انتخابی بیشتر است.")
            debt,credit=-val,0
            if account_id not in (None,""):
                _bank(conn,account_id,"payment",val,day,key+":bank","mehr-supplier",SUPPLIER)
        else:
            if val>max(0,net):
                raise ImportErrorDetail("مبلغ دریافتی از طلب خالص ثبت‌شده نزد مهر بیشتر است.")
            debt,credit=0,-val
            if account_id not in (None,""):
                _bank(conn,account_id,"receipt",val,day,key+":bank","mehr-supplier",SUPPLIER)
        note=_text(notes)
        if kind!="offset" and account_id in (None,""):
            marker="حساب بانکی نامشخص؛ اثر بانکی ثبت نشد"
            note=(note+"؛ " if note else "")+marker
        _ledger(conn,day,debt,credit,kind,key,note)
        if target:
            target_kind,target_id=target.split(":")
            conn.execute("""INSERT INTO sister_mehr_settlement_links
                (reference,target_type,target_id) VALUES (?,?,?)""",
                (key,target_kind,int(target_id)))
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:conn.execute("ROLLBACK")
        raise

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


def open_customer_invoices(conn,limit=None):
    """Confirmed only: unpaid invoices are real receivables, not draft advances."""
    sql="""
        SELECT i.id,i.invoice_date,c.name,c.phone,
          COALESCE((SELECT SUM(l.qty*l.sale_unit)
                    FROM sister_invoice_lines l WHERE l.invoice_id=i.id),0) AS gross,
          COALESCE((SELECT SUM(r.amount)
                    FROM sister_invoice_receipts r WHERE r.invoice_id=i.id),0) AS paid
        FROM sister_invoices i
        JOIN sister_invoice_customers c ON c.id=i.customer_id
        WHERE i.status='dispatched' AND i.is_void=0
          AND COALESCE((SELECT SUM(l.qty*l.sale_unit)
                         FROM sister_invoice_lines l WHERE l.invoice_id=i.id),0)
              > COALESCE((SELECT SUM(r.amount)
                           FROM sister_invoice_receipts r WHERE r.invoice_id=i.id),0)
        ORDER BY i.invoice_date DESC,i.id DESC
    """
    if limit is not None:
        return [dict(r) for r in conn.execute(sql+" LIMIT ?",(int(limit),))]
    return [dict(r) for r in conn.execute(sql)]



def _invoice_snapshot(conn,invoice_id):
    invoice=conn.execute("""SELECT i.*,c.name,c.phone FROM sister_invoices i
        JOIN sister_invoice_customers c ON c.id=i.customer_id WHERE i.id=?""",(invoice_id,)).fetchone()
    if not invoice:raise ImportErrorDetail("فاکتور پیدا نشد.")
    lines=[dict(r) for r in conn.execute("SELECT * FROM sister_invoice_lines WHERE invoice_id=? ORDER BY size",(invoice_id,))]
    receipts=[dict(r) for r in conn.execute("SELECT * FROM sister_invoice_receipts WHERE invoice_id=? ORDER BY id",(invoice_id,))]
    return {"invoice":dict(invoice),"lines":lines,"receipts":receipts}


def _audit_invoice(conn,invoice_id,action,before,after,key):
    conn.execute("""INSERT INTO sister_invoice_audit
        (invoice_id,action,old_json,new_json,request_key,created_at)
        VALUES (?,?,?,?,?,?)""",
        (invoice_id,action,json.dumps(before,ensure_ascii=False,sort_keys=True),
         json.dumps(after,ensure_ascii=False,sort_keys=True),key,now()))


def _adjust_invoice_stock(conn,invoice_id,previous,revised,request_key):
    """Apply signed differences; leave all prior stock events intact."""
    prev={}
    curr={}
    for line in previous:
        mid=int(line["master_id"])
        prev[mid]=prev.get(mid,0)+int(line["qty"])
    for line in revised:
        mid=int(line["master_id"])
        curr[mid]=curr.get(mid,0)+int(line["qty"])
    for mid in sorted(set(prev)|set(curr)):
        correction=prev.get(mid,0)-curr.get(mid,0)
        if correction==0:continue
        sku=conn.execute("SELECT seller_stock FROM master_products WHERE id=?",(mid,)).fetchone()
        if sku is None:raise ImportErrorDetail("کالای قبلی دیگر در انبار پیدا نمی‌شود.")
        new_stock=int(sku["seller_stock"])+correction
        conn.execute("UPDATE master_products SET seller_stock=?,updated_at=? WHERE id=?",
                     (new_stock,now(),mid))
        conn.execute("""INSERT INTO master_stock_events
            (occurred_at,master_id,source,delta,balance_after,reference)
            VALUES (?,?,?,?,?,?)""",
            (now(),mid,"home",correction,new_stock,
             "sister-invoice-correction:"+str(invoice_id)+":"+request_key))


def edit_invoice(conn,invoice_id,customer_name,phone,invoice_date,lines,notes,
                 expected_version,request_key):
    """Correct an existing invoice atomically; never create a second sale."""
    try:iid=int(invoice_id);version=int(expected_version)
    except (TypeError,ValueError):raise ImportErrorDetail("شماره یا نسخه فاکتور نامعتبر است.")
    key=_text(request_key,100)
    if not key:raise ImportErrorDetail("شناسه ویرایش لازم است.")
    name=_text(customer_name,120)
    if len(name)<2:raise ImportErrorDetail("نام مشتری را کامل وارد کن.")
    day=_date(invoice_date);phone=_text(phone,40);memo=_text(notes)
    conn.execute("BEGIN IMMEDIATE")
    try:
        before=_invoice_snapshot(conn,iid)
        inv=before["invoice"]
        if inv["is_void"]:raise ImportErrorDetail("فاکتور ابطال‌شده قابل ویرایش نیست.")
        if inv["version"]!=version:raise ImportErrorDetail("فاکتور بعد از باز شدن فرم تغییر کرده؛ صفحه را تازه‌سازی کن.")
        if conn.execute("SELECT 1 FROM sister_invoice_audit WHERE request_key=?",(key,)).fetchone():
            raise ImportErrorDetail("این ویرایش قبلاً ثبت شده است.")
        next_lines=[]
        for size in SIZES:
            row=lines.get(size,{}) or {}
            qty=money(row.get("qty") or 0)
            purchase=money(row.get("purchase") or 0)
            sale=money(row.get("sale") or 0)
            if qty>100000:raise ImportErrorDetail("تعداد سایز "+size+" بیش از حد مجاز است.")
            if not qty:continue
            if not sale or not purchase:raise ImportErrorDetail("قیمت خرید و فروش سایز "+size+" را وارد کن.")
            mid=None
            if inv["origin"]=="home":
                mid_raw=row.get("master_id")
                if mid_raw in (None,""):raise ImportErrorDetail("کالای واقعی سایز "+size+" را انتخاب کن.")
                try:mid=int(mid_raw)
                except (TypeError,ValueError):raise ImportErrorDetail("کالای انتخابی نامعتبر است.")
                sku=conn.execute("SELECT category,size,active FROM master_products WHERE id=?",(mid,)).fetchone()
                if sku is None or sku["category"]!="قالب" or sku["size"]!=size or not sku["active"]:
                    raise ImportErrorDetail("قالب انتخابی با سایز "+size+" سازگار نیست.")
            next_lines.append({"invoice_id":iid,"size":size,"master_id":mid,
                               "qty":qty,"purchase_unit":purchase,"sale_unit":sale})
        if not next_lines:raise ImportErrorDetail("حداقل یک ردیف دارای تعداد مثبت لازم است.")
        old_sales=sum(int(x["qty"])*int(x["sale_unit"]) for x in before["lines"])
        new_sales=sum(x["qty"]*x["sale_unit"] for x in next_lines)
        paid=sum(int(x["amount"]) for x in before["receipts"])
        if new_sales<paid:
            raise ImportErrorDetail("مبلغ جدید فاکتور از دریافتی ثبت‌شده کمتر است؛ اول دریافتی را اصلاح کن.")
        if inv["origin"]=="factory" and inv["status"]=="dispatched":
            old_cost=sum(int(x["qty"])*int(x["purchase_unit"]) for x in before["lines"])
            new_cost=sum(x["qty"]*x["purchase_unit"] for x in next_lines)
            customer_to_mehr=sum(int(r["amount"]) for r in before["receipts"]
                                 if r["destination"] in ("mehr","check_mehr"))
            linked=int(conn.execute("""SELECT COALESCE(SUM(-l.debt_delta),0)
                FROM sister_mehr_settlement_links a
                JOIN sister_mehr_ledger l ON l.reference=a.reference
                WHERE a.target_type='invoice' AND a.target_id=? AND l.kind='paid_to_mehr'""",
                (iid,)).fetchone()[0])
            if new_cost<customer_to_mehr+linked:
                raise ImportErrorDetail("بهای خرید جدید از مجموع واریزی مشتری نزد مهر و تسویه‌های این فاکتور کمتر می‌شود.")
            if mehr_balance(conn)["debt"]+new_cost-old_cost<0:
                raise ImportErrorDetail("به‌خاطر تهاترهای قبلی، بدهی مهر برای این اصلاح کافی نیست.")
        conn.execute("""INSERT INTO sister_invoice_customers(name,phone,created_at)
            VALUES (?,?,?) ON CONFLICT(name) DO UPDATE SET
            phone=CASE WHEN excluded.phone!='' THEN excluded.phone ELSE sister_invoice_customers.phone END""",
            (name,phone,now()))
        customer_id=conn.execute("SELECT id FROM sister_invoice_customers WHERE name=?",(name,)).fetchone()[0]
        if inv["status"]=="dispatched":
            if inv["origin"]=="home":
                _adjust_invoice_stock(conn,iid,before["lines"],next_lines,key)
            else:
                delta=sum(x["qty"]*x["purchase_unit"] for x in next_lines)-sum(
                    int(x["qty"])*int(x["purchase_unit"]) for x in before["lines"])
                if delta:
                    _ledger(conn,today(),delta,0,"factory_invoice_adjustment",
                            "invoice-edit:"+str(iid)+":"+key,
                            "اصلاح بهای خرید فاکتور #"+str(iid))
        conn.execute("DELETE FROM sister_invoice_lines WHERE invoice_id=?",(iid,))
        for line in next_lines:
            conn.execute("""INSERT INTO sister_invoice_lines
              (invoice_id,size,master_id,qty,purchase_unit,sale_unit)
              VALUES (?,?,?,?,?,?)""",
              (iid,line["size"],line["master_id"],line["qty"],line["purchase_unit"],line["sale_unit"]))
        conn.execute("""UPDATE sister_invoices SET customer_id=?,invoice_date=?,notes=?,version=version+1
            WHERE id=?""",(customer_id,day,memo,iid))
        after=_invoice_snapshot(conn,iid)
        _audit_invoice(conn,iid,"edit",before,after,key)
        conn.execute("COMMIT")
        return iid
    except Exception:
        if conn.in_transaction:conn.execute("ROLLBACK")
        raise


def edit_invoice_receipt(conn,invoice_id,receipt_id,amount,paid_on,notes,check_date,request_key):
    """Only correct amount/date/note; destination and bank stay unchanged."""
    key=_text(request_key,100)
    if not key:raise ImportErrorDetail("شناسه اصلاح دریافت لازم است.")
    val=money(amount)
    if val<=0:raise ImportErrorDetail("مبلغ دریافتی باید مثبت باشد.")
    day=_date(paid_on);memo=_text(notes)
    conn.execute("BEGIN IMMEDIATE")
    try:
        iid=int(invoice_id);rid=int(receipt_id)
        before=_invoice_snapshot(conn,iid)
        if before["invoice"]["is_void"]:raise ImportErrorDetail("فاکتور ابطال‌شده قابل اصلاح نیست.")
        receipt=next((x for x in before["receipts"] if x["id"]==rid),None)
        if receipt is None:raise ImportErrorDetail("این دریافت متعلق به فاکتور نیست.")
        if conn.execute("SELECT 1 FROM sister_invoice_audit WHERE request_key=?",(key,)).fetchone():
            raise ImportErrorDetail("این ویرایش قبلاً انجام شده است.")
        total=sum(int(x["qty"])*int(x["sale_unit"]) for x in before["lines"])
        others=sum(int(x["amount"]) for x in before["receipts"] if x["id"]!=rid)
        if others+val>total:raise ImportErrorDetail("جمع دریافتی‌ها نمی‌تواند از مبلغ فاکتور بیشتر شود.")
        cheque=_date(check_date,allow_future=True) if receipt["destination"]=="check_mehr" else None
        if receipt["destination"]=="check_mehr" and not cheque:
            raise ImportErrorDetail("تاریخ چک لازم است.")
        ref="invoice-receipt:"+str(rid)
        if receipt["destination"]=="mine" and receipt["account_id"] is not None:
            bank=conn.execute("""UPDATE sister_finance_movements
                SET amount_toman=?,movement_date=?
                WHERE reference=? AND kind='receipt' AND cancelled_at IS NULL""",(val,day,ref))
            if bank.rowcount!=1:raise ImportErrorDetail("گردش بانکی مرتبط با دریافت پیدا نشد.")
        elif receipt["destination"] in ("mehr","check_mehr"):
            old_credit=int(receipt["amount"])
            if mehr_balance(conn)["credit"]+val-old_credit<0:
                raise ImportErrorDetail("مبلغ جدید با تهاتر قبلی مهر سازگار نیست؛ ابتدا تهاتر را بررسی کن.")
            entry=conn.execute("""UPDATE sister_mehr_ledger SET credit_delta=?,occurred_on=?
                WHERE reference=? AND kind='customer_to_mehr'""",(val,day,ref))
            if entry.rowcount!=1:raise ImportErrorDetail("ثبت واریز مشتری نزد مهر پیدا نشد.")
        conn.execute("""UPDATE sister_invoice_receipts
            SET amount=?,paid_on=?,notes=?,check_date=? WHERE id=? AND invoice_id=?""",
            (val,day,memo,cheque,rid,iid))
        conn.execute("UPDATE sister_invoices SET version=version+1 WHERE id=?",(iid,))
        after=_invoice_snapshot(conn,iid)
        _audit_invoice(conn,iid,"receipt_edit",before,after,key)
        conn.execute("COMMIT")
        return rid
    except Exception:
        if conn.in_transaction:conn.execute("ROLLBACK")
        raise


def cancel_invoice(conn,invoice_id,request_key,expected_version):
    """Reverses one invoice exactly once; preserves lines and audit trail.

    Any recorded customer receipt or Mehr settlement must first be reconciled:
    automatically refunding real cash would be incorrect.
    """
    key=_text(request_key,100)
    if not key:raise ImportErrorDetail("شناسه ابطال لازم است.")
    try:iid=int(invoice_id);version=int(expected_version)
    except (TypeError,ValueError):raise ImportErrorDetail("شماره یا نسخه فاکتور نامعتبر است.")
    conn.execute("BEGIN IMMEDIATE")
    try:
        before=_invoice_snapshot(conn,iid)
        inv=before["invoice"]
        if inv["is_void"]:raise ImportErrorDetail("این فاکتور قبلاً ابطال شده است.")
        if inv["version"]!=version:raise ImportErrorDetail("فاکتور تغییر کرده؛ صفحه را تازه‌سازی کن.")
        if before["receipts"]:
            raise ImportErrorDetail("این فاکتور دریافت ثبت‌شده دارد؛ برای جلوگیری از حذف واریز واقعی، فعلاً فقط ویرایش فاکتور و دریافتی مجاز است.")
        linked=conn.execute("""SELECT 1 FROM sister_mehr_settlement_links
            WHERE target_type='invoice' AND target_id=?""",(iid,)).fetchone()
        if linked:raise ImportErrorDetail("فاکتور تسویه مهر دارد؛ پیش از ابطال باید تسویه آن بررسی شود.")
        if inv["status"]=="dispatched":
            if inv["origin"]=="home":
                _adjust_invoice_stock(conn,iid,before["lines"],[],key)
            else:
                old_cost=sum(int(x["qty"])*int(x["purchase_unit"]) for x in before["lines"])
                if mehr_balance(conn)["debt"]<old_cost:
                    raise ImportErrorDetail("با توجه به تهاترهای قبلی مهر، ابطال خودکار این فاکتور مجاز نیست.")
                _ledger(conn,today(),-old_cost,0,"factory_invoice_cancel",
                        "invoice-cancel:"+str(iid)+":"+key,
                        "ابطال فاکتور بدون دریافت مشتری #"+str(iid))
        conn.execute("""UPDATE sister_invoices SET is_void=1,voided_at=?,version=version+1 WHERE id=?""",
                     (now(),iid))
        after=_invoice_snapshot(conn,iid)
        _audit_invoice(conn,iid,"cancel",before,after,key)
        conn.execute("COMMIT")
        return iid
    except Exception:
        if conn.in_transaction:conn.execute("ROLLBACK")
        raise


def invoice_audit(conn,invoice_id):
    return [dict(r) for r in conn.execute("""SELECT id,action,created_at
         FROM sister_invoice_audit WHERE invoice_id=? ORDER BY id DESC""",(int(invoice_id),))]


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
