"""Read-only audit of currently configured DigiKala sale prices against posted sales.

Run INSIDE the isolated sister-digikala container using python -.
No DB initialization, writes, migrations, transaction updates or stock changes.
"""
import sqlite3
from collections import defaultdict
from datetime import date

from daily_sales_service.engine import fee_unit, settings_for
from daily_sales_service.master_engine import _daily_digikala_price

START = "2026-11-06"  # 15 Aban 1405
AS_OF = date.today().isoformat()

conn = sqlite3.connect("file:/data/sales.sqlite3?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA query_only=ON")
try:
    sales = list(conn.execute("""
        SELECT s.sale_date, s.source, s.variant_id, s.qty,
               s.price_toman, s.fee_toman,
               p.title, p.category AS marketplace_category,
               p.master_id, m.sale_price_toman AS master_sale_price
        FROM sales s
        JOIN products p ON p.variant_id=s.variant_id
        LEFT JOIN master_products m ON m.id=p.master_id
        WHERE s.sale_date >= ?
        ORDER BY s.sale_date, s.variant_id, s.source
    """, (START,)))
    variants = {
        int(row["variant_id"]): row
        for row in conn.execute("""
            SELECT p.*,m.sale_price_toman AS master_sale_price
            FROM products p LEFT JOIN master_products m ON m.id=p.master_id
            WHERE p.variant_id IN (
                SELECT DISTINCT variant_id FROM sales WHERE sale_date>=?
            )
        """, (START,))
    }
    cfg = settings_for(conn)
    data = defaultdict(lambda: {"rows": [], "packs": 0, "gross_delta": 0,
                                "fee_delta": 0, "changed_rows": 0})
    totals = {"gross": 0, "fee": 0, "changed": 0, "packs": 0}
    print("DIGIKALA_PRICE_AUDIT_READ_ONLY")
    print("از ۱۵ آبان ۱۴۰۵ /", START, "| نرخ تنظیم‌شده در تاریخ", AS_OF)
    print("روزهای فروش:", ", ".join(sorted({s["sale_date"] for s in sales})) or "هیچ")
    print("کل ردیف فروش:", len(sales), "| کل بسته:", sum(int(s["qty"]) for s in sales))
    print("کدهای یکتا:", len(variants))
    print()
    for row in sales:
        vid = int(row["variant_id"])
        var = variants[vid]
        master = ({"id":var["master_id"], "sale_price_toman":var["master_sale_price"]}
                  if var["master_id"] is not None else None)
        target, source = _daily_digikala_price(conn,var,master,AS_OF)
        if target is None or target <= 0:
            target_fee = None
        else:
            target_fee = fee_unit(target,row["marketplace_category"],cfg)["fee"]
        n = int(row["qty"])
        old = int(row["price_toman"])
        old_fee = int(row["fee_toman"])
        d = data[vid]
        d["price"] = target
        d["source"] = source
        d["title"] = row["title"]
        d["packs"] += n
        d["rows"].append((str(row["sale_date"]),int(row["price_toman"]),n))
        if target is None:
            d["missing"] = True
        elif int(target) != old or int(target_fee) != old_fee:
            d["changed_rows"] += 1
            d["gross_delta"] += (int(target)-old)*n
            d["fee_delta"] += (int(target_fee)-old_fee)*n
            totals["changed"] += 1
            totals["packs"] += n
            totals["gross"] += (int(target)-old)*n
            totals["fee"] += (int(target_fee)-old_fee)*n
    for vid in sorted(data):
        d = data[vid]
        last = conn.execute("""
            SELECT effective_date, price_toman FROM dk_dated_sale_prices
            WHERE variant_id=? ORDER BY effective_date DESC LIMIT 1
        """, (vid,)).fetchone()
        dated = (f'{last["price_toman"]:,} از {last["effective_date"]}'
                 if last else "ثبت نشده")
        prior = ", ".join(f"{p:,} تومان" for p in sorted({p for _,p,_ in d["rows"]}))
        status = "اختلاف" if d["changed_rows"] else ("قیمت نامشخص" if d.get("missing") else "مطابق")
        print(f'{vid} | {status} | {d["packs"]} بسته | فروش ثبت‌شده: {prior} '
              f'| قیمت فعلی: {d["price"]:,}' if d["price"] else
              f'{vid} | قیمت نامشخص | {d["packs"]} بسته | فروش ثبت‌شده: {prior}')
        print(f'  تاریخ‌دار آخر: {dated} | منبع قیمت فعلی: {d["source"]}'
              f' | {d["changed_rows"]} ردیف نیازمند بازبینی')
    print()
    print("=== جمع اختلاف‌ها با قیمت فعلی ===")
    print("تعداد ردیف‌های دارای اختلاف قیمت یا کارمزد:", totals["changed"])
    print("تعداد بسته‌های این ردیف‌ها:", totals["packs"])
    print("تفاوت مبلغ ناخالص فروش (تومان):", f'{totals["gross"]:+,}')
    print("تفاوت کارمزد و هزینه دیجی‌کالا (تومان):", f'{totals["fee"]:+,}')
    print("تفاوت طلب حاصل از فروش (تومان):", f'{totals["gross"]-totals["fee"]:+,}')
    print("توجه: این فقط مقایسه است؛ هیچ قیمت، فروش، موجودی یا طلبی تغییر نکرد.")
finally:
    conn.close()
