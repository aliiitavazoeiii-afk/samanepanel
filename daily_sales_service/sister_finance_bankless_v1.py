"""Bank-unallocated receipts from marketplaces; no fabricated bank movements.

Receipts reduce the corresponding platform claim, never sales or profit.
The original bank-linked movements and invoice/Mehr settlements stay untouched.
"""
from .engine import ImportErrorDetail,money
from .effective_costs import valid_date,today
from .master_engine import now

SCHEMA = """
CREATE TABLE IF NOT EXISTS sister_unallocated_receipts (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 party_id INTEGER NOT NULL REFERENCES sister_finance_parties(id),
 amount_toman INTEGER NOT NULL CHECK(amount_toman>0),
 movement_date TEXT NOT NULL,
 reference TEXT,
 note TEXT NOT NULL DEFAULT '',
 request_key TEXT NOT NULL UNIQUE,
 cancelled_at TEXT,
 created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_unallocated_receipts_reference
 ON sister_unallocated_receipts(party_id,reference)
 WHERE reference IS NOT NULL AND cancelled_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_unallocated_receipts_party_date
 ON sister_unallocated_receipts(party_id,movement_date);
"""

def ensure_schema(conn):
    conn.executescript(SCHEMA)

def receipt_history(conn,limit=150):
    return [dict(row) for row in conn.execute("""
       SELECT r.*,p.code AS party_code,p.title AS party_title
       FROM sister_unallocated_receipts r
       JOIN sister_finance_parties p ON p.id=r.party_id
       ORDER BY r.id DESC LIMIT ?""",(int(limit),))]

def received_by_platform(conn):
    return {r["code"]:int(r["total"]) for r in conn.execute("""
       SELECT p.code, SUM(r.amount_toman) AS total
       FROM sister_unallocated_receipts r
       JOIN sister_finance_parties p ON p.id=r.party_id
       WHERE r.cancelled_at IS NULL
       GROUP BY p.code""")}

def received_total(conn):
    return int(conn.execute("""
        SELECT COALESCE(SUM(amount_toman),0)
        FROM sister_unallocated_receipts WHERE cancelled_at IS NULL""").fetchone()[0])

def record_receipt(conn,party_id,amount,paid_on,request_key,reference="",note=""):
    from .sister_finance_logic import PLATFORM_KEYS,platform_balances
    val=money(amount)
    if val<=0:
        raise ImportErrorDetail("مبلغ دریافتی باید بزرگ‌تر از صفر باشد.")
    day=valid_date(paid_on)
    if day>today():
        raise ImportErrorDetail("تاریخ دریافتی نمی‌تواند در آینده باشد.")
    key=str(request_key or "").strip()
    reference=str(reference or "").strip() or None
    note=str(note or "").strip()
    if not key or len(key)>100:
        raise ImportErrorDetail("شناسه ثبت دریافتی نامعتبر است.")
    if (reference and len(reference)>100) or len(note)>500:
        raise ImportErrorDetail("شماره پیگیری یا توضیحات بیش از حد طولانی است.")
    try:
        pid=int(party_id)
    except (TypeError,ValueError):
        raise ImportErrorDetail("پلتفرم معتبر نیست.")
    conn.execute("BEGIN IMMEDIATE")
    try:
        party=conn.execute("SELECT code,title FROM sister_finance_parties WHERE id=? AND active=1",
                           (pid,)).fetchone()
        if party is None or party["code"] not in PLATFORM_KEYS:
            raise ImportErrorDetail("این فرم فقط برای دریافتی از پلتفرم فروش است.")
        if conn.execute("SELECT 1 FROM sister_unallocated_receipts WHERE request_key=?",
                        (key,)).fetchone():
            raise ImportErrorDetail("این دریافتی قبلاً ثبت شده است.")
        if reference:
            if conn.execute("""SELECT 1 FROM sister_unallocated_receipts
               WHERE party_id=? AND reference=? AND cancelled_at IS NULL""",
               (pid,reference)).fetchone() or conn.execute("""
               SELECT 1 FROM sister_finance_movements WHERE party_id=?
               AND kind='receipt' AND reference=? AND cancelled_at IS NULL""",
               (pid,reference)).fetchone():
                raise ImportErrorDetail("شماره پیگیری تکراری است؛ دریافتی دوباره ثبت نشد.")
        balance=platform_balances(conn)[party["code"]]["outstanding"]
        if val>balance:
            raise ImportErrorDetail(
                "مبلغ دریافتی بیشتر از مانده طلب است. مانده: "+
                f"{int(balance):,}"+" تومان.")
        row=conn.execute("""INSERT INTO sister_unallocated_receipts
           (party_id,amount_toman,movement_date,reference,note,request_key,created_at)
           VALUES(?,?,?,?,?,?,?)""",(pid,val,day,reference,note,key,now()))
        conn.execute("COMMIT")
        return int(row.lastrowid)
    except Exception:
        conn.execute("ROLLBACK")
        raise

def cancel_receipt(conn,receipt_id):
    try:
        item_id=int(receipt_id)
    except (ValueError,TypeError):
        raise ImportErrorDetail("شناسه دریافتی معتبر نیست.")
    conn.execute("BEGIN IMMEDIATE")
    try:
        row=conn.execute("""UPDATE sister_unallocated_receipts SET cancelled_at=?
              WHERE id=? AND cancelled_at IS NULL""",(now(),item_id))
        if not row.rowcount:
            raise ImportErrorDetail("دریافتی پیدا نشد یا قبلاً ابطال شده است.")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
