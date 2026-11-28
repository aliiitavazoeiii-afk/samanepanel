#!/usr/bin/env bash
# Diagnose Excel row 22 of packageDeliveryReport_17958447678359.xlsx; read only.
set -Eeuo pipefail
cd /opt/dia-darma-fresh
docker compose -f compose.fresh.yml exec -T sister-digikala python - <<'PY'
import os,sqlite3
p=os.getenv("SALES_DB_PATH","/data/sales.sqlite3")
db=sqlite3.connect("file:"+p+"?mode=ro",uri=True)
db.row_factory=sqlite3.Row
db.execute("PRAGMA query_only=ON")
vid=67254455
print("=== EXCEL ROW 22; 1 SOLD PACK BK-WH XXL BLACK/WHITE ===")
v=db.execute("SELECT variant_id,product_id,category,title,active,master_id,sale_price_toman,list_price_rial,promotion_price_rial FROM products WHERE variant_id=?",(vid,)).fetchone()
print("TARGET_INTERNAL_CATALOG",dict(v) if v else "MISSING")
print("=== SIMILAR LISTINGS WITH THEIR LINKED PHYSICAL PIECES ===")
matches=list(db.execute("""SELECT variant_id,product_id,category,title,active,master_id,
 sale_price_toman,list_price_rial,promotion_price_rial
 FROM products
 WHERE variant_id IN (67254448,67254455)
 OR (title LIKE '%BK-WH%' AND (title LIKE '%XXL%' OR title LIKE '%XL%'))
 OR (title LIKE '%مشکی%' AND title LIKE '%سفید%' AND title LIKE '%2 عددی%' AND title LIKE '%XXL%')
 ORDER BY variant_id LIMIT 60"""))
for row in matches:
 d=dict(row)
 print("SIMILAR_VARIANT",d)
 parts=list(db.execute("""SELECT x.position,x.master_id,m.title,m.size,m.color,m.code,m.active
 FROM dk_variant_parts x JOIN master_products m ON m.id=x.master_id
 WHERE x.variant_id=? ORDER BY x.position""",(row["variant_id"],)))
 for x in parts:print("  PART",dict(x))
 if not parts and row["master_id"] is not None:
  m=db.execute("SELECT id,title,size,color,code,active FROM master_products WHERE id=?",(row["master_id"],)).fetchone()
  print("  DEFAULT_MASTER",dict(m) if m else "MISSING")
print("=== AVAILABLE DIA WOMEN PHYSICAL XXL/2XL STOCK OPTIONS ===")
masters=db.execute("""SELECT id,code,title,size,color,seller_stock,khorshid_stock,active
 FROM master_products WHERE category='شورت زنانه دیا' AND size IN ('XXL','2XL')
 ORDER BY title,code,color LIMIT 80""")
for row in masters:print("POSSIBLE_MASTER",dict(row))
print("=== TODAY NOV 28 REGISTERED SALES ===")
for row in db.execute("""SELECT sale_date,source,variant_id,qty FROM sales
 WHERE sale_date='2026-11-28' AND variant_id IN (67254448,67254455)
 ORDER BY sale_date,variant_id"""):print("TODAY_SALE",dict(row))
print("DIAGNOSTIC_DONE_READ_ONLY")
db.close()
PY
