"""Bank-unallocated operating expenses and supplier settlements for sister panel.

The user chooses a purpose and amount, not a bank. Do not fabricate cash
movements or count a supplier settlement as new COGS. All amounts are Toman.
"""
from .engine import ImportErrorDetail, money
from .effective_costs import valid_date, today
from .master_engine import now

EXPENSES = (
    ("post", "هزینه پست / ارسال"),
    ("snap", "هزینه اسنپ / پیک"),
    ("carton", "هزینه کارتن / بسته‌بندی"),
    ("current", "هزینه جاری"),
    ("other", "سایر هزینه‌ها"),
)
SUPPLIER_SHORTCUTS = (
    ("dia", "دیا"),
    ("darma", "دارما"),
    ("bodyguard", "بادیگارد"),
    ("holder", "هولدر"),
)
EXPENSE_LABELS = dict(EXPENSES)
SUPPLIER_LABELS = dict(SUPPLIER_SHORTCUTS)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sister_manual_outgoings (
 id INTEGER PRIMARY KEY,
 kind TEXT NOT NULL CHECK(kind IN ('expense','supplier')),
 category TEXT NOT NULL,
 party_title TEXT NOT NULL DEFAULT '',
 linked_supplier_id INTEGER REFERENCES sister_purchase_suppliers(id),
 amount_toman INTEGER NOT NULL CHECK(amount_toman>0),
 paid_on TEXT NOT NULL,
 notes TEXT NOT NULL DEFAULT '',
 request_key TEXT NOT NULL UNIQUE,
 cancelled_at TEXT,
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sister_manual_outgoings_date
  ON sister_manual_outgoings(paid_on,id);
CREATE INDEX IF NOT EXISTS idx_sister_manual_outgoings_supplier
  ON sister_manual_outgoings(linked_supplier_id,cancelled_at);
"""

def ensure_schema(conn):
    conn.executescript(SCHEMA)

def _clean(value,limit=350):
    result=str(value or "").strip()
    if len(result)>limit:
        raise ImportErrorDetail("متن بیش از حد مجاز است.")
    return result

def record_outgoing(conn,purpose,amount,paid_on,request_key,notes="",other_supplier=""):
    """Purpose is expense:post or supplier:dia etc. No bank is guessed.

    Existing recorded supplier debt is reduced only for an unambiguous exact
    supplier match with enough unpaid purchase debt. Otherwise the payment
    remains an explicit unmatched supplier advance, never silently settled.
    """
    value=money(amount)
    if value<1:raise ImportErrorDetail("مبلغ پرداخت باید مثبت باشد.")
    day=valid_date(paid_on)
    if day>today():raise ImportErrorDetail("تاریخ پرداخت نمی‌تواند در آینده باشد.")
    key=_clean(request_key,100)
    if not key:raise ImportErrorDetail("شناسه ثبت پرداخت لازم است.")
    note=_clean(notes)
    purpose=_clean(purpose,100)
    kind,sep,category=purpose.partition(":")
    if not sep:raise ImportErrorDetail("نوع هزینه یا طرف حساب نامعتبر است.")
    if kind=="expense" and category in EXPENSE_LABELS:
        title=EXPENSE_LABELS[category]
    elif kind=="supplier" and category in SUPPLIER_LABELS:
        title=SUPPLIER_LABELS[category]
    elif kind=="supplier" and category=="other":
        title=_clean(other_supplier,120)
        if len(title)<2:raise ImportErrorDetail("نام تأمین‌کننده را وارد کن.")
        if "".join(title.split()).replace("ي","ی").replace("ك","ک")=="مهر":
            raise ImportErrorDetail("پرداخت به مهر را از گزینه اختصاصی «مهر» ثبت کن.")
    else:
        raise ImportErrorDetail("نوع هزینه یا تأمین‌کننده معتبر نیست.")
    conn.execute("BEGIN IMMEDIATE")
    try:
        old=conn.execute("SELECT id FROM sister_manual_outgoings WHERE request_key=?",(key,)).fetchone()
        if old:raise ImportErrorDetail("این پرداخت قبلاً ثبت شده است.")
        linked=None
        if kind=="supplier":
            # Find ONE exact-name supplier only. Do not infer from unrelated SKUs.
            matches=list(conn.execute("""SELECT id,name FROM sister_purchase_suppliers
                WHERE TRIM(name)=?""",(title,)))
            if len(matches)==1:
                sid=int(matches[0]["id"])
                from .sister_purchases import supplier_totals
                if supplier_totals(conn,sid)["due"]>=value:
                    linked=sid
        cur=conn.execute("""INSERT INTO sister_manual_outgoings
          (kind,category,party_title,linked_supplier_id,amount_toman,paid_on,notes,request_key,created_at)
          VALUES (?,?,?,?,?,?,?,?,?)""",
          (kind,category,title,linked,value,day,note,key,now()))
        conn.execute("COMMIT")
        return int(cur.lastrowid)
    except Exception:
        conn.execute("ROLLBACK")
        raise

def cancel_outgoing(conn,identifier):
    try:item_id=int(identifier)
    except (TypeError,ValueError):raise ImportErrorDetail("شناسه پرداخت معتبر نیست.")
    conn.execute("BEGIN IMMEDIATE")
    try:
        row=conn.execute("UPDATE sister_manual_outgoings SET cancelled_at=? WHERE id=? AND cancelled_at IS NULL",
                         (now(),item_id))
        if not row.rowcount:raise ImportErrorDetail("پرداخت پیدا نشد یا قبلاً ابطال شده.")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

def outgoing_history(conn,limit=150):
    return [dict(row) for row in conn.execute("""SELECT * FROM sister_manual_outgoings
        ORDER BY id DESC LIMIT ?""",(int(limit),))]

def expense_total(conn):
    return int(conn.execute("""SELECT COALESCE(SUM(amount_toman),0)
        FROM sister_manual_outgoings
        WHERE kind='expense' AND cancelled_at IS NULL""").fetchone()[0])

def unmatched_supplier_total(conn):
    return int(conn.execute("""SELECT COALESCE(SUM(amount_toman),0)
        FROM sister_manual_outgoings
        WHERE kind='supplier' AND linked_supplier_id IS NULL AND cancelled_at IS NULL""").fetchone()[0])
