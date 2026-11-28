#!/usr/bin/env bash
# Read-only diagnostic of the exact 28 Nov 2026 DigiKala delivery report.
set -Eeuo pipefail
cd /opt/dia-darma-fresh
docker compose -f compose.fresh.yml exec -T sister-digikala python - <<'PY'
import os,sqlite3
from daily_sales_service.master_engine import _daily_digikala_price
from daily_sales_service.digikala_auto_link import parts_for
codes=[
 (2,67312039,12),(3,67255169,9),(4,75666433,7),
 (5,77626780,6),(6,30397621,4),(7,67255155,4),
 (8,67312063,4),(9,76198115,4),(10,77626754,4),
 (11,67312057,2),(12,68434400,2),(13,76949711,2),
 (14,30397622,1),(15,33509803,1),(16,39973104,1),
 (17,63981654,1),(18,63981671,1),(19,64222801,1),
 (20,64222805,1),(21,67254448,1),(22,67254455,1),
 (23,67254552,1),(24,67255163,1),(25,67255184,1),
 (26,68434368,1),(27,74906332,1),(28,76198098,1),
 (29,76442633,1),(30,77626728,1),(31,77626749,1),
 (32,77626767,1),(33,77626774,1),(34,79742279,1),
 (35,79742421,1),(36,80722570,1),(37,80722862,1)]
path=os.getenv("SALES_DB_PATH","/data/sales.sqlite3")
db=sqlite3.connect("file:"+path+"?mode=ro",uri=True)
db.row_factory=sqlite3.Row
db.execute("PRAGMA query_only=ON")
errs=[]
warnings=[]
print("REPORT_TOTAL",len(codes),"variants",sum(qty for _,_,qty in codes),"packages")
for excel_row,vid,qty in codes:
 p=db.execute("SELECT * FROM products WHERE variant_id=?",(vid,)).fetchone()
 reasons=[]
 master=None
 pieces=[]
 price=None
 price_origin=None
 if p is None:
  reasons.append("کد در کاتالوگ داخلی موجود نیست")
 else:
  master=(db.execute("SELECT * FROM master_products WHERE id=?",(p["master_id"],)).fetchone()
          if p["master_id"] is not None else None)
  if master is None:reasons.append("کد تنوع به کالای اصلی متصل نیست")
  elif not master["active"]:reasons.append("کالای اصلی غیرفعال است")
  if master is not None:
   pieces=parts_for(db,vid,master["id"])
   if not pieces:reasons.append("ترکیب موجودی ندارد")
   for part_id,multiplier in pieces:
    part=db.execute("SELECT title,size,color,active FROM master_products WHERE id=?",(part_id,)).fetchone()
    if part is None or not part["active"]:
     reasons.append("جزء فیزیکی غیرفعال/ناموجود: "+str(part_id))
   try:price,price_origin=_daily_digikala_price(db,p,master,"2026-11-28")
   except Exception as exc:reasons.append("بررسی قیمت خطا داد: "+repr(exc))
   if not price or price<=0:reasons.append("قیمت فروش معتبر برای ۲۸ نوامبر وجود ندارد")
  if not p["active"]:warnings.append("Excel "+str(excel_row)+" | "+str(vid)+" | کد کاتالوگ غیرفعال است؛ واردکننده ممکن است فروش قبلی را بپذیرد")
 if excel_row in (20,21):
  print("TARGET_EXCEL_ROW",excel_row,"CODE",vid,"QTY",qty)
  print("CATALOG",dict(p) if p else None)
  print("MASTER",dict(master) if master else None)
  print("PARTS",pieces,"PRICE",price,"PRICE_SOURCE",price_origin)
 if reasons:
  errs.append((excel_row,vid,qty,"؛ ".join(reasons)))
for excel_row,vid,qty,why in errs:
 print("FILE_VALIDATION_ERROR","EXCEL_ROW",excel_row,"VARIANT",vid,"QTY",qty,"REASON",why)
for message in warnings:print("FILE_WARNING",message)
if not errs:print("ALL_36_VARIANTS_CATALOG_AND_PRICE_OK")
print("ERROR_VARIANTS",len(errs))
daily=db.execute("""SELECT source,COUNT(*) AS n,COALESCE(SUM(qty),0) AS qty
 FROM sales WHERE sale_date='2026-11-28' GROUP BY source ORDER BY source""").fetchall()
for r in daily:print("EXISTING_TODAY_SALES",dict(r))
for vid in (64222805,67254448):
 past=db.execute("""SELECT sale_date,source,qty FROM sales WHERE variant_id=?
 ORDER BY sale_date DESC LIMIT 4""",(vid,)).fetchall()
 print("VARIANT_SALES_HISTORY",vid,[dict(row) for row in past])
db.close()
print("READ_ONLY_DIAGNOSTIC_COMPLETE; NO SALES OR STOCK CHANGED")
PY
