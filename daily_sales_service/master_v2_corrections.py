"""Safe corrections to warehouse adjustments and transfers.

Darma-equivalent actions are append-only audit corrections. Refuse any
rewrite when later stock activity could make the original document ambiguous.
"""
from .engine import ImportErrorDetail, money
from .master_engine import now
from .master_v2_logic import _warehouse_col

def _last_event(conn,master_id,location):
    return conn.execute("""SELECT id,reference,balance_after FROM master_stock_events
        WHERE master_id=? AND source=? ORDER BY id DESC LIMIT 1""",
        (master_id,location)).fetchone()

def undo_adjustment(conn,event_id):
    conn.execute("BEGIN IMMEDIATE")
    try:
        row=conn.execute("""SELECT id,master_id,source,delta,balance_after,reference
             FROM master_stock_events WHERE id=?""",(event_id,)).fetchone()
        if row is None or not str(row["reference"]).startswith("adjust:"):
            raise ImportErrorDetail("این سند اصلاح موجودی قابل بازگشت نیست.")
        loc=row["source"]
        col=_warehouse_col(loc)
        last=_last_event(conn,row["master_id"],loc)
        if last is None or last["id"]!=row["id"]:
            raise ImportErrorDetail("پس از این اصلاح گردش جدید ثبت شده و بازگشت خودکار ایمن نیست.")
        current=conn.execute(f"SELECT {col} FROM master_products WHERE id=?",(row["master_id"],)).fetchone()
        if current is None or int(current[0])!=int(row["balance_after"]):
            raise ImportErrorDetail("موجودی فعلی با سند قبلی تطابق ندارد.")
        restored=int(current[0])-int(row["delta"])
        if restored<0:raise ImportErrorDetail("بازگشت این اصلاح موجودی را منفی می‌کند.")
        conn.execute(f"UPDATE master_products SET {col}=?,updated_at=? WHERE id=?",
            (restored,now(),row["master_id"]))
        conn.execute("""INSERT INTO master_stock_events
           (occurred_at,master_id,source,delta,balance_after,reference)
           VALUES (?,?,?,?,?,?)""",
           (now(),row["master_id"],loc,-int(row["delta"]),restored,
            f"undo-adjust:{event_id}"))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK");raise

def revise_transfer(conn,transfer_id,target_qty):
    new=money(target_qty)
    conn.execute("BEGIN IMMEDIATE")
    try:
        t=conn.execute("SELECT * FROM master_transfers WHERE id=?",(transfer_id,)).fetchone()
        if t is None:raise ImportErrorDetail("سند انتقال پیدا نشد.")
        src,dst=t["from_location"],t["to_location"]
        col_from,col_to=_warehouse_col(src),_warehouse_col(dst)
        last_from=_last_event(conn,t["master_id"],src)
        last_to=_last_event(conn,t["master_id"],dst)
        if (last_from is None or last_to is None
            or not str(last_from["reference"]).startswith(t["reference"])
            or not str(last_to["reference"]).startswith(t["reference"])):
            raise ImportErrorDetail("بعد از انتقال گردش دیگری ثبت شده؛ ویرایش سند ایمن نیست.")
        old=int(t["quantity"]);difference=new-old
        row=conn.execute(f"SELECT {col_from},{col_to} FROM master_products WHERE id=?",(t["master_id"],)).fetchone()
        if row is None or int(row[0])!=int(last_from["balance_after"]) or int(row[1])!=int(last_to["balance_after"]):
            raise ImportErrorDetail("گردش‌ها با موجودی فعلی مطابقت ندارند.")
        next_from=int(row[0])-difference
        next_to=int(row[1])+difference
        if next_from<0 or next_to<0:raise ImportErrorDetail("موجودی انبار برای تغییر انتقال کافی نیست.")
        if difference:
            conn.execute(f"UPDATE master_products SET {col_from}=?,{col_to}=?,updated_at=? WHERE id=?",
                         (next_from,next_to,now(),t["master_id"]))
            for loc,delta,balance in ((src,-difference,next_from),(dst,difference,next_to)):
                conn.execute("""INSERT INTO master_stock_events
                   (occurred_at,master_id,source,delta,balance_after,reference)
                   VALUES (?,?,?,?,?,?)""",
                   (now(),t["master_id"],loc,delta,balance,
                    t["reference"]+f" correction {old}->{new}"))
            conn.execute("UPDATE master_transfers SET quantity=? WHERE id=?",(new,transfer_id))
        conn.execute("COMMIT")
        return {"old":old,"new":new,"delta":difference}
    except Exception:
        conn.execute("ROLLBACK");raise
