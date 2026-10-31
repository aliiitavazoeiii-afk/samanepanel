#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

step "1) START DB + BACKUP"
docker compose up -d db || fail "database start failed"
i=1
while [ "$i" -le 30 ]; do
  docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 && break
  [ "$i" -eq 30 ] && fail "PostgreSQL did not become ready"
  sleep 1; i=$((i+1))
done
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="backups/before-darma-day3-physical-v32-${STAMP}.sql"
PLAN="backups/plan-darma-day3-physical-v32-${STAMP}.txt"
APPLYLOG="backups/apply-darma-day3-physical-v32-${STAMP}.txt"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "backup is empty"
echo "BACKUP = $BACKUP"

step "2) BUILD LATEST WEB IMAGE + CHECK"
docker compose build web || fail "web build failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift detected"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"

step "3) DRY RUN EXACT DAY-3 PHYSICAL RECONCILE"
docker compose run --rm --entrypoint python web manage.py reconcile_darma_day3_physical_v32 2>&1 | tee "$PLAN" || fail "dry-run failed"
grep -q "DRY RUN ONLY" "$PLAN" || fail "dry-run did not finish"
grep -q "Target HOME/KH/TOTAL  = 4,585 / 8,890 / 13,475" "$PLAN" || fail "target totals do not match uploaded files"
grep -q "Khorshid cream XXL=400; red XXL=0" "$PLAN" || fail "critical physical cells check missing"

step "4) APPLY EXACT HOME + KHORSHID PHYSICAL FILES"
docker compose run --rm --entrypoint python web manage.py reconcile_darma_day3_physical_v32 --apply 2>&1 | tee "$APPLYLOG" || fail "apply failed; transaction rolled back"
grep -q "SUCCESS: DARMA HOME + KHORSHID SET EXACTLY TO DAY-3 PHYSICAL FILES V32" "$APPLYLOG" || fail "success marker missing"
grep -q "FINAL HOME = 4585" "$APPLYLOG" || fail "HOME total verification failed"
grep -q "FINAL KHORSHID = 8890" "$APPLYLOG" || fail "KHORSHID total verification failed"
grep -q "FINAL TOTAL = 13475" "$APPLYLOG" || fail "combined total verification failed"

step "5) BRING/REFRESH SITE"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy || fail "caddy restart failed"
sleep 3
docker compose exec -T web python manage.py check || fail "live Django check failed"

step "6) FINAL KEY-CELL VERIFICATION"
docker compose exec -T web python manage.py shell -c '
from django.db.models import Sum
from core.brand_colors import norm
from core.models import Brand,Color,Size,StockBalance,StockLocation
b=Brand.objects.get(name="دارما")
locs={x.key:x for x in StockLocation.objects.filter(key__in=["home","khorshid"])}
sizes={x.name:x for x in Size.objects.all()}
def color(name):
  matches=[x for x in Color.objects.filter(stockbalance__brand=b).distinct() if norm(x.name)==norm(name)]
  assert len(matches)==1,(name,[x.name for x in matches]); return matches[0]
def q(loc,c,s):
  return int(StockBalance.objects.filter(brand=b,location=locs[loc],color=color(c),size=sizes[s]).aggregate(v=Sum("qty"))["v"] or 0)
assert q("khorshid","کرم","XXL")==400
assert q("khorshid","قرمز","XXL")==0
assert q("home","کرم","3XL")==77
assert q("home","طوسی","4XL")==0
home=int(StockBalance.objects.filter(brand=b,location=locs["home"]).aggregate(v=Sum("qty"))["v"] or 0)
kh=int(StockBalance.objects.filter(brand=b,location=locs["khorshid"]).aggregate(v=Sum("qty"))["v"] or 0)
assert (home,kh,home+kh)==(4585,8890,13475),(home,kh,home+kh)
print("FINAL PHYSICAL STOCK VERIFIED: HOME=4585 KHORSHID=8890 TOTAL=13475")
' || fail "final physical stock verification failed"

echo ""
echo "======================================"
echo "SUCCESS: DARMA DAY-3 PHYSICAL STOCK V32"
echo "Backup: $BACKUP"
echo "Dry-run: $PLAN"
echo "Apply log: $APPLYLOG"
echo "HOME = 4,585"
echo "KHORSHID = 8,890"
echo "TOTAL = 13,475"
echo "Sales through 3 Shahrivar were preserved; no sale history was rewritten."
echo "Check CAPITAL BEFORE / AFTER / DELTA in the apply log."
echo "======================================"
