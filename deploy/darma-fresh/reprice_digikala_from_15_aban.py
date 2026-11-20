"""One-time, guarded DigiKala price correction from 15 Aban 1405.

Read-only by default. Apply requires an exact digest from an immediately
preceding preview. Source stock, quantity, COGS, receipts and import audit
are never changed. A verified SQLite backup is REQUIRED for --apply.
"""
import argparse
import hashlib
import json
import os
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

from daily_sales_service.engine import fee_unit, settings_for
from daily_sales_service.effective_costs import today
from daily_sales_service.master_engine import _daily_digikala_price

START = "2026-11-06"  # 15 Aban 1405
EXPLICIT = (
    "قیمت تاریخ‌دار دیجی‌کالا",
    "قیمت ثبت‌شده در کاتالوگ دیجی‌کالا",
    "قیمت فروش اختصاصی کد تنوع",
)
AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS dk_sales_repricing_audit (
  batch_id TEXT NOT NULL, corrected_at TEXT NOT NULL,
  sale_date TEXT NOT NULL, source TEXT NOT NULL, variant_id INTEGER NOT NULL,
  qty INTEGER NOT NULL,
  old_price INTEGER NOT NULL, new_price INTEGER NOT NULL,
  old_commission INTEGER NOT NULL, new_commission INTEGER NOT NULL,
  old_processing INTEGER NOT NULL, new_processing INTEGER NOT NULL,
  old_vat INTEGER NOT NULL, new_vat INTEGER NOT NULL,
  old_fee INTEGER NOT NULL, new_fee INTEGER NOT NULL,
  price_source TEXT NOT NULL,
  PRIMARY KEY(batch_id,sale_date,source,variant_id)
);
CREATE TABLE IF NOT EXISTS dk_sales_repricing_rules_audit (
  batch_id TEXT NOT NULL, variant_id INTEGER NOT NULL,
  effective_date TEXT NOT NULL, previous_price INTEGER, new_price INTEGER NOT NULL,
  PRIMARY KEY(batch_id,variant_id,effective_date)
);
"""

def read_plan(conn, as_of):
    cfg = settings_for(conn)
    rows = conn.execute("""
      SELECT s.sale_date,s.source,s.variant_id,s.qty,s.price_toman,
             s.commission_toman,s.processing_toman,s.vat_toman,s.fee_toman,
             p.category AS marketplace_category
      FROM sales s JOIN products p ON p.variant_id=s.variant_id
      WHERE s.sale_date>=?
      ORDER BY s.sale_date,s.source,s.variant_id
    """,(START,)).fetchall()
    prices = {}
    sources = {}
    for p in conn.execute("""
      SELECT p.*, m.sale_price_toman AS master_sale_price
      FROM products p LEFT JOIN master_products m ON m.id=p.master_id
      WHERE p.variant_id IN (
        SELECT DISTINCT variant_id FROM sales WHERE sale_date>=?
      )
    """,(START,)):
        mid = p["master_id"]
        master = {"id":mid,"sale_price_toman":p["master_sale_price"]} if mid is not None else None
        value, source = _daily_digikala_price(conn,p,master,as_of)
        prices[int(p["variant_id"])] = value
        sources[int(p["variant_id"])] = source

    updates = []
    fallback = []
    missing = []
    fee_only = []
    explicit_prices = {}
    for row in rows:
        r = dict(row)
        vid = int(r["variant_id"])
        target = prices.get(vid)
        source = sources.get(vid,"نامشخص")
        old_price = int(r["price_toman"])
        allowed = any(source.startswith(prefix) for prefix in EXPLICIT)
        if not target:
            missing.append((vid,r["sale_date"],old_price))
            continue
        if not allowed:
            if int(target)!=old_price:
                fallback.append((vid,r["sale_date"],old_price,int(target),source))
            continue
        explicit_prices[vid] = int(target)
        new = fee_unit(int(target),r["marketplace_category"],cfg)
        if old_price == int(target):
            if int(r["fee_toman"])!=new["fee"]:
                fee_only.append((vid,r["sale_date"],int(r["fee_toman"]),new["fee"]))
            continue
        updates.append({
            "sale_date":r["sale_date"],"source":r["source"],"variant_id":vid,
            "qty":int(r["qty"]),"old_price":old_price,"new_price":int(target),
            "old_commission":int(r["commission_toman"]), "new_commission":new["commission"],
            "old_processing":int(r["processing_toman"]),"new_processing":new["processing"],
            "old_vat":int(r["vat_toman"]),"new_vat":new["vat"],
            "old_fee":int(r["fee_toman"]),"new_fee":new["fee"],"price_source":source,
        })
    receipt = conn.execute("""
      SELECT COALESCE(SUM(m.amount_toman),0)
      FROM sister_finance_movements m
      JOIN sister_finance_parties p ON p.id=m.party_id
      WHERE p.code='digikala' AND m.kind='receipt' AND m.cancelled_at IS NULL
    """).fetchone()[0]
    all_sales_net = conn.execute("""
      SELECT COALESCE(SUM(qty*(price_toman-fee_toman)),0) FROM sales
    """).fetchone()[0]
    net_change = sum((u["new_price"]-u["old_price"]-u["new_fee"]+u["old_fee"])*u["qty"] for u in updates)
    plan = {
        "start":START,"as_of":as_of,"updates":updates,
        "fallback":fallback,"missing":missing,"fee_only":fee_only,
        "explicit_prices":explicit_prices,
        "receipt":int(receipt),"sales_net_before":int(all_sales_net),
        "net_change":net_change,"total_rows":len(rows),
        "total_packs":sum(int(r["qty"]) for r in rows),
        "settings":cfg,
    }
    serial = json.dumps(plan,sort_keys=True,ensure_ascii=False,separators=(",",":"))
    plan["digest"] = hashlib.sha256(serial.encode()).hexdigest()
    return plan

def print_plan(plan):
    rows = plan["updates"]
    counts = Counter(u["price_source"] for u in rows)
    gross = sum((u["new_price"]-u["old_price"])*u["qty"] for u in rows)
    fee = sum((u["new_fee"]-u["old_fee"])*u["qty"] for u in rows)
    print("DIGIKALA_REPRICE_PREFLIGHT_READ_ONLY")
    print("از ۱۵ آبان:",plan["start"],"| قیمت فعلی در:",plan["as_of"])
    print("کل ردیف فروش و بسته‌های بازه:",plan["total_rows"],plan["total_packs"])
    print("ردیف‌های تغییر قیمتِ دارای منبع صریح:",len(rows),
          "| بسته:",sum(x["qty"] for x in rows))
    print("کدهای دارای قیمت ثبت‌شده:",len(plan["explicit_prices"]))
    print("منابع قیمت‌های اصلاحی:",dict(counts))
    print("ردیف‌های دارای اختلاف قیمت ولی منبع پیش‌فرض (اصلاح نمی‌شوند):",len(plan["fallback"]))
    for x in plan["fallback"][:25]:
        print("  NEED_PRICE",*x,sep=" | ")
    print("ردیف بدون قیمت معتبر (اصلاح نمی‌شود):",len(plan["missing"]))
    for x in plan["missing"][:15]:
        print("  MISSING",*x,sep=" | ")
    print("اختلاف فقط کارمزد، بدون اختلاف قیمت (اصلاح نمی‌شود):",len(plan["fee_only"]))
    print("تفاوت مبلغ فروش:",f"{gross:+,}","تومان")
    print("تفاوت هزینه دیجی‌کالا:",f"{fee:+,}","تومان")
    print("تفاوت خالص طلب دیجی‌کالا:",f"{plan['net_change']:+,}","تومان")
    print("دریافت‌های ثبت‌شده از دیجی‌کالا:",f"{plan['receipt']:,}","تومان")
    before = plan["sales_net_before"]-plan["receipt"]
    after = before+plan["net_change"]
    print("مانده طلب قبل/بعد با فرض اصلاح:",f"{before:,}",f"{after:,}")
    if after<0: print("BLOCKED: طلب پس از اصلاح منفی می‌شود؛ نیاز به تطبیق تسویه.")
    if plan["fallback"]: print("BLOCKED: قیمت‌های پیش‌فرض دارای اختلاف باید اول تأیید/ثبت شوند.")
    print("PREVIEW_DIGEST",plan["digest"])
    print("هیچ فروش، کسر موجودی، کارمزد، قیمت یا دریافت بانکی تغییر نکرد.")

def backup_database(conn, target):
    dest = Path(target)
    if not dest.is_absolute() or not str(dest).startswith("/data/"):
        raise RuntimeError("مسیر بکاپ باید داخل /data/ باشد.")
    if dest.exists(): raise RuntimeError("بکاپ با این نام قبلاً وجود دارد.")
    dest.parent.mkdir(parents=True,exist_ok=True)
    try:
        with sqlite3.connect(str(dest)) as backup:
            conn.backup(backup)
            if backup.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
                raise RuntimeError("بکاپ SQLite سالم نیست.")
        if dest.stat().st_size<4096: raise RuntimeError("بکاپ ناقص است.")
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    return str(dest)

def apply(conn,expected,as_of,backup_path):
    before = read_plan(conn,as_of)
    if before["digest"]!=expected:
        raise RuntimeError("اطلاعات از زمان پیش‌نمایش عوض شده؛ ابتدا پیش‌نمایش جدید بگیر.")
    if before["fallback"]:
        raise RuntimeError("برای بعضی کدها فقط قیمت پیش‌فرض موجود است؛ اصلاح خودکار متوقف شد.")
    if before["missing"]:
        raise RuntimeError("بعضی کدها قیمت معتبر ندارند؛ اصلاح خودکار متوقف شد.")
    if before["sales_net_before"]-before["receipt"]+before["net_change"]<0:
        raise RuntimeError("طلب دیجی‌کالا پس از اصلاح منفی می‌شود؛ ابتدا تسویه‌ها را تطبیق بده.")
    if not before["updates"]:
        print("NO_PRICE_DIFFERENCES: تغییر قیمت لازم نیست.")
        return
    bak=backup_database(conn,backup_path)
    print("SQLITE_BACKUP_VERIFIED",bak,flush=True)
    conn.execute("BEGIN IMMEDIATE")
    try:
        latest=read_plan(conn,as_of)
        if latest["digest"]!=expected:
            raise RuntimeError("اطلاعات حین تهیه بکاپ تغییر کرده؛ اصلاح متوقف شد.")
        stamp=datetime.now().isoformat(timespec="seconds")
        batch=stamp.replace(":","-") + "-" + expected[:10]
        for statement in AUDIT_SCHEMA.strip().split(";"):
            if statement.strip():conn.execute(statement)
        for u in latest["updates"]:
            keys = ("new_price","new_commission","new_processing","new_vat","new_fee")
            vals=[u[key] for key in keys]
            cur=conn.execute("""
              UPDATE sales
              SET price_toman=?,commission_toman=?,processing_toman=?,vat_toman=?,fee_toman=?
              WHERE sale_date=? AND source=? AND variant_id=? AND qty=?
                AND price_toman=? AND commission_toman=? AND
                    processing_toman=? AND vat_toman=? AND fee_toman=?
            """,vals+[u[k] for k in ("sale_date","source","variant_id","qty",
                                     "old_price","old_commission","old_processing","old_vat","old_fee")])
            if cur.rowcount != 1: raise RuntimeError("فروش هنگام اصلاح تغییر کرد: "+str(u["variant_id"]))
            conn.execute("""
              INSERT INTO dk_sales_repricing_audit VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,(batch,stamp)+tuple(u[k] for k in (
                  "sale_date","source","variant_id","qty","old_price","new_price",
                  "old_commission","new_commission","old_processing","new_processing",
                  "old_vat","new_vat","old_fee","new_fee","price_source")))
        for vid,price in sorted(latest["explicit_prices"].items()):
            existing = conn.execute("""
              SELECT effective_date,price_toman FROM dk_dated_sale_prices
              WHERE variant_id=? AND effective_date>=? AND effective_date<=?
            """,(vid,START,as_of)).fetchall()
            current = {r["effective_date"]:int(r["price_toman"]) for r in existing}
            for day, prior in sorted({**current,START:current.get(START)}.items()):
                if prior == price: continue
                conn.execute("""INSERT INTO dk_sales_repricing_rules_audit
                  (batch_id,variant_id,effective_date,previous_price,new_price)
                  VALUES (?,?,?,?,?)""",(batch,vid,day,prior,price))
                conn.execute("""INSERT INTO dk_dated_sale_prices
                  (variant_id,effective_date,price_toman,recorded_at) VALUES (?,?,?,?)
                  ON CONFLICT(variant_id,effective_date) DO UPDATE SET
                    price_toman=excluded.price_toman,recorded_at=excluded.recorded_at
                """,(vid,day,price,stamp))
        conn.execute("COMMIT")
        print("REPRICE_DONE",len(latest["updates"]),"rows",
              f"{latest['net_change']:+,}","toman net change",
              "audit batch",batch,"backup",bak)
    except Exception:
        if conn.in_transaction:conn.execute("ROLLBACK")
        raise

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--apply",action="store_true")
    p.add_argument("--expect",default="")
    p.add_argument("--backup",default="")
    p.add_argument("--db",default="/data/sales.sqlite3")
    args=p.parse_args()
    if args.db!="/data/sales.sqlite3" and not os.getenv("DIGIKALA_REPRICE_TEST_DB"):
        raise RuntimeError("فقط دیتابیس ایزوله پنل مجاز است.")
    if args.apply and (len(args.expect)!=64 or not args.backup):
        p.error("--apply needs --expect <preview digest> and --backup /data/unique-name.sqlite3")
    conn=sqlite3.connect(args.db,uri=False,timeout=30,isolation_level=None)
    conn.row_factory=sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        as_of=today()
        if not args.apply:
            conn.execute("PRAGMA query_only=ON")
            print_plan(read_plan(conn,as_of))
        else:
            apply(conn,args.expect,as_of,args.backup)
    finally:conn.close()

if __name__=="__main__":
    main()
