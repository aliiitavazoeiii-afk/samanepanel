"""Isolated sister-business financial subledger and unified daily sales.

Receivables are DERIVED from the authoritative sale tables, never double-posted.
A receipt reduces the platform receivable and increases the chosen cash/bank
account. Payments decrease that cash account; they are not sale expenses unless
recorded separately. Cost of goods reduces profit, NOT marketplace receivable.
All money is integer Toman. Legacy Darma/Dia financial DB is not accessed.
"""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from .engine import ImportErrorDetail, money
from .effective_costs import valid_date,today
from .master_engine import now

PARTIES=(("digikala","دیجی‌کالا"),("basalam","باسلام"),
         ("site","سایت"),("mold","قالب‌ها"),("snap","اسنپ"))
PLATFORM_KEYS=("digikala","basalam","site","mold")

SCHEMA="""
CREATE TABLE IF NOT EXISTS sister_finance_parties (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 code TEXT NOT NULL UNIQUE,
 title TEXT NOT NULL UNIQUE,
 is_platform INTEGER NOT NULL DEFAULT 0,
 active INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sister_finance_accounts (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 title TEXT NOT NULL UNIQUE,
 opening_toman INTEGER NOT NULL DEFAULT 0,
 active INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sister_finance_movements (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 kind TEXT NOT NULL CHECK(kind IN ('receipt','payment')),
 party_id INTEGER NOT NULL REFERENCES sister_finance_parties(id),
 account_id INTEGER NOT NULL REFERENCES sister_finance_accounts(id),
 movement_date TEXT NOT NULL,
 amount_toman INTEGER NOT NULL CHECK(amount_toman>0),
 reference TEXT,
 note TEXT NOT NULL DEFAULT '',
 cancelled_at TEXT,
 created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sister_finance_ref
 ON sister_finance_movements(kind,party_id,reference)
 WHERE reference IS NOT NULL AND cancelled_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_sister_finance_movement_date
 ON sister_finance_movements(movement_date,kind);
"""

def ensure_finance_schema(conn):
    conn.executescript(SCHEMA)
    for code,title in PARTIES:
        conn.execute("""INSERT OR IGNORE INTO sister_finance_parties
           (code,title,is_platform,created_at) VALUES(?,?,?,?)""",
           (code,title,1 if code in PLATFORM_KEYS else 0,now()))

def commission_for(channel,gross):
    """Known rules only: Basalam 15% total gross; others direct sales 0%.

    DigiKala is never computed here, as its authoritative sale rows already
    snapshot its own exact commission, processing and taxes.
    """
    amount=int(gross)
    if amount<0:raise ImportErrorDetail("مبلغ فروش نامعتبر است.")
    if channel=="basalam":
        return int((Decimal(amount)*Decimal("0.15")).quantize(Decimal("1"),rounding=ROUND_HALF_UP))
    if channel in ("site","mold"):return 0
    raise ImportErrorDetail("کارمزد این پلتفرم هنوز تعریف نشده است.")

def effective_fee(channel,gross,stored):
    return commission_for(channel,gross) if stored is None else int(stored)

def _day_bounds(from_date=None,to_date=None):
    start=valid_date(from_date) if from_date else None
    end=valid_date(to_date) if to_date else None
    if start and end and start>end:raise ImportErrorDetail("تاریخ شروع از پایان بزرگ‌تر است.")
    return start,end

def sale_lines(conn,channel=None,from_date=None,to_date=None,limit=None):
    """All three sale sources, COGS snapshots intact, no mutable postings."""
    start,end=_day_bounds(from_date,to_date)
    if channel and channel not in PLATFORM_KEYS:raise ImportErrorDetail("پلتفرم نامعتبر است.")
    lines=[]
    if channel in (None,"digikala"):
        sql="""SELECT s.sale_date,s.source,s.variant_id,s.qty,s.price_toman,
                     s.fee_toman,s.cost_toman,p.title
               FROM sales s JOIN products p ON p.variant_id=s.variant_id WHERE 1=1"""
        args=[]
        if start:sql+=" AND s.sale_date>=?";args.append(start)
        if end:sql+=" AND s.sale_date<=?";args.append(end)
        for r in conn.execute(sql,args):
            r=dict(r)
            packs=int(r["qty"])
            gross=packs*int(r["price_toman"])
            fee=packs*int(r["fee_toman"])
            cost=packs*int(r["cost_toman"]) if r["cost_toman"] is not None else None
            pack_parts=conn.execute("SELECT COUNT(*) FROM dk_variant_parts WHERE variant_id=?",
                                    (r["variant_id"],)).fetchone()[0]
            lines.append({"source":"digikala","sale_id":str(r["variant_id"])+":"+r["sale_date"]+":"+r["source"],
                 "sale_date":r["sale_date"],"title":r["title"],"packs":packs,
                 "units":packs*max(1,int(pack_parts)),
                 "gross":gross,"fees":fee,"cogs":cost,
                 "net":gross-fee,"profit":gross-fee-cost if cost is not None else None,
                 "kind":"digikala"})
    for source,table,query in (
       ("v3","platform_sales","""SELECT s.id,s.channel,s.sale_date,s.packs,s.units,
                              s.gross_toman,s.cogs_toman,s.commission_toman,l.title
                              FROM platform_sales s JOIN platform_listings l ON l.id=s.listing_id"""),
       ("v4","platform_bundle_sales","""SELECT s.id,s.channel,s.sale_date,s.packs,s.units,
                              s.gross_toman,s.cogs_toman,s.commission_toman,b.title || ' / ' || v.size AS title
                              FROM platform_bundle_sales s
                              JOIN platform_bundle_variants v ON v.id=s.variant_id
                              JOIN platform_bundle_models b ON b.id=v.bundle_id""")):
        sql=query+" WHERE 1=1";args=[]
        if channel and channel!="digikala":sql+=" AND s.channel=?";args.append(channel)
        elif channel=="digikala":continue
        if start:sql+=" AND s.sale_date>=?";args.append(start)
        if end:sql+=" AND s.sale_date<=?";args.append(end)
        for row in conn.execute(sql,args):
            r=dict(row)
            gross=int(r["gross_toman"])
            fees=effective_fee(r["channel"],gross,r["commission_toman"])
            cost=int(r["cogs_toman"]) if r["cogs_toman"] is not None else None
            lines.append({"source":r["channel"],"sale_id":source+":"+str(r["id"]),
                 "sale_date":r["sale_date"],"title":r["title"],"packs":int(r["packs"]),
                 "units":int(r["units"]),"gross":gross,"fees":fees,"cogs":cost,
                 "net":gross-fees,"profit":gross-fees-cost if cost is not None else None,
                 "kind":source})
    lines.sort(key=lambda x:(x["sale_date"],x["sale_id"]),reverse=True)
    return lines[:int(limit)] if limit is not None else lines

def sales_report(conn,channel=None,from_date=None,to_date=None,limit=100):
    lines=sale_lines(conn,channel,from_date,to_date)
    total={"orders":len(lines),"packs":sum(r["packs"] for r in lines),
           "units":sum(r["units"] for r in lines),
           "gross":sum(r["gross"] for r in lines),
           "fees":sum(r["fees"] for r in lines),
           "net":sum(r["net"] for r in lines),
           "cogs_known":sum((r["cogs"] or 0) for r in lines),
           "unknown_cost_lines":sum(1 for r in lines if r["cogs"] is None),
           "profit":None,"lines":lines[:limit]}
    if total["unknown_cost_lines"]==0:total["profit"]=total["net"]-total["cogs_known"]
    return total

def parties(conn):
    return [dict(x) for x in conn.execute(
        "SELECT * FROM sister_finance_parties WHERE active=1 ORDER BY is_platform DESC,id")]

def accounts(conn):
    sql="""SELECT a.*,COALESCE(SUM(CASE WHEN m.id IS NULL THEN 0
              WHEN m.kind='receipt' THEN m.amount_toman
              ELSE -m.amount_toman END),0) AS movement_toman
           FROM sister_finance_accounts a
           LEFT JOIN sister_finance_movements m ON m.account_id=a.id AND m.cancelled_at IS NULL
           GROUP BY a.id ORDER BY a.id"""
    result=[dict(x) for x in conn.execute(sql)]
    for x in result:x["balance"]=int(x["opening_toman"])+int(x["movement_toman"])
    return result

def add_party(conn,title):
    name=str(title or "").strip()
    if len(name)<2 or len(name)>100:raise ImportErrorDetail("نام طرف حساب باید بین ۲ تا ۱۰۰ کاراکتر باشد.")
    if name in {p[1] for p in PARTIES}:raise ImportErrorDetail("این پلتفرم از قبل تعریف شده است.")
    import uuid
    conn.execute("BEGIN IMMEDIATE")
    try:
        if conn.execute("SELECT 1 FROM sister_finance_parties WHERE title=?",(name,)).fetchone():
            raise ImportErrorDetail("این طرف حساب قبلاً تعریف شده است.")
        row=conn.execute("""INSERT INTO sister_finance_parties
           (code,title,is_platform,created_at) VALUES(?,?,0,?)""",
           ("person-"+uuid.uuid4().hex[:16],name,now()))
        conn.execute("COMMIT");return int(row.lastrowid)
    except Exception:
        conn.execute("ROLLBACK");raise

def add_account(conn,title,opening="0"):
    name=str(title or "").strip()
    if len(name)<2 or len(name)>100:raise ImportErrorDetail("نام حساب نامعتبر است.")
    amount=money(opening)
    conn.execute("BEGIN IMMEDIATE")
    try:
        if conn.execute("SELECT 1 FROM sister_finance_accounts WHERE title=?",(name,)).fetchone():
            raise ImportErrorDetail("این حساب قبلاً ثبت شده است.")
        row=conn.execute("""INSERT INTO sister_finance_accounts(title,opening_toman,created_at)
            VALUES(?,?,?)""",(name,amount,now()))
        conn.execute("COMMIT");return int(row.lastrowid)
    except Exception:
        conn.execute("ROLLBACK");raise

def movements(conn,kind=None,limit=150):
    sql="""SELECT m.*,p.title party_title,p.code party_code,
                a.title account_title
        FROM sister_finance_movements m
        JOIN sister_finance_parties p ON p.id=m.party_id
        JOIN sister_finance_accounts a ON a.id=m.account_id WHERE 1=1"""
    args=[]
    if kind:
        if kind not in ("receipt","payment"):raise ImportErrorDetail("نوع گردش معتبر نیست.")
        sql+=" AND m.kind=?";args.append(kind)
    sql+=" ORDER BY m.id DESC LIMIT ?";args.append(limit)
    return [dict(x) for x in conn.execute(sql,args)]

def register_movement(conn,kind,party_id,account_id,amount,movement_date,reference="",note=""):
    if kind not in ("receipt","payment"):raise ImportErrorDetail("نوع دریافت یا پرداخت نامعتبر است.")
    val=money(amount)
    if val<=0:raise ImportErrorDetail("مبلغ باید بزرگ‌تر از صفر باشد.")
    date_key=valid_date(movement_date)
    if date_key>today():raise ImportErrorDetail("ثبت دریافت یا پرداخت در آینده مجاز نیست.")
    note=str(note or "").strip()
    ref=str(reference or "").strip() or None
    if len(note)>500 or (ref and len(ref)>100):raise ImportErrorDetail("شرح یا شماره پیگیری خیلی طولانی است.")
    try:pid=int(party_id);aid=int(account_id)
    except (TypeError,ValueError):raise ImportErrorDetail("حساب یا طرف حساب انتخاب‌شده معتبر نیست.")
    conn.execute("BEGIN IMMEDIATE")
    try:
        person=conn.execute("SELECT * FROM sister_finance_parties WHERE id=? AND active=1",(pid,)).fetchone()
        bank=conn.execute("SELECT * FROM sister_finance_accounts WHERE id=? AND active=1",(aid,)).fetchone()
        if person is None or bank is None:raise ImportErrorDetail("طرف حساب یا حساب بانکی معتبر نیست.")
        if ref and conn.execute("""SELECT id FROM sister_finance_movements
            WHERE kind=? AND party_id=? AND reference=? AND cancelled_at IS NULL""",
            (kind,pid,ref)).fetchone():
            raise ImportErrorDetail("شماره پیگیری تکراری است؛ گردش دوباره ثبت نشد.")
        row=conn.execute("""INSERT INTO sister_finance_movements
          (kind,party_id,account_id,movement_date,amount_toman,reference,note,created_at)
          VALUES(?,?,?,?,?,?,?,?)""",(kind,pid,aid,date_key,val,ref,note,now()))
        conn.execute("COMMIT")
        return int(row.lastrowid)
    except Exception:
        conn.execute("ROLLBACK");raise

def cancel_movement(conn,identifier):
    try:mid=int(identifier)
    except (TypeError,ValueError):raise ImportErrorDetail("شناسه تراکنش معتبر نیست.")
    conn.execute("BEGIN IMMEDIATE")
    try:
        row=conn.execute("""UPDATE sister_finance_movements
          SET cancelled_at=? WHERE id=? AND cancelled_at IS NULL""",(now(),mid))
        if not row.rowcount:raise ImportErrorDetail("تراکنش پیدا نشد یا قبلاً ابطال شده است.")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK");raise

def platform_balances(conn):
    due={key:sales_report(conn,key)["net"] for key in PLATFORM_KEYS}
    receipts={r["code"]:int(r["amount"])
              for r in conn.execute("""SELECT p.code,SUM(m.amount_toman) amount
               FROM sister_finance_movements m
               JOIN sister_finance_parties p ON p.id=m.party_id
               WHERE m.cancelled_at IS NULL AND m.kind='receipt'
               GROUP BY p.code""")}
    balances={}
    for code,title in PARTIES:
        if code not in PLATFORM_KEYS:continue
        earned=due[code];settled=receipts.get(code,0)
        balances[code]={"code":code,"title":title,
                         "sales_net":earned,"received":settled,
                         "outstanding":earned-settled}
    return balances

def overview(conn):
    by_platform=platform_balances(conn)
    cash=accounts(conn)
    total_due=sum(r["outstanding"] for r in by_platform.values())
    all_sales=sales_report(conn)
    return {"platforms":by_platform,"accounts":cash,
            "total_receivable":total_due,
            "cash_balance":sum(x["balance"] for x in cash),
            "sales":{k:v for k,v in all_sales.items() if k!="lines"},
            "receipts":sum(r["amount_toman"] for r in movements(conn,"receipt",100000)
                           if not r["cancelled_at"]),
            "payments":sum(r["amount_toman"] for r in movements(conn,"payment",100000)
                           if not r["cancelled_at"])}

