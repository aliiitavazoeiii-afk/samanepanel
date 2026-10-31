#!/bin/sh
set -eu
cd /opt/darma-general
export COMPOSE_IGNORE_ORPHANS=1

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

BASE=59e7a9c545e7831760e174868a431fa098fb2bca

snapshot_exec() {
  docker compose exec -T web python manage.py shell -c '
from django.db.models import Sum
from core.dia_gallery_v45 import dia_gallery_receivable_total
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import Brand,BusinessPayment,DigikalaSettlement,ExcelManualRow,ExcelManualSetting,InventoryMovement,RawMaterialStock,SaleLine,StockBalance,TakvinPurchase
from core.report_v5 import _raw_material_context

def norm(s):
    return str(s or "").replace(" ","").replace("ي","ی").replace("ك","ک")
def row_balance(needle):
    for r in ExcelManualRow.objects.filter(active=True,section=ExcelManualRow.ACCOUNTS).order_by("sort_order","id"):
        if needle in norm(r.title): return int(r.amount or 0)
    return 0
def bqty(name):
    b=Brand.objects.get(name=name)
    return int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0)

rows=ExcelManualRow.objects.filter(active=True)
accounts=sum(int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.ACCOUNTS).exclude(note__startswith="[system:self-spend-v62]"))
persons=sum(int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.PERSONS))
dia=int(dia_gallery_receivable_total())
assets=sum(int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.ASSETS))
finished=int(finished_inventory_value_v17())
raw=int(_raw_material_context()["materials_total"])
digi=int(digikala_receivable_total())
debt=int(ExcelManualSetting.objects.filter(key="takvin_debt").values_list("value",flat=True).first() or 0)
capital=accounts+persons+dia+assets+finished+raw+digi-debt
print("CAPITAL=%d" % capital)
print("MELLAT=%d" % row_balance("ملت"))
print("MOFID=%d" % row_balance("مفید"))
print("FINISHED=%d" % finished)
print("RAW=%d" % raw)
print("DIGI=%d" % digi)
print("DIA=%d" % dia)
print("TAKVIN_DEBT=%d" % debt)
print("DARMA_QTY=%d" % bqty("دارما"))
print("TAKVIN_QTY=%d" % bqty("تکوین"))
print("NOVANI_QTY=%d" % bqty("Novani"))
print("SALES=%d" % SaleLine.objects.count())
print("PAYMENTS=%d" % BusinessPayment.objects.count())
print("RECEIPTS=%d" % DigikalaSettlement.objects.count())
print("RAW_ROWS=%d" % RawMaterialStock.objects.count())
print("MOVEMENTS=%d" % InventoryMovement.objects.count())
print("TAKVIN_PURCHASES=%d" % TakvinPurchase.objects.count())
' 2>/dev/null | grep -E '^(CAPITAL|MELLAT|MOFID|FINISHED|RAW|DIGI|DIA|TAKVIN_DEBT|DARMA_QTY|TAKVIN_QTY|NOVANI_QTY|SALES|PAYMENTS|RECEIPTS|RAW_ROWS|MOVEMENTS|TAKVIN_PURCHASES)='
}

snapshot_run() {
  docker compose -f compose.yml -f compose.telegram.yml run --rm --entrypoint python web manage.py shell -c '
from django.db.models import Sum
from core.dia_gallery_v45 import dia_gallery_receivable_total
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import Brand,BusinessPayment,DigikalaSettlement,ExcelManualRow,ExcelManualSetting,InventoryMovement,RawMaterialStock,SaleLine,StockBalance,TakvinPurchase
from core.report_v5 import _raw_material_context

def norm(s):
    return str(s or "").replace(" ","").replace("ي","ی").replace("ك","ک")
def row_balance(needle):
    for r in ExcelManualRow.objects.filter(active=True,section=ExcelManualRow.ACCOUNTS).order_by("sort_order","id"):
        if needle in norm(r.title): return int(r.amount or 0)
    return 0
def bqty(name):
    b=Brand.objects.get(name=name)
    return int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0)

rows=ExcelManualRow.objects.filter(active=True)
accounts=sum(int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.ACCOUNTS).exclude(note__startswith="[system:self-spend-v62]"))
persons=sum(int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.PERSONS))
dia=int(dia_gallery_receivable_total())
assets=sum(int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.ASSETS))
finished=int(finished_inventory_value_v17())
raw=int(_raw_material_context()["materials_total"])
digi=int(digikala_receivable_total())
debt=int(ExcelManualSetting.objects.filter(key="takvin_debt").values_list("value",flat=True).first() or 0)
capital=accounts+persons+dia+assets+finished+raw+digi-debt
print("CAPITAL=%d" % capital)
print("MELLAT=%d" % row_balance("ملت"))
print("MOFID=%d" % row_balance("مفید"))
print("FINISHED=%d" % finished)
print("RAW=%d" % raw)
print("DIGI=%d" % digi)
print("DIA=%d" % dia)
print("TAKVIN_DEBT=%d" % debt)
print("DARMA_QTY=%d" % bqty("دارما"))
print("TAKVIN_QTY=%d" % bqty("تکوین"))
print("NOVANI_QTY=%d" % bqty("Novani"))
print("SALES=%d" % SaleLine.objects.count())
print("PAYMENTS=%d" % BusinessPayment.objects.count())
print("RECEIPTS=%d" % DigikalaSettlement.objects.count())
print("RAW_ROWS=%d" % RawMaterialStock.objects.count())
print("MOVEMENTS=%d" % InventoryMovement.objects.count())
print("TAKVIN_PURCHASES=%d" % TakvinPurchase.objects.count())
' 2>/dev/null | grep -E '^(CAPITAL|MELLAT|MOFID|FINISHED|RAW|DIGI|DIA|TAKVIN_DEBT|DARMA_QTY|TAKVIN_QTY|NOVANI_QTY|SALES|PAYMENTS|RECEIPTS|RAW_ROWS|MOVEMENTS|TAKVIN_PURCHASES)='
}

step "1) DATABASE BACKUP + PRE STATE"
docker compose config -q || fail "compose invalid"
docker compose up -d db web || fail "database/web start failed"
i=1
while [ "$i" -le 30 ]; do
  docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 && break
  [ "$i" -eq 30 ] && fail "PostgreSQL not ready"
  sleep 1
  i=$((i+1))
done
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="backups/before-digikala-zero-guard-v65-${STAMP}.sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "database backup is empty"
echo "BACKUP=$BACKUP"
PRE=$(snapshot_exec) || fail "could not capture pre state"
echo "$PRE"

step "2) VERIFY V65 SOURCE SCOPE + NO DIGIKALA WRITE CODE"
git cat-file -e "$BASE^{commit}" || fail "V65 base commit missing"
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    core/digikala_zero_guard_v65.py|core/telegram_inventory_alerts_v20.py|compose.telegram.yml|core/management/commands/check_digikala_zero_guard_v65.py|core/management/commands/check_cost_rules_takvin_purchase_v59.py|docs/PROJECT_CONTEXT/08_LIVE_STATE_AND_CHECKPOINTS.md|docs/PROJECT_CONTEXT/39_DIGIKALA_ZERO_GUARD_V65.md|docs/PROJECT_CONTEXT/README.md|UI_SAFETY_V65.md|server_digikala_zero_guard_v65.sh) ;;
    *) fail "unexpected V65 file changed: $f" ;;
  esac
done

git diff --quiet "$BASE"..HEAD --   core/digikala_client_v40.py core/digikala_shared_v44.py core/digikala_views_v40.py   core/models.py core/models_final.py core/migrations core/urls.py   core/report_v10.py core/final_services.py core/inventory_v20.py   core/business_tools_v62.py core/business_receipts_v64.py   core/daily_order_views_v60.py core/sale_entry_v60.py core/sale_price_v60.py   core/finance.py core/finance_excel_v9.py core/inventory_valuation_v17.py   core/material_report_v22.py core/returns_v37.py   || fail "protected business/integration source changed"

if grep -E '/activation|/seller-stock' core/digikala_zero_guard_v65.py >/dev/null 2>&1; then
  fail "V65 safe module contains a Digikala write endpoint marker"
fi
if grep -F '"POST"' core/digikala_zero_guard_v65.py >/dev/null 2>&1 \
  || grep -F '"PUT"' core/digikala_zero_guard_v65.py >/dev/null 2>&1 \
  || grep -F '"PATCH"' core/digikala_zero_guard_v65.py >/dev/null 2>&1 \
  || grep -F "'POST'" core/digikala_zero_guard_v65.py >/dev/null 2>&1 \
  || grep -F "'PUT'" core/digikala_zero_guard_v65.py >/dev/null 2>&1 \
  || grep -F "'PATCH'" core/digikala_zero_guard_v65.py >/dev/null 2>&1; then
  fail "V65 safe module contains a Digikala write method marker"
fi

step "3) BUILD WEB + BOT, MIGRATE CARRIED V64 IF NEEDED"
docker compose -f compose.yml -f compose.telegram.yml build web bot || fail "web/bot build failed"
docker compose -f compose.yml -f compose.telegram.yml run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift"
docker compose -f compose.yml -f compose.telegram.yml run --rm --entrypoint python web manage.py check || fail "Django check failed"
docker compose -f compose.yml -f compose.telegram.yml run --rm --entrypoint python web manage.py migrate --plan || fail "migration plan failed"
docker compose -f compose.yml -f compose.telegram.yml run --rm --entrypoint python web manage.py migrate --noinput || fail "migration failed"

POST_MIGRATE=$(snapshot_run) || fail "could not capture post-migration state"
echo "$POST_MIGRATE"
[ "$PRE" = "$POST_MIGRATE" ] || {
  echo "--- PRE ---"; echo "$PRE"
  echo "--- POST MIGRATE ---"; echo "$POST_MIGRATE"
  fail "migration changed protected business values"
}

step "4) EXISTING REGRESSIONS"
docker compose -f compose.yml -f compose.telegram.yml run --rm --entrypoint sh web -c 'python manage.py collectstatic --noinput >/dev/null && python manage.py check_daily_report_runtime_v48' || fail "V48 runtime regression failed"
docker compose -f compose.yml -f compose.telegram.yml run --rm --entrypoint python web manage.py check_darma_cost_rule_v55 || fail "V55 regression failed"
docker compose -f compose.yml -f compose.telegram.yml run --rm --entrypoint python web manage.py check_cost_rules_takvin_purchase_v59 || fail "V59 regression failed"
docker compose -f compose.yml -f compose.telegram.yml run --rm --entrypoint python web manage.py check_sale_price_elastic_multi_v60 || fail "V60 regression failed"
docker compose -f compose.yml -f compose.telegram.yml run --rm --entrypoint python web manage.py check_self_payee_account_v62 || fail "V62 regression failed"
docker compose -f compose.yml -f compose.telegram.yml run --rm --entrypoint python web manage.py check_payment_source_v63 || fail "V63 regression failed"
docker compose -f compose.yml -f compose.telegram.yml run --rm --entrypoint python web manage.py check_multi_receipts_v64 || fail "V64 regression failed"

step "5) V65 OFFLINE SAFE REGRESSION"
docker compose -f compose.yml -f compose.telegram.yml run --rm --entrypoint python bot manage.py check_digikala_zero_guard_v65 || fail "V65 offline regression failed"

step "6) TOKEN ISOLATION + LIVE READ-ONLY MAPPING"
docker compose -f compose.yml -f compose.telegram.yml run --rm --entrypoint sh bot -c '
  test -s /run/secrets/digikala/access_token.txt &&
  test -s /run/secrets/digikala/refresh_token.txt &&
  test ! -e /run/secrets/digikala/private_key.pem
' || fail "bot Digikala runtime token isolation failed"

MAP_PRE=$(snapshot_run) || fail "could not capture pre-map state"
docker compose -f compose.yml -f compose.telegram.yml run --rm --entrypoint python bot manage.py check_digikala_zero_guard_v65 --api-health --allow-network-failure || fail "V65 Digikala health command failed"
docker compose -f compose.yml -f compose.telegram.yml run --rm --entrypoint python bot manage.py check_digikala_zero_guard_v65 --live-map --allow-network-failure || fail "V65 live read-only mapping command failed"
MAP_POST=$(snapshot_run) || fail "could not capture post-map state"
[ "$MAP_PRE" = "$MAP_POST" ] || {
  echo "--- BEFORE LIVE MAP ---"; echo "$MAP_PRE"
  echo "--- AFTER LIVE MAP ---"; echo "$MAP_POST"
  fail "live Digikala mapping changed business values"
}

step "7) TELEGRAM PREFLIGHT"
docker compose -f compose.yml -f compose.telegram.yml run --rm --entrypoint python bot manage.py check_telegram_bot_v20 --network || fail "Telegram bot preflight failed"

step "8) RECREATE WEB + BOT"
PROJECTED=$(snapshot_run) || fail "could not capture projected state"
docker compose -f compose.yml -f compose.telegram.yml up -d --force-recreate web bot || fail "web/bot recreate failed"
docker compose restart caddy >/dev/null || fail "caddy restart failed"
sleep 8
docker compose -f compose.yml -f compose.telegram.yml exec -T web python manage.py check || fail "live Django check failed"
docker compose -f compose.yml -f compose.telegram.yml exec -T bot python manage.py check_digikala_zero_guard_v65 || fail "live V65 offline check failed"

LOGS=$(docker compose -f compose.yml -f compose.telegram.yml logs --tail=120 bot 2>&1 || true)
echo "$LOGS"
printf '%s
' "$LOGS" | grep -q 'V65 zero guard state initialized safely' || fail "bot did not initialize V65 zero state safely"

step "9) FINAL BUSINESS INVARIANTS"
FINAL=$(snapshot_exec) || fail "could not capture final state"
echo "$FINAL"
[ "$PROJECTED" = "$FINAL" ] || {
  echo "--- PROJECTED ---"; echo "$PROJECTED"
  echo "--- FINAL ---"; echo "$FINAL"
  fail "V65 deployment changed protected business values"
}

step "10) SUCCESS"
echo "SUCCESS: DIGIKALA ZERO GUARD V65 SAFE MODE DEPLOYED"
echo "Telegram zero transition check: every ~60 seconds"
echo "Digikala mapping: GET /open-api/v1/variants only"
echo "Digikala activation/write: LOCKED / ABSENT"
echo "Existing zero cells at first startup: seeded silently"
echo "Backup: $BACKUP"
