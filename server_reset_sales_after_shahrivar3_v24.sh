#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

step "1) START DB + CHECK CURRENT LIVE WEB"
docker compose up -d db || fail "database start failed"
i=1
while [ "$i" -le 30 ]; do
  docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 && break
  [ "$i" -eq 30 ] && fail "PostgreSQL did not become ready"
  sleep 1
  i=$((i+1))
done
docker compose exec -T web python manage.py check >/dev/null || fail "current live web is not healthy"

step "2) FULL DATABASE BACKUP BEFORE DESTRUCTIVE RESET"
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="backups/before-sales-reset-after-shahrivar3-v24-${STAMP}.sql"
DIAG="backups/diagnostic-before-sales-reset-after-shahrivar3-v24-${STAMP}.txt"
APPLYLOG="backups/apply-sales-reset-after-shahrivar3-v24-${STAMP}.txt"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "database backup is empty"
echo "BACKUP = $BACKUP"

CAP_BEFORE=$(docker compose exec -T web python manage.py capital_audit_v9 | awk -F'= ' '/CAPITAL TOTAL/{gsub(/[[:space:]]/,"",$2);print $2}' | tail -1)
DARMA_BEFORE=$(docker compose exec -T web python manage.py shell -c 'from django.db.models import Sum; from core.models import Brand,StockBalance; b=Brand.objects.get(name="دارما"); print(int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0))' 2>/dev/null | tail -1)
echo "CAPITAL BEFORE = ${CAP_BEFORE:-unknown}"
echo "DARMA TOTAL BEFORE = ${DARMA_BEFORE:-unknown}"

step "3) BUILD LATEST IMAGE"
docker compose build web || fail "web build failed"

step "4) PREFLIGHT - NO MIGRATION DRIFT + DJANGO CHECK"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "model/migration drift detected"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"
docker compose run --rm --entrypoint python web manage.py check_v19_features || fail "v19 feature check failed"

step "5) READ-ONLY DIAGNOSTIC PLAN (SAVED BEFORE DELETE)"
docker compose run --rm --entrypoint python web manage.py reset_sales_after_shahrivar3_v24 2>&1 | tee "$DIAG" || fail "diagnostic plan failed"
[ -s "$DIAG" ] || fail "diagnostic output is empty"
echo "DIAGNOSTIC = $DIAG"

step "6) APPLY: KEEP 3 SHAHRIVAR, DELETE SALES AFTER IT, RESTORE EXACT DARMA REFERENCE"
docker compose run --rm --entrypoint python web manage.py reset_sales_after_shahrivar3_v24 --apply 2>&1 | tee "$APPLYLOG" || fail "reset transaction failed; database transaction should be rolled back"
[ -s "$APPLYLOG" ] || fail "apply output is empty"

grep -q "=== RESET COMPLETE ===" "$APPLYLOG" || fail "reset did not report completion"
grep -q "Darma HOME = 4585" "$APPLYLOG" || fail "HOME reference verification failed"
grep -q "Darma KHORSHID = 8890" "$APPLYLOG" || fail "KHORSHID reference verification failed"
grep -q "Darma TOTAL = 13475" "$APPLYLOG" || fail "TOTAL reference verification failed"
grep -q "cream 3XL = 77" "$APPLYLOG" || fail "cream 3XL reference verification failed"
grep -q "grey 4XL = 0" "$APPLYLOG" || fail "grey 4XL reference verification failed"
grep -q "red XXL = 0" "$APPLYLOG" || fail "red XXL reference verification failed"

step "7) MIRROR CORRECTED DARMA CATALOG TO ANBARESH + VERIFY CODE 06"
docker compose run --rm --entrypoint python web manage.py shell -c '
from core.anbaresh_catalog_v19 import sync_anbaresh_catalog
from core.brand_colors import norm
from core.models import Brand, ProductCode
sync_anbaresh_catalog()
for brand_name in ("دارما", "انبارش"):
    brand = Brand.objects.get(name=brand_name)
    p = ProductCode.objects.get(brand=brand, code="06")
    comps = list(p.composition.select_related("color"))
    names = [(x.color.name, int(x.qty or 0)) for x in comps]
    assert not any(norm(name) == norm("قرمز") for name, qty in names), f"{brand_name} 06 still contains red: {names}"
    assert any(norm(name) == norm("کرم") for name, qty in names), f"{brand_name} 06 has no cream: {names}"
    assert sum(qty for name, qty in names) == int(p.pack_qty or 0), f"{brand_name} 06 composition total mismatch: {names}, pack={p.pack_qty}"
    print(brand_name, "06", names)
' || fail "Darma/Anbaresh code 06 catalog verification failed"

step "8) RECREATE LIVE WEB ON LATEST CODE"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy || fail "caddy restart failed"
sleep 3
docker compose exec -T web python manage.py check || fail "final live Django check failed"

step "9) FINAL STATE"
CAP_AFTER=$(docker compose exec -T web python manage.py capital_audit_v9 | awk -F'= ' '/CAPITAL TOTAL/{gsub(/[[:space:]]/,"",$2);print $2}' | tail -1)
DARMA_AFTER=$(docker compose exec -T web python manage.py shell -c 'from django.db.models import Sum; from core.models import Brand,StockBalance; b=Brand.objects.get(name="دارما"); print(int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0))' 2>/dev/null | tail -1)
POST_DAYS=$(docker compose exec -T web python manage.py shell -c 'from core.dateutils import parse_jalali_date; from core.models import SaleDay; d=parse_jalali_date("1405/06/03"); print(SaleDay.objects.filter(date__gt=d).count())' 2>/dev/null | tail -1)
DAY3=$(docker compose exec -T web python manage.py shell -c 'from core.dateutils import parse_jalali_date; from core.models import SaleDay; d=parse_jalali_date("1405/06/03"); print(SaleDay.objects.filter(date=d).count())' 2>/dev/null | tail -1)
[ "$DARMA_AFTER" = "13475" ] || fail "final Darma total is $DARMA_AFTER, expected 13475"
[ "$POST_DAYS" = "0" ] || fail "there are still $POST_DAYS SaleDays after 3 Shahrivar"
[ "$DAY3" = "1" ] || fail "3 Shahrivar reference SaleDay was not preserved exactly once"

echo ""
echo "======================================"
echo "SUCCESS: SALES AFTER 3 SHAHRIVAR RESET TO REFERENCE V24"
echo "Backup: $BACKUP"
echo "Diagnostic before deletion: $DIAG"
echo "Apply log: $APPLYLOG"
echo "Capital before: ${CAP_BEFORE:-unknown}"
echo "Capital after: ${CAP_AFTER:-unknown}"
echo "Darma total before: ${DARMA_BEFORE:-unknown}"
echo "Darma total after: $DARMA_AFTER"
echo "3 Shahrivar preserved: YES"
echo "SaleDays after 3 Shahrivar: 0"
echo "Reference cells: cream 3XL=77 | grey 4XL=0 | red XXL=0"
echo "Darma/Anbaresh code 06: no red, cream present"
echo "Next: import 4 Shahrivar only, inspect inventory, then 5 Shahrivar, etc."
echo "======================================"