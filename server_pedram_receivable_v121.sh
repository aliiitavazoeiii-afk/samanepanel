#!/bin/sh
set -eu
cd /opt/darma-general
fail(){ echo "FAILED: $1"; exit 1; }
export COMPOSE_IGNORE_ORPHANS=1
BASE=f6424fe0be725833e8f54247c5cc45c0d40b3634

echo "=== V121 PEDRAM RECEIVABLE CORRECTION AND NUMBER FORMATTING ==="
test "$(git branch --show-current)" = "v121-pedram-receivable-fix" || fail "wrong branch"
git cat-file -e "$BASE^{commit}" || fail "V115 parent commit missing"
# Keep locally customized domain routing intact. Caddyfile is an
# explicitly permitted, uncommitted production override ONLY; everything
# else must remain clean. Never stash/reset/checkout the Caddyfile.
git diff --quiet -- . ':(exclude)Caddyfile' || fail "other tracked local changes exist"
git diff --cached --quiet -- . ':(exclude)Caddyfile' || fail "other staged local changes exist"
git diff --quiet "$BASE"..HEAD -- Caddyfile || fail "branch unexpectedly modifies Caddyfile"
test -f Caddyfile || fail "existing Caddyfile missing"
CADDY_BEFORE=$(sha256sum Caddyfile | awk '{print $1}')
echo "Caddyfile local override retained (sha256=$CADDY_BEFORE)"
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
 case "$f" in
  PROJECT_HANDOFF_CURRENT.md|core/management/commands/check_fabric_roll_count_v116.py|core/management/commands/check_material_summary_box_grid_v110.py|core/management/commands/check_ui_rail_report_v116.py|core/management/commands/check_wholesale_v119.py|core/management/commands/repair_pedram_wholesale_v121.py|core/material_report_v92.py|core/migrations/0020_novani_wholesale.py|core/models.py|core/report_v10.py|core/test_wholesale_v119.py|core/urls.py|core/wholesale_export_v119.py|core/wholesale_logic_v119.py|core/wholesale_models_v119.py|core/wholesale_v119.py|docs/PROJECT_CONTEXT/65_FABRIC_ROLL_COUNT_V116.md|docs/PROJECT_CONTEXT/65_SMOOTH_RAIL_REPORT_PRIORITY_V116.md|docs/PROJECT_CONTEXT/66_UNAPPLIED_FABRIC_WEIGHT_V118.md|docs/PROJECT_CONTEXT/67_NOVANI_WHOLESALE_V119.md|docs/PROJECT_CONTEXT/68_NOVANI_COLOR_SIZE_MATRIX_V120.md|docs/PROJECT_CONTEXT/69_PEDRAM_RECEIVABLE_V121.md|docs/PROJECT_CONTEXT/README.md|requirements.txt|server_fabric_roll_count_v116.sh|server_novani_color_matrix_v120.sh|server_novani_wholesale_v119.sh|server_pedram_receivable_v121.sh|server_unapplied_fabric_v118.sh|server_unified_ui_fabric_v117.sh|static/core/sidebar-v116.css|templates/base.html|templates/core/dashboard_excel_v89.html|templates/core/digikala_center_v43.html|templates/core/finance_center_v97.html|templates/core/inventory_center_v96.html|templates/core/material_report_v92.html|templates/core/pricing_monitor_v89.html|templates/core/report_excel_v3.html|templates/core/report_excel_v36.html|templates/core/settings_home.html|templates/core/wholesale_v119.html) ;;
  *) fail "unexpected V121 file: $f" ;;
 esac
done
git diff --quiet "$BASE"..HEAD -- core/models_final.py core/material_report_v23.py core/finance_overview_v104.py core/calculator_v37.py core/inventory_v20.py core/sale_entry_v60.py core/capital_history_v87.py core/material_flow.py || fail "protected legacy logic changed"
# The old models.py is byte-identical except for one explicit V119 registration.
python3 - "$BASE" <<'PY'
import pathlib, subprocess, sys
original=subprocess.check_output(["git","show",f"{sys.argv[1]}:core/models.py"])
current=pathlib.Path("core/models.py").read_bytes()
append=b"\n\n# Registered after existing core financial models: wholesale uses distinct ledgers.\nfrom .wholesale_models_v119 import WholesaleCustomer, WholesaleInvoice, WholesaleInvoiceLine, WholesaleReceipt  # noqa: E402,F401\n"
if current != original + append:
    raise SystemExit("FAILED: existing core/models.py changed outside V119 import")
PY
MIGRATION_CHANGED=$(git diff --name-only "$BASE"..HEAD -- core/migrations)
test "$MIGRATION_CHANGED" = "core/migrations/0020_novani_wholesale.py" || fail "unexpected migrations changed"

echo "=== BACKUP / BUSINESS HASH ==="
docker compose config -q || fail "compose invalid"
docker compose ps --status running web | grep -q web || fail "live web not running"
test -f .env || fail ".env not found"
set -a; . ./.env; set +a
mkdir -p backups
BACKUP="backups/before-v121-pedram-receivable-$(date +%Y%m%d-%H%M%S).sql"
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
docker compose run --rm --entrypoint python web -m compileall -q core/wholesale_models_v119.py core/wholesale_logic_v119.py core/wholesale_v119.py core/wholesale_export_v119.py core/migrations/0020_novani_wholesale.py core/management/commands/check_wholesale_v119.py core/management/commands/repair_pedram_wholesale_v121.py core/test_wholesale_v119.py || fail "new wholesale Python source syntax check failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "unexpected migration"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check"
echo "=== V119 MIGRATION SAFETY ==="
docker compose run --rm --entrypoint python web manage.py showmigrations core | grep -Eq '\[X\] 0019_material_output_location' || fail "V119 expects existing core migration 0019 already installed"
docker compose run --rm --entrypoint python web manage.py migrate core 0020_novani_wholesale --noinput || fail "V119 migration failed"
# V121: existing Pedram V119/V120 invoices were incorrectly MINUS gross.
# Never reapply the invoice or inventory sale; only repair a verifiably old
# settlement marker and the signed shared tailor person balance.
echo "=== V121 PEDRAM ACCOUNT REPAIR PREVIEW (READ ONLY) ==="
REPAIR_DRY=$(docker compose run --rm --entrypoint python web manage.py repair_pedram_wholesale_v121) || fail "Pedram reconciliation dry run failed"
echo "$REPAIR_DRY"
REPAIR_GROSS=$(printf '%s\n' "$REPAIR_DRY" | awk -F= '$1=="PEDRAM_REPAIR_GROSS"{print $2}')
TAILOR_BEFORE=$(printf '%s\n' "$REPAIR_DRY" | awk -F= '$1=="PEDRAM_TAILOR_BEFORE"{print $2}')
case "$REPAIR_GROSS" in
  0|144384000) ;;
  *) fail "Unexpected legacy Pedram gross $REPAIR_GROSS; review invoice IDs before any repair" ;;
esac
case "$TAILOR_BEFORE" in
  ''|*[!0-9-]*) fail "missing Pedram tailor account balance" ;;
esac

echo "=== V121 ONE-TIME EXACT REPAIR ==="
REPAIR_APPLIED=$(docker compose run --rm --entrypoint python web manage.py repair_pedram_wholesale_v121 --apply --expected-gross "$REPAIR_GROSS") || fail "Pedram repair failed (transaction rolled back)"
echo "$REPAIR_APPLIED"
TAILOR_AFTER=$(printf '%s\n' "$REPAIR_APPLIED" | awk -F= '$1=="PEDRAM_TAILOR_AFTER"{print $2}')
test "$TAILOR_AFTER" = "$((TAILOR_BEFORE + 2 * REPAIR_GROSS))" || fail "tailor balance not increased by expected 2x old invoice total"
REPAIR_RECHECK=$(docker compose run --rm --entrypoint python web manage.py repair_pedram_wholesale_v121) || fail "recheck failed"
printf '%s\n' "$REPAIR_RECHECK" | grep -qx 'PEDRAM_REPAIR_GROSS=0' || fail "old Pedram mis-signed invoices still pending"
echo "PEDRAM_CORRECTED_GROSS=$REPAIR_GROSS"
echo "PEDRAM_SIGNED_TAILOR_BEFORE=$TAILOR_BEFORE"
echo "PEDRAM_SIGNED_TAILOR_AFTER=$TAILOR_AFTER"
echo "PEDRAM_FINANCIAL_EFFECT=positive correction only; no duplicate sale or stock writes"
docker compose run --rm --entrypoint python web manage.py check_wholesale_v119 || fail "V119 wholesale ledger check"

docker compose run --rm --entrypoint python web manage.py check_ui_rail_report_v116 || fail "V116 UI regression failed"
docker compose run --rm --entrypoint python web manage.py check_material_summary_box_grid_v110 || fail "V110+V118 material summary regression failed"
docker compose run --rm --entrypoint python web manage.py check_fabric_roll_count_v116 || fail "V118 roll/weight audit failed"
docker compose run --rm --entrypoint python web manage.py check_final_baseline_v108 || fail "V108 regression failed"
docker compose run --rm --entrypoint python web manage.py check_production_unit_cost_v113 || fail "V113 calculator regression failed"
PROJECTED=$(snapshot_image) || fail "PROJECTED hash error"
test "$PRE" = "$PROJECTED" || { echo "$PROJECTED"; fail "business hash changed before deploy"; }

test "$(sha256sum Caddyfile | awk '{print $1}')" = "$CADDY_BEFORE" || fail "Caddyfile changed before deploy"
echo "=== LIVE RECREATE ==="
docker compose up -d --no-deps --force-recreate web || fail "web recreate failed"
sleep 6
docker compose exec -T web python manage.py check_ui_rail_report_v116 || fail "live V116 UI check failed"
docker compose exec -T web python manage.py check_material_summary_box_grid_v110 || fail "live V110+V116 regression failed"
docker compose exec -T web python manage.py check_fabric_roll_count_v116 || fail "live V118 audit failed"
docker compose exec -T web python manage.py check_production_unit_cost_v113 || fail "live V113 check failed"
docker compose exec -T web python manage.py check_wholesale_v119 || fail "live V119 wholesale audit failed"
FINAL=$(snapshot_live) || fail "FINAL hash error"
test "$PRE" = "$FINAL" || { echo "$FINAL"; fail "business hash changed after deploy"; }
test "$(sha256sum Caddyfile | awk '{print $1}')" = "$CADDY_BEFORE" || fail "Caddyfile was changed during deploy"
echo "Caddyfile sha256 unchanged: $CADDY_BEFORE"
echo "SUCCESS: V121 PEDRAM RECEIVABLE CORRECTED"
echo "PRE = PROJECTED = FINAL"
echo "BACKUP=$BACKUP"
