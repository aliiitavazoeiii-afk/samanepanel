#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

BASE_MARKER='V47 BLACK RED UI RUNTIME OVERLAY'
INV_MARKER='V47 PROFESSIONAL INVENTORY TABLES'
OVERLAY=/tmp/darma-inventory-ui-v47.css

snapshot_economic() {
  docker compose exec -T web python manage.py shell -c '
from django.db.models import Sum
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import AccountEntry, Brand, ExcelManualRow, ExcelManualSetting, SaleLine, StockBalance
from core.report_v5 import _raw_material_context

def bqty(name):
    b=Brand.objects.get(name=name)
    return int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0)
try:
    from core.dia_gallery_v45 import dia_gallery_receivable_total
    dia=int(dia_gallery_receivable_total())
except Exception:
    dia=0
rows=ExcelManualRow.objects.filter(active=True)
accounts=sum(int(x.amount or 0) for x in rows.filter(section__in=[ExcelManualRow.ACCOUNTS,ExcelManualRow.PERSONS])) + dia
assets=sum(int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.ASSETS))
finished=int(finished_inventory_value_v17()); raw=int(_raw_material_context()["materials_total"]); digi=int(digikala_receivable_total())
debt=int(ExcelManualSetting.objects.filter(key="takvin_debt").values_list("value",flat=True).first() or 0)
print(f"CAPITAL={accounts+assets+finished+raw+digi-debt}")
print(f"FINISHED={finished}"); print(f"RAW={raw}"); print(f"DIGI={digi}"); print(f"DIA={dia}")
print(f"DARMA={bqty(chr(1583)+chr(1575)+chr(1585)+chr(1605)+chr(1575))}")
print(f"TAKVIN={bqty(chr(1578)+chr(1705)+chr(1608)+chr(1740)+chr(1606))}")
print(f"NOVANI={bqty(chr(78)+chr(111)+chr(118)+chr(97)+chr(110)+chr(105))}")
print(f"SALES={SaleLine.objects.count()}"); print(f"ACCOUNT_ENTRIES={AccountEntry.objects.count()}")
' 2>/dev/null | grep -E '^(CAPITAL|FINISHED|RAW|DIGI|DIA|DARMA|TAKVIN|NOVANI|SALES|ACCOUNT_ENTRIES)='
}

step "1) DEPLOY BASE BLACK / RED V47 + CREATE FRESH BACKUP"
bash server_black_red_ui_v47.sh || fail "base V47 deploy failed"

docker compose exec -T web sh -c "grep -q '$BASE_MARKER' /app/static/core/ui-polish.css" || fail "base V47 marker missing"

step "2) VERIFY INVENTORY TEMPLATE + CAPTURE BASELINE"
docker compose exec -T web python - <<'PY' || fail "inventory template preflight failed"
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings")
import django; django.setup()
from django.template.loader import get_template
get_template("core/inventory_v19.html")
print("INVENTORY TEMPLATE OK")
PY
LIVE=$(snapshot_economic) || fail "could not capture business snapshot"
echo "$LIVE"

STAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p backups
CSS_BACKUP="backups/v47-before-professional-inventory-${STAMP}.css"
docker compose exec -T web cat /app/static/core/ui-polish.css > "$CSS_BACKUP" || fail "live CSS backup failed"
[ -s "$CSS_BACKUP" ] || fail "live CSS backup empty"
echo "CSS_BACKUP=$CSS_BACKUP"

cat > "$OVERLAY" <<'CSS'

/* ========================================================================== */
/* V47 PROFESSIONAL INVENTORY TABLES — PRESENTATION ONLY                      */
/* ========================================================================== */

/* Inventory page shell and add-model box */
.inventory-add-box{
  position:relative!important;
  background:linear-gradient(145deg,rgba(28,22,25,.86),rgba(9,9,10,.82))!important;
  border:1px solid rgba(255,255,255,.09)!important;
  border-radius:18px!important;
  box-shadow:0 18px 48px rgba(0,0,0,.28),inset 0 1px 0 rgba(255,255,255,.04)!important;
  overflow:hidden!important;
}
.inventory-add-box:before{
  content:"";position:absolute;inset:0 auto 0 0;width:3px;
  background:linear-gradient(#ff5267,#b80f2b);box-shadow:0 0 22px rgba(227,27,54,.25);
}
.inventory-form-note{color:#8f8b91!important}
.brand-tabs-mobile{padding:4px!important;gap:7px!important;border-radius:14px;background:rgba(255,255,255,.025)!important;border:1px solid rgba(255,255,255,.07)!important;width:max-content;max-width:100%}
.brand-tabs-mobile .btn{border-radius:10px!important;box-shadow:none!important;min-height:38px!important}

/* Inventory cards get a dedicated data-grid treatment. */
.inventory-add-box~.card{
  border-radius:18px!important;
  background:linear-gradient(150deg,rgba(20,18,20,.92),rgba(7,7,8,.88))!important;
  border-color:rgba(255,255,255,.09)!important;
  box-shadow:0 24px 62px rgba(0,0,0,.34),inset 0 1px 0 rgba(255,255,255,.035)!important;
}
.inventory-add-box~.card>.card-header{
  position:relative!important;
  min-height:68px!important;
  padding:16px 20px!important;
  background:linear-gradient(90deg,rgba(227,27,54,.065),rgba(255,255,255,.012) 38%,transparent)!important;
  border-bottom:1px solid rgba(255,255,255,.075)!important;
}
.inventory-add-box~.card>.card-header:after{
  content:"";position:absolute;right:20px;bottom:-1px;width:62px;height:2px;border-radius:8px;
  background:linear-gradient(90deg,#ff5368,#9f0e25);box-shadow:0 0 16px rgba(227,27,54,.28);
}
.inventory-add-box~.card .card-title{font-size:.95rem!important;font-weight:800!important;color:#f8f7f8!important}
.inventory-add-box~.card .mobile-scroll-note{
  margin:10px 14px 0!important;padding:7px 11px!important;width:max-content!important;max-width:calc(100% - 28px)!important;
  border:1px solid rgba(255,255,255,.065)!important;border-radius:9px!important;
  background:rgba(255,255,255,.025)!important;color:#7f7a81!important;font-size:.68rem!important;
}
.inventory-add-box~.card .table-responsive{
  margin:10px 14px 16px!important;
  width:calc(100% - 28px)!important;
  border:1px solid rgba(255,255,255,.085)!important;
  border-radius:14px!important;
  background:#09090a!important;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.025),0 10px 32px rgba(0,0,0,.20)!important;
  overflow:auto!important;
}
.inventory-add-box~.card .table-stock{
  min-width:760px!important;
  border-collapse:separate!important;
  border-spacing:0!important;
  table-layout:fixed!important;
  font-size:.84rem!important;
  line-height:1.35!important;
  margin:0!important;
}
.inventory-add-box~.card .table-stock th,
.inventory-add-box~.card .table-stock td{
  height:47px!important;
  padding:9px 12px!important;
  border-width:0 0 1px 1px!important;
  border-color:rgba(255,255,255,.055)!important;
  vertical-align:middle!important;
  font-variant-numeric:tabular-nums!important;
}
.inventory-add-box~.card .table-stock thead th{
  position:sticky!important;top:0!important;z-index:4!important;
  height:44px!important;
  background:linear-gradient(180deg,#171417,#100e10)!important;
  color:#aaa5ab!important;
  border-bottom:1px solid rgba(255,255,255,.10)!important;
  font-size:.72rem!important;font-weight:700!important;text-transform:none!important;
  box-shadow:inset 0 -1px 0 rgba(0,0,0,.35)!important;
}
.inventory-add-box~.card .table-stock th:first-child,
.inventory-add-box~.card .table-stock td:first-child{
  position:sticky!important;right:0!important;z-index:3!important;
  width:170px!important;min-width:170px!important;max-width:170px!important;
  text-align:right!important;
  background:#0e0d0f!important;
  color:#f1eff1!important;
  font-weight:700!important;
  border-left:1px solid rgba(255,255,255,.10)!important;
  box-shadow:-10px 0 22px rgba(0,0,0,.17)!important;
}
.inventory-add-box~.card .table-stock thead th:first-child{z-index:7!important;background:#191519!important;color:#c8c4c8!important}
.inventory-add-box~.card .table-stock tbody td{
  color:#dddadd!important;
  background:rgba(255,255,255,.008)!important;
  transition:background .13s ease,color .13s ease!important;
}
.inventory-add-box~.card .table-stock tbody tr:nth-child(even) td{background:rgba(255,255,255,.018)!important}
.inventory-add-box~.card .table-stock tbody tr:nth-child(even) th:first-child{background:#111012!important}
.inventory-add-box~.card .table-stock tbody tr:hover td{background:rgba(227,27,54,.052)!important;color:#fff!important}
.inventory-add-box~.card .table-stock tbody tr:hover th:first-child{background:#1a1115!important;color:#fff!important}
.inventory-add-box~.card .table-stock td.num-center,
.inventory-add-box~.card .table-stock td.money-center{font-weight:650!important;letter-spacing:.01em!important}
.inventory-add-box~.card .table-stock td.text-danger{
  color:#ff6678!important;background:rgba(227,27,54,.095)!important;font-weight:850!important;
}

/* Main total inventory: make total column visually distinct. */
.inventory-add-box+.card .table-stock thead th:last-child,
.inventory-add-box+.card .table-stock tbody td:last-child{
  background:rgba(227,27,54,.055)!important;
  border-left-color:rgba(255,78,100,.16)!important;
  font-weight:850!important;color:#f8eef0!important;
}
.inventory-add-box+.card .table-stock thead th:last-child{color:#ff9aa7!important;background:linear-gradient(180deg,rgba(108,15,34,.43),rgba(38,13,20,.55))!important}

/* Summary/footer rows: strong but still accounting-readable. */
.inventory-add-box~.card .table-stock tfoot th,
.inventory-add-box~.card .table-stock tfoot td{height:50px!important;font-weight:850!important}
.inventory-add-box~.card .inventory-summary-row th,
.inventory-add-box~.card .inventory-summary-row td{
  background:linear-gradient(180deg,rgba(227,27,54,.115),rgba(227,27,54,.065))!important;
  border-color:rgba(255,75,98,.18)!important;color:#fff0f2!important;
}
.inventory-add-box~.card .inventory-capital-row th,
.inventory-add-box~.card .inventory-capital-row td{
  background:linear-gradient(180deg,rgba(38,169,105,.105),rgba(27,114,75,.07))!important;
  border-color:rgba(72,209,142,.15)!important;color:#80e5b2!important;
}
.inventory-add-box~.card .inventory-grand{font-weight:900!important}

@media(max-width:767.98px){
  .brand-tabs-mobile{width:100%;padding:3px!important}
  .inventory-add-box~.card .table-responsive{margin:8px 8px 12px!important;width:calc(100% - 16px)!important;border-radius:11px!important}
  .inventory-add-box~.card .mobile-scroll-note{margin:8px 8px 0!important}
  .inventory-add-box~.card .table-stock{min-width:690px!important;font-size:.79rem!important}
  .inventory-add-box~.card .table-stock th,.inventory-add-box~.card .table-stock td{height:43px!important;padding:8px 9px!important}
  .inventory-add-box~.card .table-stock th:first-child,.inventory-add-box~.card .table-stock td:first-child{width:140px!important;min-width:140px!important;max-width:140px!important}
}
CSS

step "3) APPLY PROFESSIONAL INVENTORY OVERLAY"
docker compose exec -T web sh -c "! grep -q '$INV_MARKER' /app/static/core/ui-polish.css" || fail "inventory overlay already present unexpectedly"
cat "$OVERLAY" | docker compose exec -T web sh -c 'cat >> /app/static/core/ui-polish.css' || fail "could not append inventory UI overlay"
docker compose exec -T web python manage.py collectstatic --noinput >/dev/null || fail "collectstatic failed"
docker compose restart web >/dev/null || fail "web restart failed"
docker compose restart caddy >/dev/null || fail "caddy restart failed"
sleep 6

docker compose exec -T web sh -c "grep -q '$BASE_MARKER' /app/static/core/ui-polish.css && grep -q '$INV_MARKER' /app/static/core/ui-polish.css" || fail "UI marker verification failed"
docker compose exec -T web python - <<'PY' || fail "live inventory template verification failed"
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings")
import django; django.setup()
from django.template.loader import get_template
from django.contrib.staticfiles.storage import staticfiles_storage
get_template("core/inventory_v19.html")
print("LIVE INVENTORY TEMPLATE OK")
print("UI_CSS_URL=", staticfiles_storage.url("core/ui-polish.css"))
PY

step "4) VERIFY ZERO BUSINESS CHANGE"
FINAL=$(snapshot_economic) || fail "could not capture final business snapshot"
echo "$FINAL"
[ "$LIVE" = "$FINAL" ] || {
  echo "--- BEFORE INVENTORY UI ---"; echo "$LIVE"
  echo "--- AFTER INVENTORY UI ---"; echo "$FINAL"
  fail "inventory UI overlay changed business values"
}

rm -f "$OVERLAY"
echo ""
echo "======================================"
echo "SUCCESS: BLACK RED UI V47 + PROFESSIONAL INVENTORY UI DEPLOYED"
echo "Inventory tables: sticky headers + sticky model column + zebra rows + hover + stronger totals"
echo "Business/accounting/inventory logic: unchanged"
echo "Remove only inventory redesign, keep base V47: bash server_black_red_ui_v47.sh"
echo "Rollback everything to pre-V47: bash server_rollback_black_red_ui_v47.sh"
echo "======================================"
