#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

set -a
. ./.env || fail "could not load .env"
set +a

step "1) START DATABASE"
docker compose up -d db || fail "database start failed"
i=1
while [ "$i" -le 30 ]; do
  docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 && break
  [ "$i" -eq 30 ] && fail "PostgreSQL did not become ready"
  sleep 1
  i=$((i+1))
done

step "2) BACKUP"
mkdir -p backups
BACKUP="backups/before-saleonly-anbaresh-novani-v19-$(date +%Y%m%d-%H%M%S).sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "backup failed"
[ -s "$BACKUP" ] || fail "backup is empty"
echo "BACKUP: $BACKUP"

step "3) LIVE DATA GUARDS BEFORE MIGRATION"
if ! docker compose ps --status running web 2>/dev/null | grep -q web; then
  fail "live web container is not running; cannot establish safe before-state"
fi

ANB_STATE=$(docker compose exec -T web python manage.py shell -c '
from django.db.models import Sum
from core.models import Brand, StockBalance
b=Brand.objects.filter(name="انبارش").first()
qs=StockBalance.objects.filter(brand=b) if b else StockBalance.objects.none()
nonzero=qs.exclude(qty=0).count()
print(str(qs.count())+"|"+str(nonzero)+"|"+str(int(qs.aggregate(v=Sum("qty"))["v"] or 0)))
' 2>/dev/null | tail -1) || fail "could not inspect live Anbaresh stock"
ANB_ROWS=$(printf '%s' "$ANB_STATE" | cut -d'|' -f1)
ANB_NONZERO=$(printf '%s' "$ANB_STATE" | cut -d'|' -f2)
ANB_QTY=$(printf '%s' "$ANB_STATE" | cut -d'|' -f3)
echo "ANBARESH STOCK ROWS BEFORE    = $ANB_ROWS"
echo "ANBARESH NONZERO ROWS BEFORE  = $ANB_NONZERO"
echo "ANBARESH STOCK QTY BEFORE     = $ANB_QTY"
[ "${ANB_NONZERO:-0}" = "0" ] || fail "Anbaresh has non-zero legacy stock rows. Nothing was migrated; review them before converting it to a sales-only channel."
[ "${ANB_QTY:-0}" = "0" ] || fail "Anbaresh stock total is non-zero. Nothing was migrated."

ANB_SALES=$(docker compose exec -T web python manage.py shell -c '
from core.models import SaleLine
print(SaleLine.objects.filter(product_size__product__brand__name="انبارش", quantity__gt=0).count())
' 2>/dev/null | tail -1) || fail "could not inspect live Anbaresh sales"
echo "ANBARESH POSITIVE SALE LINES BEFORE = $ANB_SALES"
[ "${ANB_SALES:-0}" = "0" ] || fail "Legacy Anbaresh sales already exist. Nothing was migrated; they must be reconciled before switching Anbaresh to Darma-backed inventory."

DARMA_BEFORE=$(docker compose exec -T web python manage.py shell -c '
from django.db.models import Sum
from core.models import Brand, StockBalance
b=Brand.objects.get(name="دارما")
print(int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0))
' 2>/dev/null | tail -1) || fail "could not read Darma stock before"
echo "DARMA QTY BEFORE = $DARMA_BEFORE"

step "4) CAPITAL BEFORE"
CAP_BEFORE=$(docker compose exec -T web python manage.py capital_audit_v9 | awk -F'= ' '/CAPITAL TOTAL/{gsub(/[[:space:]]/,"",$2);print $2}' | tail -1)
[ -n "$CAP_BEFORE" ] || fail "could not read capital before"
echo "CAPITAL BEFORE = $CAP_BEFORE"

step "5) BUILD"
docker compose build web || fail "web build failed"

step "6) MIGRATION DRIFT CHECK"
docker compose run --rm --entrypoint sh web -c 'python manage.py makemigrations --check --dry-run' || fail "model/migration drift detected"

step "7) MIGRATE"
docker compose run --rm --entrypoint sh web -c 'python manage.py migrate --noinput' || fail "migration failed"

step "8) V19 PREFLIGHT"
docker compose run --rm --entrypoint sh web -c '
python manage.py check &&
python manage.py check_excel_web &&
python manage.py check_v19_features &&
python manage.py check_capital_integrity_v14
' || fail "v19 preflight failed; live web was NOT replaced"

step "9) VERIFY DATA + CAPITAL AFTER MIGRATION"
DARMA_AFTER=$(docker compose run --rm --entrypoint sh web -c 'python manage.py shell -c "from django.db.models import Sum; from core.models import Brand,StockBalance; b=Brand.objects.get(name=\"دارما\"); print(int(StockBalance.objects.filter(brand=b).aggregate(v=Sum(\"qty\"))[\"v\"] or 0))"' | tail -1)
echo "DARMA QTY AFTER  = $DARMA_AFTER"
[ "$DARMA_BEFORE" = "$DARMA_AFTER" ] || fail "Darma stock changed during v19 metadata migration: before=$DARMA_BEFORE after=$DARMA_AFTER"

CAP_AFTER=$(docker compose run --rm --entrypoint sh web -c 'python manage.py capital_audit_v9' | awk -F'= ' '/CAPITAL TOTAL/{gsub(/[[:space:]]/,"",$2);print $2}' | tail -1)
[ -n "$CAP_AFTER" ] || fail "could not read capital after migration"
echo "CAPITAL AFTER  = $CAP_AFTER"
[ "$CAP_BEFORE" = "$CAP_AFTER" ] || fail "capital changed during v19 deployment: before=$CAP_BEFORE after=$CAP_AFTER. Live web was NOT replaced."

step "10) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy || fail "caddy restart failed"

step "11) FINAL LIVE CHECK"
docker compose exec -T web python manage.py check_v19_features || fail "live v19 check failed"
docker compose exec -T web python manage.py check_capital_integrity_v14 || fail "live capital integrity failed"
docker compose exec -T web python manage.py capital_audit_v9 || fail "live capital audit failed"

echo ""
echo "======================================"
echo "SUCCESS: SALE-ONLY ANBARESH + NOVANI + MATERIAL BRAND V19 DEPLOYED"
echo "Backup: $BACKUP"
echo "Capital stayed unchanged: $CAP_AFTER"
echo "Darma stock stayed unchanged during deployment: $DARMA_AFTER"
echo "Anbaresh has no independent inventory; future Anbaresh sales deduct Darma stock."
echo "Novani has one inventory table with 61,000 toman unit cost rows."
echo "Material reports now route finished output to the selected brand."
echo "======================================"
