"""Explicitly void ONE confirmed DigiKala sales day, with exact stock reversal.

Receivables are derived from sales rows; no cash/bank movements are deleted.
Write a permanent row-level JSON audit before removing any sales. This action
never touches other dates, marketplace platforms or product definitions.
"""
from collections import defaultdict
from datetime import datetime, timezone
import json
import uuid

from .engine import ImportErrorDetail
from .effective_costs import valid_date
from .digikala_auto_link import parts_for
from .master_engine import now

SOURCE_COLUMNS={"seller":"seller_stock","khorshid":"khorshid_stock",
                "digikala":"digikala_stock"}

def void_daily_digikala_sales(conn,sale_date,confirm_date):
    day=valid_date(sale_date)
    if str(confirm_date)!=day:
        raise ImportErrorDetail("تأیید تاریخ حذف معتبر نیست؛ صورت روز حذف نشد.")
    conn.execute("BEGIN IMMEDIATE")
    try:
        rows=[dict(row) for row in conn.execute(
            "SELECT * FROM sales WHERE sale_date=? ORDER BY source,variant_id",(day,))]
        if not rows:
            raise ImportErrorDetail("برای این تاریخ صورت فروش ثبت‌شده‌ای وجود ندارد.")
        # A user cannot void earned claims already settled into the bank
        # when that would leave the marketplace ledger over-settled.
        from .sister_finance_logic import platform_balances
        finance=platform_balances(conn)["digikala"]
        earned_to_void=sum(
            int(x["qty"])*(int(x["price_toman"])-int(x["fee_toman"]))
            for x in rows)
        if finance["outstanding"]-earned_to_void<0:
            raise ImportErrorDetail(
                "حذف این صورت باعث می‌شود دریافتی‌های دیجی‌کالا از فروش‌های باقیمانده بیشتر شود. "
                "ابتدا تراکنش‌های تسویه در حسابداری را بررسی یا اصلاح کن.")
        stock_delta=defaultdict(int)
        components=[]
        for sale in rows:
            source=sale["source"]
            if source not in SOURCE_COLUMNS:
                raise ImportErrorDetail("منبع انبار تاریخی ناشناخته است؛ حذف متوقف شد.")
            variant=conn.execute("SELECT master_id FROM products WHERE variant_id=?",
                                (sale["variant_id"],)).fetchone()
            if variant is None or variant["master_id"] is None:
                raise ImportErrorDetail(
                    f"اتصال موجودی کد {sale['variant_id']} تغییر کرده؛ حذف خودکار ایمن نیست.")
            parts=parts_for(conn,sale["variant_id"],variant["master_id"])
            if not parts:
                raise ImportErrorDetail("اجزای کالای فروخته‌شده قابل شناسایی نیستند.")
            for master_id,per_pack in parts:
                mid=int(master_id)
                count=int(sale["qty"])*int(per_pack)
                if count<=0:raise ImportErrorDetail("تعداد فروش قدیمی نامعتبر است.")
                key=(mid,source)
                stock_delta[key]+=count
                components.append({"variant_id":sale["variant_id"],"source":source,
                                   "master_id":mid,"restored_units":count})
        snapshots=[]
        for (mid,source),amount in sorted(stock_delta.items()):
            col=SOURCE_COLUMNS[source]
            record=conn.execute(f"SELECT {col} FROM master_products WHERE id=?",
                                (mid,)).fetchone()
            if record is None:raise ImportErrorDetail("SKU فیزیکی حذف شده؛ حذف صورت متوقف شد.")
            previous=int(record[0])
            snapshots.append({"master_id":mid,"source":source,"before":previous,
                              "delta":amount,"after":previous+amount})
        conn.execute("""CREATE TABLE IF NOT EXISTS digikala_daily_void_audit (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           sale_date TEXT NOT NULL,
           deleted_at TEXT NOT NULL,
           deleted_sales_json TEXT NOT NULL,
           stock_reversals_json TEXT NOT NULL
        )""")
        snapshot={"sales":rows,"components":components,
                  "claim_removed_toman":earned_to_void}
        conn.execute("""INSERT INTO digikala_daily_void_audit(
            sale_date,deleted_at,deleted_sales_json,stock_reversals_json)
            VALUES(?,?,?,?)""",
            (day,now(),json.dumps(snapshot,ensure_ascii=False),
             json.dumps(snapshots,ensure_ascii=False)))
        for item in snapshots:
            col=SOURCE_COLUMNS[item["source"]]
            conn.execute(f"UPDATE master_products SET {col}=?,updated_at=? WHERE id=?",
                         (item["after"],now(),item["master_id"]))
            conn.execute("""INSERT INTO master_stock_events(
                occurred_at,master_id,source,delta,balance_after,reference)
                VALUES (?,?,?,?,?,?)""",
                (now(),item["master_id"],item["source"],item["delta"],
                 item["after"],"void-digikala:"+day+":"+uuid.uuid4().hex[:12]))
        deleted=conn.execute("DELETE FROM sales WHERE sale_date=?",(day,)).rowcount
        if deleted!=len(rows):raise ImportErrorDetail("تعداد ردیف‌های حذف شده تطابق ندارد.")
        # A pending preview captured before deletion must not re-post
        # a stale day while a different inventory snapshot is active.
        for row in conn.execute("SELECT token,payload FROM previews"):
            try:
                pending=json.loads(row["payload"])
            except (TypeError,ValueError):continue
            if pending.get("sale_date")==day:
                conn.execute("DELETE FROM previews WHERE token=?",(row["token"],))
        conn.execute("COMMIT")
        return {"sale_date":day,"deleted_lines":deleted,
                "restored_units":sum(x["delta"] for x in snapshots),
                "removed_claim":earned_to_void}
    except Exception:
        if conn.in_transaction:conn.execute("ROLLBACK")
        raise
