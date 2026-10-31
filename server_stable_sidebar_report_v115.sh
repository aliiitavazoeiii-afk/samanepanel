#!/bin/sh
set -eu
cd /opt/darma-general
fail(){ echo "FAILED: $1"; exit 1; }
export COMPOSE_IGNORE_ORPHANS=1
BASE=36af70949a4d3d846fd824ab5d74e1af42597947

echo "=== V115 BRANCH / DIFF ==="
test "$(git branch --show-current)" = "v115-stable-sidebar-report-dashboard" || fail "wrong branch"
git cat-file -e "$BASE^{commit}" || fail "V114 parent commit missing"
git diff --quiet || fail "local tracked changes exist; safeguard other UI work"
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
 case "$f" in
  templates/base.html|static/core/sidebar-v115.css|templates/core/report_excel_v3.html|templates/core/dashboard_excel_v89.html|core/report_v10.py|core/excel_dashboard_v89.py|core/management/commands/check_stable_sidebar_report_v115.py|docs/PROJECT_CONTEXT/64_STABLE_SIDEBAR_REPORT_V115.md|docs/PROJECT_CONTEXT/README.md|PROJECT_HANDOFF_CURRENT.md|server_stable_sidebar_report_v115.sh) ;;
  *) fail "unexpected file $f" ;;
 esac
done
git diff --quiet "$BASE"..HEAD -- core/models.py core/migrations core/material_report_v23.py core/material_report_v92.py core/finance_overview_v104.py core/calculator_v37.py core/inventory_v20.py core/sale_entry_v60.py || fail "protected logic changed"

echo "=== BACKUP / BUSINESS HASH ==="
docker compose config -q || fail "compose invalid"
docker compose ps --status running web | grep -q web || fail "live web not running"
test -f .env || fail ".env not found"
set -a; . ./.env; set +a
mkdir -p backups
BACKUP="backups/before-v115-sidebar-report-$(date +%Y%m%d-%H%M%S).sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "backup failed"
test -s "$BACKUP" || fail "backup empty"
HASH_CODE='from hashlib import sha256
from django.apps import apps
names=["StockBalance","InventoryMovement","RawMaterialStock","MaterialReportBlock","MaterialReportOutputApplied","MaterialReportOutputLocation","BusinessPayment","AccountEntry","SaleLine","ProductCode","ProductSize"]
for name in names:
 m=apps.get_model("core",name)
 cols=[f.attname for f in m._meta.concrete_fields]
 h=sha256()
 for row in m.objects.order_by("pk").values_list(*cols):
  h.update(repr(row).encode());h.update(b"\\n")
 print(name+"="+h.hexdigest())'
snapshot_live(){ docker compose exec -T web python manage.py shell -c "$HASH_CODE" 2>/dev/null | grep -E '^(StockBalance|InventoryMovement|RawMaterialStock|MaterialReportBlock|MaterialReportOutputApplied|MaterialReportOutputLocation|BusinessPayment|AccountEntry|SaleLine|ProductCode|ProductSize)='; }
snapshot_image(){ docker compose run --rm --entrypoint python web manage.py shell -c "$HASH_CODE" 2>/dev/null | grep -E '^(StockBalance|InventoryMovement|RawMaterialStock|MaterialReportBlock|MaterialReportOutputApplied|MaterialReportOutputLocation|BusinessPayment|AccountEntry|SaleLine|ProductCode|ProductSize)='; }
PRE=$(snapshot_live) || fail "PRE hash error"
echo "$PRE"

echo "=== BUILD / READ ONLY REGRESSION ==="
docker compose build web || fail "build failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "unexpected migration"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check"
docker compose run --rm --entrypoint python web manage.py check_stable_sidebar_report_v115 || fail "V115 regression failed"
docker compose run --rm --entrypoint python web manage.py check_final_baseline_v108 || fail "V108 regression failed"
docker compose run --rm --entrypoint python web manage.py check_production_unit_cost_v113 || fail "V113 calculator regression failed"
PROJECTED=$(snapshot_image) || fail "PROJECTED hash error"
test "$PRE" = "$PROJECTED" || { echo "$PROJECTED"; fail "business hash changed before deploy"; }

echo "=== LIVE RECREATE ==="
docker compose up -d --no-deps --force-recreate web || fail "web recreate failed"
sleep 6
docker compose exec -T web python manage.py check_stable_sidebar_report_v115 || fail "live V115 check failed"
docker compose exec -T web python manage.py check_production_unit_cost_v113 || fail "live V113 check failed"
FINAL=$(snapshot_live) || fail "FINAL hash error"
test "$PRE" = "$FINAL" || { echo "$FINAL"; fail "business hash changed after deploy"; }
echo "SUCCESS: STABLE SIDEBAR + COMPREHENSIVE REPORT V115 DEPLOYED"
echo "PRE = PROJECTED = FINAL"
echo "BACKUP=$BACKUP"
