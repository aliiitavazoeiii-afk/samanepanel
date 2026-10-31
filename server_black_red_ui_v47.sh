#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

BASE=d933ba520be6d2527f7df70689ab5c659751a601
MARKER='V47 BLACK RED UI RUNTIME OVERLAY'
OVERLAY=/tmp/darma-ui-v47.css

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

cat > "$OVERLAY" <<'CSS'

/* ========================================================================== */
/* V47 BLACK RED UI RUNTIME OVERLAY — PRESENTATION ONLY                       */
/* ========================================================================== */
:root{
  --navy:#050506!important;
  --navy2:#09090b!important;
  --navy3:#111013!important;
  --navy4:#1b171b!important;
  --orange:#e31b36!important;
  --orange2:#ff5267!important;
  --red:#ff4055!important;
  --v38-bg:#050506!important;
  --v38-bg-2:#09090b!important;
  --v38-panel:rgba(18,16,19,.82)!important;
  --v38-panel-soft:rgba(18,16,20,.62)!important;
  --v38-panel-strong:rgba(24,20,24,.90)!important;
  --v38-line:rgba(255,255,255,.10)!important;
  --v38-line-strong:rgba(255,255,255,.17)!important;
  --v38-text:#f7f7f8!important;
  --v38-muted:#9b989f!important;
  --v38-muted-2:#c1bec3!important;
  --v38-orange:#e31b36!important;
  --v38-orange-2:#ff6073!important;
  --v38-shadow:0 22px 60px rgba(0,0,0,.42)!important;
}

html,body,.page{background:#050506!important;color:#f7f7f8!important}
body:before{
  background:
    radial-gradient(ellipse at 15% -8%,rgba(145,8,31,.30),transparent 34%),
    radial-gradient(ellipse at 93% 18%,rgba(227,27,54,.14),transparent 28%),
    radial-gradient(ellipse at 56% 100%,rgba(111,7,25,.11),transparent 38%),
    linear-gradient(145deg,#040405 0%,#080708 52%,#0d090c 100%)!important;
}
body:after{opacity:.09!important}
::selection{background:rgba(227,27,54,.42)!important;color:#fff!important}
*{scrollbar-color:rgba(145,139,145,.42) transparent!important}
*::-webkit-scrollbar-thumb{background:rgba(145,139,145,.34)!important}
*::-webkit-scrollbar-thumb:hover{background:rgba(197,70,88,.52)!important}

.erp-sidebar{
  background:linear-gradient(180deg,rgba(4,4,5,.98),rgba(9,7,9,.95))!important;
  border-left-color:rgba(255,255,255,.085)!important;
  box-shadow:-20px 0 54px rgba(0,0,0,.38)!important;
}
.erp-topbar{
  background:rgba(5,5,6,.88)!important;
  border-bottom-color:rgba(255,255,255,.085)!important;
  box-shadow:0 12px 34px rgba(0,0,0,.20)!important;
}
.erp-topbar .small,.erp-brand small{color:#817d83!important}

/* User's Darma logo: white artwork belongs on a dark plaque, not the old light one. */
.erp-brand{
  position:relative!important;
  display:block!important;
  width:100%!important;
  height:132px!important;
  margin:0 2px 15px!important;
  padding:0!important;
  border:1px solid rgba(255,255,255,.105)!important;
  border-radius:18px!important;
  background-color:#09090a!important;
  background-image:url("darma-logo-v39.webp")!important;
  background-repeat:no-repeat!important;
  background-position:center!important;
  background-size:86% auto!important;
  box-shadow:0 18px 42px rgba(0,0,0,.38),inset 0 1px 0 rgba(255,255,255,.045)!important;
  overflow:hidden!important;
}
.erp-brand:hover{
  border-color:rgba(255,72,94,.30)!important;
  box-shadow:0 22px 48px rgba(0,0,0,.46),0 0 0 1px rgba(227,27,54,.07),inset 0 1px 0 rgba(255,255,255,.055)!important;
}
.erp-brand:after{
  content:"";position:absolute;left:16%;right:16%;bottom:0;height:1px;
  background:linear-gradient(90deg,transparent,rgba(255,62,85,.86),transparent);
  box-shadow:0 -8px 24px rgba(227,27,54,.18);
}
.erp-brand>span{
  position:absolute!important;width:1px!important;height:1px!important;overflow:hidden!important;
  clip:rect(0 0 0 0)!important;clip-path:inset(50%)!important;white-space:nowrap!important;opacity:0!important;
}

.erp-nav-title{color:#6e6970!important}
.erp-nav a{color:#bbb7bd!important}
.erp-nav a:hover{
  color:#fff!important;
  background:rgba(255,255,255,.045)!important;
  border-color:rgba(255,255,255,.075)!important;
}
.erp-nav a.active{
  color:#fff!important;
  background:linear-gradient(90deg,rgba(227,27,54,.22),rgba(255,255,255,.025))!important;
  border-color:rgba(255,78,100,.21)!important;
  box-shadow:inset -3px 0 0 #e31b36,0 9px 26px rgba(0,0,0,.24)!important;
}
.erp-dot{background:#575259!important;box-shadow:0 0 0 4px rgba(87,82,89,.07)!important}
.erp-nav a.active .erp-dot{background:#ff4359!important;box-shadow:0 0 0 5px rgba(227,27,54,.12)!important}

.card,.glass-card,.compact-form{
  background:linear-gradient(145deg,rgba(23,20,23,.86),rgba(8,8,9,.82))!important;
  border-color:rgba(255,255,255,.095)!important;
  box-shadow:0 22px 58px rgba(0,0,0,.37),inset 0 1px 0 rgba(255,255,255,.04)!important;
}
.card-header,.card-footer{background:rgba(255,255,255,.014)!important;border-color:rgba(255,255,255,.075)!important}
.card a:not(.btn){color:#ff97a5!important}
.page-kicker{color:#ff687a!important}
.page-muted,.text-secondary{color:#98949a!important}

.btn-primary{
  border-color:rgba(255,83,104,.68)!important;
  background:linear-gradient(145deg,#ff445a 0%,#e31b36 56%,#a90e27 100%)!important;
  color:#fff!important;
  text-shadow:none!important;
  box-shadow:0 12px 30px rgba(227,27,54,.25),inset 0 1px 0 rgba(255,255,255,.22)!important;
}
.btn-primary:hover{
  border-color:rgba(255,116,133,.86)!important;
  background:linear-gradient(145deg,#ff6173 0%,#f12643 56%,#bc102c 100%)!important;
  box-shadow:0 16px 36px rgba(227,27,54,.32),inset 0 1px 0 rgba(255,255,255,.26)!important;
}
.btn:not(.btn-link):focus-visible{box-shadow:0 0 0 3px rgba(227,27,54,.17),0 9px 25px rgba(0,0,0,.24)!important}
.btn-outline-light,.btn-secondary{background:rgba(255,255,255,.045)!important;border-color:rgba(255,255,255,.105)!important;color:#eeecef!important}
.btn-outline-light:hover,.btn-secondary:hover{background:rgba(255,255,255,.075)!important;border-color:rgba(255,91,110,.20)!important}

.form-control,.form-select,.input-group-text,.grid-input{
  background:rgba(255,255,255,.045)!important;
  border-color:rgba(255,255,255,.105)!important;
}
.form-control:hover,.form-select:hover{background:rgba(255,255,255,.06)!important;border-color:rgba(255,255,255,.16)!important}
.form-control:focus,.form-select:focus,.grid-input:focus{
  border-color:rgba(255,67,89,.78)!important;
  background:rgba(255,255,255,.07)!important;
  box-shadow:0 0 0 3px rgba(227,27,54,.12),inset 0 1px 0 rgba(255,255,255,.025)!important;
}
.form-select option{background:#0b0a0c!important;color:#fff!important}

.quick-icon,.alert-count{
  background:linear-gradient(145deg,rgba(227,27,54,.18),rgba(227,27,54,.065))!important;
  border-color:rgba(255,78,100,.16)!important;
  color:#ff8292!important;
}
.quick-card:hover{
  border-color:rgba(255,78,100,.27)!important;
  background:linear-gradient(145deg,rgba(37,24,28,.83),rgba(10,9,11,.78))!important;
  box-shadow:0 28px 66px rgba(0,0,0,.44),0 0 0 1px rgba(227,27,54,.035)!important;
}
.badge-soft-orange{background:rgba(227,27,54,.12)!important;color:#ff8998!important;border-color:rgba(255,75,97,.16)!important}
.alert-dot-orange{background:#e31b36!important;box-shadow:0 0 0 5px rgba(227,27,54,.11)!important}

.report-filter,.summary-cell,.brand-report,.capital-side>div{
  background:rgba(255,255,255,.025)!important;
  border-color:rgba(255,255,255,.085)!important;
}
.excel-title{background:linear-gradient(100deg,rgba(34,24,28,.70),rgba(10,9,11,.55))!important}
.brand-report-head{background:rgba(255,255,255,.035)!important}
.brand-total td{background:rgba(227,27,54,.050)!important}
.capital-hero{
  background:linear-gradient(118deg,rgba(38,22,27,.88),rgba(10,9,11,.80) 62%,rgba(25,15,19,.76))!important;
  border-color:rgba(255,255,255,.10)!important;
}
.capital-hero:before{background:radial-gradient(circle,rgba(227,27,54,.13),transparent 68%)!important}
.excel-subtitle{border-right-color:#e31b36!important}
.material-toggle{color:#ff7587!important}
.material-block>summary{
  background:linear-gradient(145deg,rgba(26,22,25,.82),rgba(9,9,10,.76))!important;
  border-color:rgba(255,255,255,.09)!important;
}
.material-grid .sticky-col,.takvin-grid .sticky-col,.table-stock th:first-child,.table-stock td:first-child{background:rgba(10,9,11,.97)!important}
.raw-edit-row td{background:rgba(227,27,54,.026)!important}

.dropdown-menu,.modal-content{
  background:rgba(12,10,12,.97)!important;
  border-color:rgba(255,255,255,.10)!important;
  box-shadow:0 30px 72px rgba(0,0,0,.58)!important;
}
.dropdown-item:hover,.dropdown-item:focus{background:rgba(227,27,54,.10)!important}

/* Comprehensive-report KPI strip: exact 4-column grid, equal cards, aligned numbers. */
.erp-content .v36-top-metrics{
  display:grid!important;
  grid-template-columns:repeat(4,minmax(0,1fr))!important;
  gap:12px!important;
  width:100%!important;
  margin:0!important;
  padding:0!important;
}
.erp-content .v36-top-metrics>div{
  width:auto!important;max-width:none!important;flex:none!important;padding:0!important;margin:0!important;
}
.erp-content .v36-top-metrics .summary-cell{
  min-height:92px!important;
  height:100%!important;
  padding:16px 18px!important;
  display:flex!important;
  flex-direction:column!important;
  justify-content:center!important;
  align-items:flex-start!important;
  border-radius:15px!important;
  background:linear-gradient(145deg,rgba(27,23,26,.76),rgba(10,9,11,.72))!important;
  border:1px solid rgba(255,255,255,.09)!important;
}
.erp-content .v36-top-metrics .summary-cell span{color:#918d93!important;margin:0!important}
.erp-content .v36-top-metrics .summary-cell strong,
.erp-content .v36-top-metrics .summary-cell .money,
.erp-content .v36-top-metrics .summary-cell .num{
  width:100%!important;
  margin-top:6px!important;
  text-align:right!important;
  direction:ltr!important;
  font-variant-numeric:tabular-nums!important;
}
.v36-fold{background:linear-gradient(145deg,rgba(22,19,22,.78),rgba(8,8,9,.75))!important;border-color:rgba(255,255,255,.085)!important}
.v36-fold[open]>summary{background:rgba(227,27,54,.055)!important;border-bottom-color:rgba(255,255,255,.075)!important}
.v36-fold-arrow{color:#ff6577!important}

@media(max-width:991.98px){
  .erp-brand{width:calc(100% - 44px)!important;height:120px!important;margin-left:44px!important;background-size:88% auto!important}
}
@media(max-width:767.98px){
  .erp-content .v36-top-metrics{grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:9px!important}
  .erp-content .v36-top-metrics .summary-cell{min-height:82px!important;padding:13px 14px!important}
}
@media(max-width:390px){
  .erp-content .v36-top-metrics{grid-template-columns:1fr!important}
}
CSS

step "1) START DATABASE + BACKUP CURRENT STATE"
docker compose config -q || fail "compose invalid"
docker compose up -d db || fail "database start failed"
i=1
while [ "$i" -le 30 ]; do
  docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 && break
  [ "$i" -eq 30 ] && fail "PostgreSQL not ready"
  sleep 1; i=$((i+1))
done
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="backups/before-black-red-ui-v47-${STAMP}"
mkdir -p "$BACKUP_DIR"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP_DIR/database.sql" || fail "database backup failed"
[ -s "$BACKUP_DIR/database.sql" ] || fail "database backup empty"
cp static/core/ui-polish.css "$BACKUP_DIR/ui-polish.css"
[ -f static/core/darma-logo-v39.webp ] && cp static/core/darma-logo-v39.webp "$BACKUP_DIR/darma-logo-v39.webp" || true
git rev-parse HEAD > "$BACKUP_DIR/git-head.txt"
echo "BACKUP_DIR=$BACKUP_DIR"

step "2) VERIFY V47 IS PRESENTATION-ONLY SOURCE"
git cat-file -e "$BASE^{commit}" || fail "V47 base commit missing"
git diff --quiet "$BASE"..HEAD -- core templates config Dockerfile entrypoint.sh docker-compose.yml Caddyfile || fail "backend/template/infrastructure source changed in V47 range"
echo "Protected backend/templates: unchanged from V47 base"

step "3) BUILD CLEAN CURRENT IMAGE + PREFLIGHT"
docker compose build web || fail "web build failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"
docker compose run --rm --entrypoint python web - <<'PY' || fail "template preflight failed"
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings")
import django; django.setup()
from django.template.loader import get_template
for name in ("base.html","core/report_excel_v45.html"):
    get_template(name)
    print("TEMPLATE OK", name)
PY

step "4) CAPTURE BUSINESS INVARIANTS"
docker compose up -d web || fail "web start failed"
sleep 4
LIVE=$(snapshot_economic) || fail "could not capture business snapshot"
echo "$LIVE"

step "5) RECREATE CLEAN WEB, THEN APPLY BLACK/RED OVERLAY INSIDE CONTAINER"
docker compose up -d --force-recreate web || fail "web recreate failed"
sleep 5
# Always start from the clean image source so rerunning this script is idempotent.
docker compose exec -T web sh -c "! grep -q '$MARKER' /app/static/core/ui-polish.css" || fail "clean image unexpectedly already contains V47 overlay"
cat "$OVERLAY" | docker compose exec -T web sh -c 'cat >> /app/static/core/ui-polish.css' || fail "could not append V47 overlay"
docker compose exec -T web python manage.py collectstatic --noinput >/dev/null || fail "collectstatic after V47 overlay failed"
docker compose restart web >/dev/null || fail "web restart failed"
docker compose restart caddy >/dev/null || fail "caddy restart failed"
sleep 6

step "6) VERIFY UI OVERLAY + REPORT TEMPLATE"
docker compose exec -T web sh -c "grep -q '$MARKER' /app/static/core/ui-polish.css" || fail "V47 overlay marker missing"
docker compose exec -T web python - <<'PY' || fail "live template verification failed"
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings")
import django; django.setup()
from django.template.loader import get_template
from django.contrib.staticfiles.storage import staticfiles_storage
for name in ("base.html","core/report_excel_v45.html"):
    get_template(name)
    print("LIVE TEMPLATE OK", name)
print("UI_CSS_URL=", staticfiles_storage.url("core/ui-polish.css"))
PY

step "7) VERIFY ZERO BUSINESS CHANGE"
FINAL=$(snapshot_economic) || fail "could not capture final business snapshot"
echo "$FINAL"
[ "$LIVE" = "$FINAL" ] || {
  echo "--- BEFORE UI ---"; echo "$LIVE"
  echo "--- AFTER UI ---"; echo "$FINAL"
  fail "V47 changed business values"
}

rm -f "$OVERLAY"
echo ""
echo "======================================"
echo "SUCCESS: BLACK RED UI V47 DEPLOYED"
echo "Backup: $BACKUP_DIR"
echo "Theme: black / charcoal / red"
echo "Logo: Darma artwork on dark plaque"
echo "Comprehensive KPI row: aligned 4-column grid"
echo "Business/accounting/inventory logic: unchanged"
echo "Rollback anytime: bash server_rollback_black_red_ui_v47.sh"
echo "======================================"
