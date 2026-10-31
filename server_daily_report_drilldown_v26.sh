#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

step "1) START DB + REQUIRE HEALTHY CURRENT WEB"
docker compose up -d db || fail "database start failed"
i=1
while [ "$i" -le 30 ]; do
  docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 && break
  [ "$i" -eq 30 ] && fail "PostgreSQL did not become ready"
  sleep 1
  i=$((i+1))
done
docker compose exec -T web python manage.py check >/dev/null || fail "current live web is not healthy"

snapshot_live(){
  CAPITAL=$(docker compose exec -T web python manage.py capital_audit_v9 | awk -F'= ' '/CAPITAL TOTAL/{gsub(/[[:space:]]/,"",$2);print $2}' | tail -1)
  STOCK=$(docker compose exec -T web python manage.py shell -c 'from django.db.models import Sum; from core.models import StockBalance; rows=StockBalance.objects.values("brand__name").annotate(q=Sum("qty")).order_by("brand__name"); print("|".join("%s=%s" % (r["brand__name"], int(r["q"] or 0)) for r in rows))' 2>/dev/null | tail -1)
  SALES=$(docker compose exec -T web python manage.py shell -c 'from django.db.models import Sum; from core.models import SaleDay,SaleLine,SaleAllocation; vals=(SaleDay.objects.count(),SaleLine.objects.count(),int(SaleLine.objects.aggregate(v=Sum("quantity"))["v"] or 0),SaleAllocation.objects.count(),int(SaleAllocation.objects.aggregate(v=Sum("qty"))["v"] or 0)); print("days=%s|lines=%s|qty=%s|allocs=%s|allocqty=%s" % vals)' 2>/dev/null | tail -1)
  [ -n "$CAPITAL" ] || fail "could not read live capital snapshot"
  [ -n "$STOCK" ] || fail "could not read live stock snapshot"
  [ -n "$SALES" ] || fail "could not read live sales snapshot"
}

snapshot_new_image(){
  CAPITAL=$(docker compose run --rm --entrypoint python web manage.py capital_audit_v9 | awk -F'= ' '/CAPITAL TOTAL/{gsub(/[[:space:]]/,"",$2);print $2}' | tail -1)
  STOCK=$(docker compose run --rm --entrypoint python web manage.py shell -c 'from django.db.models import Sum; from core.models import StockBalance; rows=StockBalance.objects.values("brand__name").annotate(q=Sum("qty")).order_by("brand__name"); print("|".join("%s=%s" % (r["brand__name"], int(r["q"] or 0)) for r in rows))' 2>/dev/null | tail -1)
  SALES=$(docker compose run --rm --entrypoint python web manage.py shell -c 'from django.db.models import Sum; from core.models import SaleDay,SaleLine,SaleAllocation; vals=(SaleDay.objects.count(),SaleLine.objects.count(),int(SaleLine.objects.aggregate(v=Sum("quantity"))["v"] or 0),SaleAllocation.objects.count(),int(SaleAllocation.objects.aggregate(v=Sum("qty"))["v"] or 0)); print("days=%s|lines=%s|qty=%s|allocs=%s|allocqty=%s" % vals)' 2>/dev/null | tail -1)
  [ -n "$CAPITAL" ] || fail "could not read new-image capital snapshot"
  [ -n "$STOCK" ] || fail "could not read new-image stock snapshot"
  [ -n "$SALES" ] || fail "could not read new-image sales snapshot"
}

step "2) BACKUP + BEFORE STATE"
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="backups/before-daily-report-drilldown-v26-${STAMP}.sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "database backup is empty"
snapshot_live
CAP_BEFORE="$CAPITAL"
STOCK_BEFORE="$STOCK"
SALES_BEFORE="$SALES"
echo "BACKUP = $BACKUP"
echo "CAPITAL BEFORE = $CAP_BEFORE"
echo "STOCK BEFORE = $STOCK_BEFORE"
echo "SALES BEFORE = $SALES_BEFORE"

step "3) BUILD LATEST WEB IMAGE"
docker compose build web || fail "web build failed"

step "4) NEW IMAGE PREFLIGHT"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "model/migration drift detected"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"
docker compose run --rm --entrypoint python web manage.py check_excel_web || fail "template/route preflight failed"
docker compose run --rm --entrypoint python web manage.py check_daily_report_v26 || fail "daily report v26 check failed"
docker compose run --rm --entrypoint python web manage.py check_v23_delivery_import || fail "Digikala title/status regression check failed"
docker compose run --rm --entrypoint python web manage.py check_v22_payment_workflows || fail "payment workflow check failed"
docker compose run --rm --entrypoint python web manage.py check_v19_features || fail "v19 feature check failed"
docker compose run --rm --entrypoint python web manage.py check_capital_integrity_v14 || fail "capital integrity check failed"

step "5) VERIFY PREFLIGHT WAS READ-ONLY"
snapshot_new_image
[ "$CAPITAL" = "$CAP_BEFORE" ] || fail "capital changed during preflight: before=$CAP_BEFORE now=$CAPITAL"
[ "$STOCK" = "$STOCK_BEFORE" ] || fail "stock changed during preflight: before=$STOCK_BEFORE now=$STOCK"
[ "$SALES" = "$SALES_BEFORE" ] || fail "sales/allocations changed during preflight: before=$SALES_BEFORE now=$SALES"

step "6) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy || fail "caddy restart failed"
sleep 3

step "7) FINAL LIVE CHECK"
docker compose exec -T web python manage.py check || fail "final Django check failed"
docker compose exec -T web python manage.py check_daily_report_v26 || fail "live daily report v26 check failed"
docker compose exec -T web python manage.py check_v23_delivery_import || fail "live Digikala regression check failed"
docker compose exec -T web python manage.py check_capital_integrity_v14 || fail "live capital integrity failed"
snapshot_live
[ "$CAPITAL" = "$CAP_BEFORE" ] || fail "capital changed by deployment: before=$CAP_BEFORE after=$CAPITAL"
[ "$STOCK" = "$STOCK_BEFORE" ] || fail "stock changed by deployment: before=$STOCK_BEFORE after=$STOCK"
[ "$SALES" = "$SALES_BEFORE" ] || fail "sales/allocations changed by deployment: before=$SALES_BEFORE after=$SALES"

echo ""
echo "======================================"
echo "SUCCESS: DAILY REPORT DRILLDOWN V26 DEPLOYED"
echo "Backup: $BACKUP"
echo "Capital unchanged: $CAPITAL"
echo "Stock unchanged: $STOCK"
echo "Sales/allocations unchanged: $SALES"
echo "Report: Takvin/Darma -> size -> sold models"
echo "Rows: code + sold colors + price + packs + shorts + gross + Digikala + profit"
echo "Digikala model source: TITLE ONLY; seller-code column ignored"
echo "D-220 vs rah220 conflict regression: checked"
echo "======================================"