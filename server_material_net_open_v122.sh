#!/bin/sh
set -eu
cd /opt/darma-general
fail(){ echo "FAILED: $1"; exit 1; }
export COMPOSE_IGNORE_ORPHANS=1
BASE=92a159b35192665ba26a526f3bd8eec6189db931

echo "=== V122 NET MATERIAL DELIVERIES + OPEN MONTH CARRYOVER ==="
test "$(git branch --show-current)" = "v122-material-net-current-open" || fail "wrong branch"
git cat-file -e "$BASE^{commit}" || fail "V121 parent commit missing"
git diff --quiet -- . ':(exclude)Caddyfile' || fail "other tracked local changes exist"
git diff --cached --quiet -- . ':(exclude)Caddyfile' || fail "other staged local changes exist"
git diff --quiet "$BASE"..HEAD -- Caddyfile || fail "V122 must not change Caddyfile"
test -f Caddyfile || fail "Caddyfile missing"
CADDY_BEFORE=$(sha256sum Caddyfile | awk '{print $1}')
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    .github/workflows/check-material-v122.yml|PROJECT_HANDOFF_CURRENT.md|core/management/commands/check_material_net_v122.py|core/management/commands/check_material_summary_box_grid_v110.py|core/material_report_v92.py|docs/PROJECT_CONTEXT/70_MATERIAL_NET_CARRYOVER_V122.md|docs/PROJECT_CONTEXT/README.md|server_material_net_open_v122.sh|templates/core/material_report_v92.html) ;;
    *) fail "unexpected V122 file: $f" ;;
  esac
done
# Production ERP data, finance, materials synchronization, stock and all
# existing HTML sidebar/business templates MUST be identical to V121.
git diff --quiet "$BASE"..HEAD -- \
    core/models.py core/migrations core/material_report_v23.py core/material_report_v20.py \
    core/material_receipt_sync.py core/material_flow.py core/wholesale_logic_v119.py \
    core/business_tools_v14.py core/capital_history_v87.py core/inventory_v20.py \
    core/finance_overview_v104.py core/sale_entry_v60.py templates/base.html \
    templates/core/material_report_v36.html || fail "protected data/ledger/template changed"

echo "=== PRODUCTION PRECHECK / BACKUP ==="
docker compose config -q || fail "compose config error"
docker compose ps --status running web | grep -q web || fail "live web container not running"
test -s .env || fail ".env missing"
set -a; . ./.env; set +a
mkdir -p backups
BACKUP="backups/before-v122-material-net-$(date +%Y%m%d-%H%M%S).sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
test -s "$BACKUP" || fail "backup is empty"
echo "BACKUP=$BACKUP"

HASH_CODE='from hashlib import sha256
from django.apps import apps
names=["StockBalance","InventoryMovement","RawMaterialStock","MaterialReportBlock","MaterialReportOutputApplied","MaterialReportOutputLocation","BusinessPayment","AccountEntry","SaleLine","ProductCode","ProductSize","ExcelManualRow"]
for name in names:
 m=apps.get_model("core",name)
 cols=[f.attname for f in m._meta.concrete_fields]
 h=sha256()
 for row in m.objects.order_by("pk").values_list(*cols):
  h.update(repr(row).encode());h.update(b"\\n")
 print(name+"="+h.hexdigest())'
snapshot_live(){ docker compose exec -T web python manage.py shell -c "$HASH_CODE" 2>/dev/null | grep -E '^(StockBalance|InventoryMovement|RawMaterialStock|MaterialReportBlock|MaterialReportOutputApplied|MaterialReportOutputLocation|BusinessPayment|AccountEntry|SaleLine|ProductCode|ProductSize|ExcelManualRow)='; }
snapshot_image(){ docker compose run --rm --entrypoint python web manage.py shell -c "$HASH_CODE" 2>/dev/null | grep -E '^(StockBalance|InventoryMovement|RawMaterialStock|MaterialReportBlock|MaterialReportOutputApplied|MaterialReportOutputLocation|BusinessPayment|AccountEntry|SaleLine|ProductCode|ProductSize|ExcelManualRow)='; }
PRE=$(snapshot_live) || fail "PRE snapshot failed"
echo "$PRE"

echo "=== READ-ONLY BUILD AND TESTS ==="
docker compose build web || fail "web build failed"
docker compose run --rm --entrypoint python web -m compileall -q core/material_report_v92.py core/management/commands/check_material_net_v122.py core/management/commands/check_material_summary_box_grid_v110.py || fail "Python syntax check failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "unexpected database schema migration"
docker compose run --rm --entrypoint python web manage.py check || fail "Django project check failed"
docker compose run --rm --entrypoint python web manage.py showmigrations core | grep -Eq '\[X\] 0020_novani_wholesale' || fail "V119 wholesale migration not applied; deploy earlier approved version first"
# V121 account repair must be reviewed/finished separately. Never change it
# as a side effect of a materials report-only release.
REPAIR_AUDIT=$(docker compose run --rm --entrypoint python web manage.py repair_pedram_wholesale_v121) || fail "financial state preview failed"
echo "$REPAIR_AUDIT"
printf '%s\n' "$REPAIR_AUDIT" | grep -qx 'PEDRAM_REPAIR_GROSS=0' || fail "V121 Pedram repair still pending; run approved V121 recovery before V122"

docker compose run --rm --entrypoint python web manage.py check_material_net_v122 || fail "V122 net/month+carryover verification failed"
docker compose run --rm --entrypoint python web manage.py check_material_summary_box_grid_v110 || fail "V110+V118 UI check failed"
docker compose run --rm --entrypoint python web manage.py check_fabric_roll_count_v116 || fail "V118 fabric roll/weight check failed"
docker compose run --rm --entrypoint python web manage.py check_ui_rail_report_v116 || fail "sidebar regression failed"
docker compose run --rm --entrypoint python web manage.py check_wholesale_v119 || fail "wholesale accounting regression failed"
docker compose run --rm --entrypoint python web manage.py check_production_unit_cost_v113 || fail "calculator regression failed"
PROJECTED=$(snapshot_image) || fail "PROJECTED snapshot failed"
test "$PRE" = "$PROJECTED" || { echo "$PROJECTED"; fail "business data changed during image preflight"; }

test "$(sha256sum Caddyfile | awk '{print $1}')" = "$CADDY_BEFORE" || fail "Caddyfile changed"
echo "=== RECREATE WEB ONLY ==="
docker compose up -d --no-deps --force-recreate web || fail "web restart failed"
sleep 6
docker compose exec -T web python manage.py check_material_net_v122 || fail "live V122 verification failed"
docker compose exec -T web python manage.py check_material_summary_box_grid_v110 || fail "live V110 report regression failed"
docker compose exec -T web python manage.py check_fabric_roll_count_v116 || fail "live V118 fabric regression failed"
docker compose exec -T web python manage.py check_wholesale_v119 || fail "live V119 finance regression failed"
FINAL=$(snapshot_live) || fail "FINAL snapshot failed"
test "$PRE" = "$FINAL" || { echo "$FINAL"; fail "business data changed during deployment"; }
test "$(sha256sum Caddyfile | awk '{print $1}')" = "$CADDY_BEFORE" || fail "Caddyfile changed during deployment"
echo "SUCCESS: V122 NET MATERIAL DELIVERY + OPEN MONTH CARRYOVER DEPLOYED"
echo "PRE = PROJECTED = FINAL"
echo "BACKUP=$BACKUP"
