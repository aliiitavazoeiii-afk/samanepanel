#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
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

step "2) FULL DATABASE BACKUP"
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="backups/before-darma-mordad31-v31-${STAMP}.sql"
PLAN="backups/plan-darma-mordad31-v31-${STAMP}.txt"
APPLYLOG="backups/apply-darma-mordad31-v31-${STAMP}.txt"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "database backup is empty"
echo "BACKUP = $BACKUP"

step "3) BUILD CURRENT IMAGE + CHECK"
docker compose build web || fail "web build failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift detected"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"

step "4) VERIFY SHAHRIVAR SALES ARE EMPTY"
POST_DAYS=$(docker compose run --rm --entrypoint python web manage.py shell -c 'from core.dateutils import parse_jalali_date; from core.models import SaleDay; s=parse_jalali_date("1405/06/01"); print(SaleDay.objects.filter(date__gte=s).count())' 2>/dev/null | tail -1)
[ "$POST_DAYS" = "0" ] || fail "there are still $POST_DAYS SaleDays from 1 Shahrivar onward; run V30B reset first"
echo "SaleDays from 1 Shahrivar onward = 0"

step "5) READ-ONLY 31 MORDAD PLAN"
docker compose run --rm --entrypoint python web manage.py reconcile_darma_mordad31_v31 2>&1 | tee "$PLAN" || fail "31 Mordad dry-run failed"
grep -q "TARGET COMBINED QTY  = 14864" "$PLAN" || fail "target quantity verification failed"
grep -q "DRY RUN ONLY" "$PLAN" || fail "dry-run did not finish safely"

step "6) APPLY AUTHORITATIVE 31 MORDAD BASELINE"
docker compose run --rm --entrypoint python web manage.py reconcile_darma_mordad31_v31 --apply 2>&1 | tee "$APPLYLOG" || fail "baseline apply failed; transaction should be rolled back"
grep -q "SUCCESS: DARMA INVENTORY SET TO 31 MORDAD V31" "$APPLYLOG" || fail "baseline did not report success"
grep -q "Darma combined total = 14864" "$APPLYLOG" || fail "final Darma total verification failed"
grep -q "M = 2109" "$APPLYLOG" || fail "M total verification failed"
grep -q "L = 4096" "$APPLYLOG" || fail "L total verification failed"
grep -q "XL = 3002" "$APPLYLOG" || fail "XL total verification failed"
grep -q "XXL = 4106" "$APPLYLOG" || fail "XXL total verification failed"
grep -q "3XL = 1143" "$APPLYLOG" || fail "3XL total verification failed"
grep -q "4XL = 408" "$APPLYLOG" || fail "4XL total verification failed"

step "7) FINAL CELL + TOTAL VERIFICATION"
docker compose run --rm --entrypoint python web manage.py reconcile_darma_mordad31_v31 > /tmp/mordad31-final.txt || fail "final baseline audit failed"
grep -q "CURRENT COMBINED QTY = 14864" /tmp/mordad31-final.txt || fail "final current quantity is not 14864"
grep -q "TOTAL DELTA          = +0" /tmp/mordad31-final.txt || fail "final cell matrix is not exact"

step "8) BRING SITE BACK"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy || fail "caddy restart failed"
sleep 4
docker compose exec -T web python manage.py check || fail "live Django check failed"

echo ""
echo "======================================"
echo "SUCCESS: DARMA 31 MORDAD BASELINE V31 DEPLOYED"
echo "Backup: $BACKUP"
echo "Plan: $PLAN"
echo "Apply log: $APPLYLOG"
echo "Darma total: 14,864"
echo "Darma accounting value @61,000: 906,704,000"
echo "Size totals: M=2109 | L=4096 | XL=3002 | XXL=4106 | 3XL=1143 | 4XL=408"
echo "KHORSHID preserved; HOME adjusted to make every combined color x size cell match the workbook."
echo "Next: import ONLY 1 Shahrivar and audit before importing day 2."
echo "======================================"
