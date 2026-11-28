#!/usr/bin/env bash
# Register ONLY missing DigiKala variant 67254455, a two-piece DIA XXL black+white pack.
# Derived from the user-supplied delivery report and read-only live catalog diagnostic.
set -Eeuo pipefail
cd /opt/dia-darma-fresh
test "$(id -u)" = "0" || { echo "STOP: root required"; exit 1; }
test "$(git branch --show-current)" = "dia-darma-fresh" || { echo "STOP: unexpected branch"; exit 1; }
docker compose -f compose.fresh.yml config --quiet
CID="$(docker compose -f compose.fresh.yml ps -q sister-digikala)"
test -n "$CID" && test "$(docker inspect -f '{{.State.Running}}' "$CID")" = "true"
umask 077
STAMP="$(date +%Y%m%dT%H%M%S)"
BACKUP="/opt/dia-darma-fresh/backups/dk-variant-67254455-$STAMP"
mkdir -p "$BACKUP"
echo "=== Back up live SQLite database online before any change ==="
docker compose -f compose.fresh.yml exec -T sister-digikala python - "$STAMP" <<'PY'
import os,sqlite3,sys
src=sqlite3.connect("file:"+os.getenv("SALES_DB_PATH","/data/sales.sqlite3")+"?mode=ro",uri=True)
target=sqlite3.connect("/data/variant-67254455-"+sys.argv[1]+".sqlite3")
try:
    src.backup(target)
finally:
    target.close()
    src.close()
PY
docker cp "$CID:/data/variant-67254455-$STAMP.sqlite3" "$BACKUP/sister-sales.sqlite3"
test -s "$BACKUP/sister-sales.sqlite3"
echo "BACKUP_READY=$BACKUP"
echo "=== Safe idempotent catalog registration (no stock/sale changes) ==="
docker compose -f compose.fresh.yml exec -T sister-digikala python - <<'PY'
import os,sqlite3,json
from daily_sales_service.engine import normalize
from daily_sales_service.master_engine import now
from daily_sales_service.digikala_auto_link import parts_for
DB=os.getenv("SALES_DB_PATH","/data/sales.sqlite3")
TARGET=67254455
SIBLING=67254448
BLACK=185
WHITE=181
TITLE="شورت زنانه دیا مدل BK-WH مجموعه 2 عددی | XXL | مشکی - سفید | گارانتی اصالت و سلامت فیزیکی کالا"
db=sqlite3.connect(DB,timeout=30,isolation_level=None)
db.row_factory=sqlite3.Row
db.execute("PRAGMA foreign_keys=ON")
db.execute("PRAGMA busy_timeout=30000")
try:
    db.execute("BEGIN IMMEDIATE")
    sibling=db.execute("SELECT * FROM products WHERE variant_id=?",(SIBLING,)).fetchone()
    if sibling is None:raise RuntimeError("STOP: XL sibling listing missing; refusing inference")
    if int(sibling["product_id"])!=19199181 or "BK-WH" not in sibling["title"] or "XL" not in sibling["title"]:
        raise RuntimeError("STOP: sibling product family has unexpectedly changed")
    sibling_parts=parts_for(db,SIBLING,sibling["master_id"])
    if sibling_parts!=[(180,1),(184,1)] and sibling_parts!=[(184,1),(180,1)]:
        raise RuntimeError("STOP: sibling black/white pair no longer matches known model")
    if int(sibling["list_price_rial"] or 0)<=0:
        raise RuntimeError("STOP: related catalog lacks fallback price; price needs confirmation")
    for mid,color,code in ((BLACK,"مشکی","DI-W-04"),(WHITE,"سفید","DI-W-03")):
        master=db.execute("SELECT id,code,category,size,color,active FROM master_products WHERE id=?",(mid,)).fetchone()
        if (not master or master["code"]!=code or master["category"]!="شورت زنانه دیا"
            or master["size"]!="XXL" or master["color"]!=color or int(master["active"])!=1):
            raise RuntimeError("STOP: DIA XXL physical SKU changed or inactive: "+str(mid))
    existing=db.execute("SELECT * FROM products WHERE variant_id=?",(TARGET,)).fetchone()
    if existing is not None:
        parts=parts_for(db,TARGET,existing["master_id"])
        if (existing["title"]!=TITLE or int(existing["product_id"])!=int(sibling["product_id"])
            or parts!=[(181,1),(185,1)] and parts!=[(185,1),(181,1)]):
            raise RuntimeError("STOP: target variant already exists with different data; no overwrite")
        print("VARIANT_ALREADY_LINKED_CORRECTLY",TARGET,"PARTS",parts)
        db.execute("COMMIT")
    else:
        stats_before=(db.execute("SELECT COUNT(*) FROM sales").fetchone()[0],
                      db.execute("SELECT COUNT(*) FROM master_stock_events").fetchone()[0],
                      [(r["id"],r["seller_stock"],r["khorshid_stock"])
                       for r in db.execute("SELECT id,seller_stock,khorshid_stock FROM master_products WHERE id IN (?,?) ORDER BY id",(BLACK,WHITE))])
        # Use the same two-piece product family as the verified XL sibling,
        # but no copied historic stock, cost snapshot, or sale records.
        db.execute("""INSERT INTO products
         (variant_id,product_id,category,title,title_key,active,
          list_price_rial,promotion_price_rial,seller_stock,digikala_stock,
          reserved,cost_toman,seeded_at,master_id,sale_price_toman)
         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
         (TARGET,int(sibling["product_id"]),sibling["category"],TITLE,normalize(TITLE),1,
          int(sibling["list_price_rial"]),0,0,0,0,None,now(),BLACK,None))
        db.executemany("""INSERT INTO dk_variant_parts(variant_id,position,master_id)
                         VALUES (?,?,?)""",[(TARGET,1,BLACK),(TARGET,2,WHITE)])
        db.execute("""INSERT INTO dk_auto_match_audit
           (variant_id,status,reason,proposed_parts,scanned_at)
           VALUES (?,?,?,?,?)""",
           (TARGET,"manual_connected",
            "ثبت کد جدید BK-WH XXL بر اساس گزارش ارسالی و تطبیق دو SKU دقیق مشکی/سفید",
            json.dumps([BLACK,WHITE]),now()))
        stats_after=(db.execute("SELECT COUNT(*) FROM sales").fetchone()[0],
                     db.execute("SELECT COUNT(*) FROM master_stock_events").fetchone()[0],
                     [(r["id"],r["seller_stock"],r["khorshid_stock"])
                      for r in db.execute("SELECT id,seller_stock,khorshid_stock FROM master_products WHERE id IN (?,?) ORDER BY id",(BLACK,WHITE))])
        if stats_before!=stats_after:raise RuntimeError("STOP: unexpected sales/stock change")
        db.execute("COMMIT")
        print("VARIANT_CATALOG_INSERTED_OK",TARGET)
    v=db.execute("SELECT variant_id,title,product_id,list_price_rial,master_id FROM products WHERE variant_id=?",(TARGET,)).fetchone()
    print("LINKED_VARIANT",dict(v))
    print("PHYSICAL_PARTS_PER_SOLD_PACK",parts_for(db,TARGET,v["master_id"]))
    print("ESTIMATED_FALLBACK_UNIT_PRICE_TOMAN",int(v["list_price_rial"])//10)
    print("IMPORTANT: fallback price copied from related XL listing; verify amount in preview before committing sales.")
    print("NO_SALES_OR_STOCK_CHANGED; upload original report once and inspect preview before confirmation.")
except Exception:
    if db.in_transaction:db.execute("ROLLBACK")
    raise
finally:db.close()
PY
echo "DK_VARIANT_67254455_REGISTERED_OK"
echo "BACKUP=$BACKUP"
