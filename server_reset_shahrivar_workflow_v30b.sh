#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

step "1) CLEAN STUCK ONE-OFF WEB-RUN CONTAINERS + START DATABASE"
RUN_IDS=$(docker ps -aq --filter 'name=darma-general-web-run-' || true)
if [ -n "$RUN_IDS" ]; then
  echo "$RUN_IDS" | xargs -r docker rm -f >/dev/null 2>&1 || true
  echo "stuck one-off web-run containers removed"
else
  echo "no stuck web-run container"
fi

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
BACKUP="backups/before-shahrivar-workflow-reset-v30b-${STAMP}.sql"
PLAN="backups/plan-shahrivar-workflow-reset-v30b-${STAMP}.txt"
APPLYLOG="backups/apply-shahrivar-workflow-reset-v30b-${STAMP}.txt"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "database backup is empty"
echo "BACKUP = $BACKUP"

step "3) BUILD CURRENT MAIN IMAGE"
docker compose build web || fail "web image build failed"

step "4) PREFLIGHT"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift detected"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"

step "5) READ-ONLY RESET PLAN"
docker compose run --rm --entrypoint python web manage.py reset_shahrivar_workflow_v30b 2>&1 | tee "$PLAN" || fail "reset plan failed"
grep -q "READ ONLY" "$PLAN" || fail "plan did not finish as read-only"
echo "PLAN = $PLAN"

step "6) APPLY ATOMIC V30B RESET"
docker compose run --rm --entrypoint python web manage.py reset_shahrivar_workflow_v30b --apply 2>&1 | tee "$APPLYLOG" || fail "reset failed; transaction should be rolled back"
grep -q "=== RESET COMPLETE V30B ===" "$APPLYLOG" || fail "reset did not report completion"
grep -q "SaleDays from 1 Shahrivar onward = 0" "$APPLYLOG" || fail "SaleDay verification failed"
grep -q "Payment rows from 1 Shahrivar onward = 0" "$APPLYLOG" || fail "payment verification failed"
grep -q "Digikala receipts from 1 Shahrivar onward = 0" "$APPLYLOG" || fail "receipt verification failed"

step "7) FINAL DATABASE VERIFICATION"
docker compose run --rm --entrypoint python web manage.py shell -c '
from core.dateutils import parse_jalali_date
from core.models import SaleDay, SaleLine, BusinessPayment, DigikalaSettlement
s=parse_jalali_date("1405/06/01")
assert SaleDay.objects.filter(date__gte=s).count() == 0
assert SaleLine.objects.filter(day__date__gte=s).count() == 0
assert BusinessPayment.objects.filter(date__gte=s).count() == 0
assert DigikalaSettlement.objects.filter(date__gte=s).count() == 0
print("workflow rows after boundary = 0")
' || fail "final DB verification failed"

step "8) BRING SITE BACK"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy || fail "caddy restart failed"
sleep 4
docker compose exec -T web python manage.py check || fail "live Django check failed"

echo ""
echo "======================================"
echo "SUCCESS: SHAHRIVAR WORKFLOW RESET V30B"
echo "Backup: $BACKUP"
echo "Plan: $PLAN"
echo "Apply log: $APPLYLOG"
echo "All SaleDays/SaleLines from 1 Shahrivar onward: REVERSED + REMOVED"
echo "All outgoing payment rows from 1 Shahrivar onward: REMOVED; CURRENT EFFECTS REBASED/PRESERVED"
echo "All Digikala receipts from 1 Shahrivar onward: REVERSED + REMOVED"
echo "Raw-material quantities/values: PRESERVED"
echo "31 Mordad and earlier: PRESERVED"
echo "Physical/manual inventory adjustments: PRESERVED"
echo "IMPORTANT: DO NOT RE-ENTER OLD OUTGOING PAYMENTS."
echo "Next: enter ONLY sales for 1, 2, 3 Shahrivar; then restore/check exact physical day-3 inventory baseline."
echo "======================================"
