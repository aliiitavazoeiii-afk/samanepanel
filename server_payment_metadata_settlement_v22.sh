#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

step "1) START DATABASE + REQUIRE HEALTHY LIVE WEB"
docker compose up -d db || fail "database start failed"
i=1
while [ "$i" -le 30 ]; do
  docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 && break
  [ "$i" -eq 30 ] && fail "PostgreSQL did not become ready"
  sleep 1
  i=$((i+1))
done
docker compose exec -T web python manage.py check >/dev/null || fail "current live web is not healthy"

step "2) BACKUP + BEFORE STATE"
mkdir -p backups
BACKUP="backups/before-payment-metadata-settlement-v22-$(date +%Y%m%d-%H%M%S).sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "backup failed"
[ -s "$BACKUP" ] || fail "backup is empty"
CAP_BEFORE=$(docker compose exec -T web python manage.py capital_audit_v9 | awk -F'= ' '/CAPITAL TOTAL/{gsub(/[[:space:]]/,"",$2);print $2}' | tail -1)
[ -n "$CAP_BEFORE" ] || fail "could not read capital before"
DARMA_BEFORE=$(docker compose exec -T web python manage.py shell -c 'from django.db.models import Sum; from core.models import Brand,StockBalance; b=Brand.objects.get(name="دارما"); print(int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0))' 2>/dev/null | tail -1)
[ -n "$DARMA_BEFORE" ] || fail "could not read Darma stock before"
echo "BACKUP = $BACKUP"
echo "CAPITAL BEFORE = $CAP_BEFORE"
echo "DARMA BEFORE = $DARMA_BEFORE"

step "3) BUILD NEW WEB"
docker compose build web || fail "web build failed"

step "4) NO MODEL/MIGRATION DRIFT"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "model/migration drift detected"

step "5) NEW-IMAGE PREFLIGHT"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"
docker compose run --rm --entrypoint python web manage.py check_excel_web || fail "template/route preflight failed"
docker compose run --rm --entrypoint python web manage.py check_v22_payment_workflows || fail "v22 payment workflow check failed"
docker compose run --rm --entrypoint python web manage.py check_v19_features || fail "v19 feature check failed"
docker compose run --rm --entrypoint python web manage.py check_capital_integrity_v14 || fail "capital integrity check failed"

step "6) VERIFY PREFLIGHT DID NOT TOUCH BUSINESS DATA"
CAP_PRELIVE=$(docker compose run --rm --entrypoint python web manage.py capital_audit_v9 | awk -F'= ' '/CAPITAL TOTAL/{gsub(/[[:space:]]/,"",$2);print $2}' | tail -1)
DARMA_PRELIVE=$(docker compose run --rm --entrypoint python web manage.py shell -c 'from django.db.models import Sum; from core.models import Brand,StockBalance; b=Brand.objects.get(name="دارما"); print(int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0))' 2>/dev/null | tail -1)
[ "$CAP_BEFORE" = "$CAP_PRELIVE" ] || fail "capital changed during preflight: before=$CAP_BEFORE now=$CAP_PRELIVE"
[ "$DARMA_BEFORE" = "$DARMA_PRELIVE" ] || fail "Darma stock changed during preflight: before=$DARMA_BEFORE now=$DARMA_PRELIVE"

step "7) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy || fail "caddy restart failed"
sleep 3

step "8) FINAL LIVE CHECK"
docker compose exec -T web python manage.py check_v22_payment_workflows || fail "live v22 workflow check failed"
docker compose exec -T web python manage.py check_capital_integrity_v14 || fail "live capital integrity failed"
CAP_AFTER=$(docker compose exec -T web python manage.py capital_audit_v9 | awk -F'= ' '/CAPITAL TOTAL/{gsub(/[[:space:]]/,"",$2);print $2}' | tail -1)
DARMA_AFTER=$(docker compose exec -T web python manage.py shell -c 'from django.db.models import Sum; from core.models import Brand,StockBalance; b=Brand.objects.get(name="دارما"); print(int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0))' 2>/dev/null | tail -1)
[ "$CAP_BEFORE" = "$CAP_AFTER" ] || fail "capital changed by code deployment: before=$CAP_BEFORE after=$CAP_AFTER"
[ "$DARMA_BEFORE" = "$DARMA_AFTER" ] || fail "Darma stock changed by code deployment: before=$DARMA_BEFORE after=$DARMA_AFTER"

echo ""
echo "======================================"
echo "SUCCESS: PAYMENT METADATA + SETTLEMENT V22 DEPLOYED"
echo "Backup: $BACKUP"
echo "Capital unchanged by deployment: $CAP_AFTER"
echo "Darma stock unchanged by deployment: $DARMA_AFTER"
echo "Date/note/actual-paid edits on unchanged material purchase will NOT reverse stock."
echo "Invoice value and actual paid amount are now separate."
echo "======================================"