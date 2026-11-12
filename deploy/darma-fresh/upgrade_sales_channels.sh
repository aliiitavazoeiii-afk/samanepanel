#!/usr/bin/env bash
# Upgrade only the isolated dia-darma-fresh Docker project. No volume resets.
set -euo pipefail

APP=/opt/dia-darma-fresh
test "$(id -u)" -eq 0 || { echo "Run as root" >&2; exit 1; }
test -f "$APP/.env" && test -f "$APP/compose.fresh.yml" || { echo "Fresh panel not found" >&2; exit 1; }
cd "$APP"
test "$(git branch --show-current)" = "dia-darma-fresh" || { echo "Wrong branch" >&2; exit 1; }
git diff --quiet && git diff --cached --quiet || { echo "Tracked source changes detected; stop" >&2; exit 1; }

git fetch origin dia-darma-fresh
git pull --ff-only origin dia-darma-fresh
test -f deploy/darma-fresh/Dockerfile.sister-sales
test -f daily_sales_service/catalog_seed.b64

umask 077
if ! grep -q '^SALES_ADMIN_PASSWORD=' .env; then
  printf 'SALES_ADMIN_PASSWORD=%s\n' "$(openssl rand -hex 32)" >> .env
fi

# Ensure the declared external edge network exists before any Compose command.
docker network inspect forosh_edge >/dev/null 2>&1 || docker network create --driver bridge forosh_edge >/dev/null
mkdir -p backups
STAMP="$(date +%Y%m%d-%H%M%S)"
echo "Backing up only the isolated Django PostgreSQL database..."
docker compose -f compose.fresh.yml exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > "backups/before-sister-sales-$STAMP.sql"
test -s "backups/before-sister-sales-$STAMP.sql"

if docker compose -f compose.fresh.yml ps --status running --services | grep -qx sister-digikala; then
  echo "Backing up existing sister-sales SQLite using SQLite backup API..."
  docker compose -f compose.fresh.yml exec -T sister-digikala python -c 'import sqlite3; a=sqlite3.connect("/data/sales.sqlite3"); b=sqlite3.connect("/data/upgrade_backup.sqlite3"); a.backup(b); b.close(); a.close()'
  CID="$(docker compose -f compose.fresh.yml ps -q sister-digikala)"
  docker cp "$CID:/data/upgrade_backup.sqlite3" "backups/sister-sales-$STAMP.sqlite3"
  test -s "backups/sister-sales-$STAMP.sqlite3"
fi

docker compose -f compose.fresh.yml config --quiet

# Docker Hub / PyPI may be blocked or unavailable on the server.
# Always rebuild source-only from the EXISTING RUNNING sister containers:
# the local images already contain the verified Python dependencies.
# This does not restart or alter any running container while building.
echo "Prepare offline builds from the running sister-only Docker images"
WEB_CID="$(docker compose -f compose.fresh.yml ps -q web)"
SALES_CID="$(docker compose -f compose.fresh.yml ps -q sister-digikala)"
test -n "$WEB_CID" && test -n "$SALES_CID" || {
  echo "ERROR: running sister web and sister-digikala images are required for a safe offline upgrade" >&2
  exit 1
}
test "$(docker inspect --format '{{.State.Running}}' "$WEB_CID")" = true
test "$(docker inspect --format '{{.State.Running}}' "$SALES_CID")" = true

echo "Verify existing running sister runtimes before touching any image"
docker compose -f compose.fresh.yml exec -T web python -c 'import django, psycopg; print("DJANGO_OFFLINE_RUNTIME_OK")'
docker compose -f compose.fresh.yml exec -T sister-digikala python -c 'import fastapi, uvicorn, multipart; print("SALES_OFFLINE_RUNTIME_OK")'

# A previous docker build/prune may have removed the immutable image ID
# referenced by an active container. Image inspection by that ID then fails,
# although the application remains healthy and a usable local tag exists.
# Recover from the local project image tag first; do not pull or install.
# As a last resort, snapshot the live container's rootfs without restarting it.
# Mounted Postgres/SQLite volumes are never part of docker commit.
prepare_offline_base() {
  local cid="$1" local_tag="$2" offline_tag="$3" imports="$4"
  local container_image
  container_image="$(docker inspect --format '{{.Image}}' "$cid")"
  if docker image inspect "$container_image" >/dev/null 2>&1; then
    echo "OFFLINE_SOURCE=LIVE_IMAGE_ID $offline_tag"
    docker image tag "$container_image" "$offline_tag"
  elif docker image inspect "$local_tag" >/dev/null 2>&1 && \
       docker run --rm --network none --entrypoint python "$local_tag" -c "$imports"; then
    echo "OFFLINE_SOURCE=VERIFIED_LOCAL_TAG $offline_tag"
    docker image tag "$local_tag" "$offline_tag"
  else
    echo "OFFLINE_SOURCE=CONTAINER_SNAPSHOT $offline_tag"
    # docker commit can capture runtime ENV, including passwords. Clear all
    # secret-looking keys in the image metadata before saving the image.
    local change_args=() key
    while IFS= read -r key; do
      test -n "$key" && change_args+=(--change "ENV ${key}=")
    done < <(docker inspect --format '{{json .Config.Env}}' "$cid" | \
      python3 -c 'import json,re,sys; a=json.load(sys.stdin); print("\n".join(k for item in a for k in [item.split("=",1)[0]] if re.search("PASSWORD|SECRET|TOKEN|API_KEY|PRIVATE_KEY|CREDENTIAL|AUTH|(^|_)PASS($|_)",k,re.I)))')
    docker commit --pause=false "${change_args[@]}" "$cid" "$offline_tag" >/dev/null || {
      echo "ERROR: Cannot recover the sister image offline; existing containers remain untouched." >&2
      return 1
    }
  fi
  docker image inspect "$offline_tag" >/dev/null
  docker run --rm --network none --entrypoint python "$offline_tag" -c "$imports" || {
    echo "ERROR: Recovered sister image has missing Python dependencies; refusing upgrade." >&2
    return 1
  }
}

prepare_offline_base "$WEB_CID" dia-darma-fresh-web:latest \
  dia-darma-fresh-web-offline-base:local \
  'import django,psycopg; print("OFFLINE_WEB_BASE_OK")'
prepare_offline_base "$SALES_CID" dia-darma-fresh-sister-digikala:latest \
  dia-darma-fresh-sister-offline-base:local \
  'import fastapi,uvicorn,multipart; print("OFFLINE_SALES_BASE_OK")'

echo "OFFLINE_SISTER_BASE_IMAGES_READY"

echo "Offline-only build of sister Django source (no pip, no PyPI)"
docker build --pull=false --network=none -f deploy/darma-fresh/Dockerfile.web.offline \
  -t dia-darma-fresh-web:latest .
echo "Offline-only build of sister sales source (no pip, no PyPI)"
docker build --pull=false --network=none -f deploy/darma-fresh/Dockerfile.sister-sales.offline \
  -t dia-darma-fresh-sister-digikala:latest .

echo "Django system checks — no changes to DB"
docker compose -f compose.fresh.yml run --rm --no-deps --entrypoint python web manage.py check
docker compose -f compose.fresh.yml run --rm --no-deps --entrypoint python web manage.py test core.tests_sister_sales -v 2

echo "Python compile checks (entire sister engine, including new UI)"
docker compose -f compose.fresh.yml run --rm --no-deps --entrypoint python sister-digikala -m compileall -q daily_sales_service tests

echo "Legacy, fresh-stock and unified SKU master tests"
docker compose -f compose.fresh.yml run --rm --no-deps --entrypoint env sister-digikala -u SALES_START_EMPTY_STOCK python -m unittest discover -s tests -v

echo "Verify new product, pricing and stock routes"
docker compose -f compose.fresh.yml run --rm --no-deps --entrypoint python sister-digikala -c 'from daily_sales_service.app import app; from daily_sales_service.master_v2_api import router; p={x.path for x in router.routes if hasattr(x,"path")}; root="/daily-sales"; required=("/master","/master/stock","/master/stock/operations","/pricing","/pricing/cost","/pricing/sales","/catalog","/catalog/parts/save"); from daily_sales_service.platform_api import router as platforms; from daily_sales_service.capital_api import router as capital; p.update(x.path for sub in (platforms,capital) for x in sub.routes if hasattr(x,"path")); required+=("/platforms","/platforms/{channel}","/platforms/{channel}/sales","/platforms/{channel}/add","/pricing/sales/variants/save","/capital-report","/api/sister-capital.json","/finance","/finance/accounts","/finance/movements","/finance/sales","/finance/accounts/add","/finance/parties/add","/finance/movements/add","/finance/movements/cancel","/api/sister-finance.json"); missing=[x for x in required if root+x not in p]; print("SISTER_MASTER_ROUTES",len(p)); assert not missing,missing'

echo "Start the sister sales service and isolated Django web"
docker compose -f compose.fresh.yml up -d --no-build --no-deps sister-digikala web

ready=0
for _ in $(seq 1 50); do
  status="$(docker compose -f compose.fresh.yml exec -T sister-digikala python -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8018/daily-sales/healthz",timeout=3).status)' 2>/dev/null || true)"
  if [ "$status" = "200" ]; then ready=1; break; fi
  sleep 2
done
if [ "$ready" != "1" ]; then
  echo "ERROR: sister sales service not healthy" >&2
  docker compose -f compose.fresh.yml logs --tail=80 sister-digikala
  exit 1
fi

echo "Live HTTP smoke without httpx or external Internet (stdlib urllib only)"
docker compose -f compose.fresh.yml exec -T sister-digikala python - <<'PY'
import base64,json,os,urllib.request
secret=os.environ["SALES_ADMIN_PASSWORD"]
account=os.environ.get("SALES_ADMIN_USER","bridge")
encoded=base64.b64encode((account+":"+secret).encode()).decode()
paths=("/daily-sales/healthz","/daily-sales/finance",
       "/daily-sales/finance/accounts","/daily-sales/finance/movements?section=receipt",
       "/daily-sales/finance/movements?section=payment",
       "/daily-sales/finance/sales","/daily-sales/api/sister-finance.json")
for path in paths:
    req=urllib.request.Request("http://127.0.0.1:8018"+path,
        headers={"Authorization":"Basic "+encoded})
    with urllib.request.urlopen(req,timeout=8) as response:
        assert response.status==200,(path,response.status)
        content=response.read(500000)
    if path.endswith("sister-finance.json"):
        payload=json.loads(content)
        assert isinstance(payload.get("platforms"),dict)
        assert "basalam" in payload["platforms"]
        assert "digikala" in payload["platforms"]
        assert isinstance(payload.get("total_receivable"),int)
    print("SISTER_LIVE_HTTP_OK",path)
PY

docker compose -f compose.fresh.yml exec -T sister-digikala python -c 'import sqlite3; c=sqlite3.connect("/data/sales.sqlite3"); n=c.execute("SELECT count(*) FROM products").fetchone()[0]; print("SISTER_VARIANTS",n); assert n==538; print("CURRENT_STOCK_SELLER_AND_DIGIKALA",tuple(c.execute("SELECT sum(seller_stock),sum(digikala_stock) FROM products").fetchone())); c.close()'

echo "Checking effective-dated costing and linked platform tables"
docker compose -f compose.fresh.yml exec -T sister-digikala python -c 'import sqlite3; c=sqlite3.connect("/data/sales.sqlite3"); names={x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type=\x27table\x27")}; required={"master_cost_history","platform_listings","platform_sales","platform_bundle_models","platform_bundle_variants","platform_bundle_parts","platform_bundle_sales","master_products","master_stock_events","sister_finance_parties","sister_finance_accounts","sister_finance_movements"}; assert required.issubset(names),required-names; print("SISTER_COST_HISTORY_AND_PLATFORMS_OK"); c.close()'

echo "Checking canonical master without altering data"
docker compose -f compose.fresh.yml exec -T sister-digikala python -c 'import sqlite3; c=sqlite3.connect("/data/sales.sqlite3"); c.execute("SELECT COUNT(*) FROM master_products"); count=c.execute("SELECT COUNT(*) FROM master_products").fetchone()[0]; unmapped=c.execute("SELECT COUNT(*) FROM products WHERE master_id IS NULL").fetchone()[0]; print("SISTER_MASTER_SKUS",count,"UNMAPPED_DIGIKALA",unmapped); c.close()'

echo "Import body.xlsx product definitions with ZERO opening stocks and no price changes"
docker compose -f compose.fresh.yml exec -T sister-digikala python -m daily_sales_service.catalog_import --dry-run
docker compose -f compose.fresh.yml exec -T sister-digikala python -m daily_sales_service.catalog_import --apply

echo "Confirm new products are present in the isolated master catalogue"
docker compose -f compose.fresh.yml exec -T sister-digikala python -c 'from daily_sales_service.engine import dbconnect; from daily_sales_service.catalog_import import entries; c=dbconnect("/data/sales.sqlite3"); items=entries(); n=sum(1 for x in items if c.execute("SELECT id FROM master_products WHERE category=? AND code=? AND size=? AND color=?",(x["category"],x["code"],x["size"],x["color"])).fetchone()); print("BODY_CATALOG_MATCHES",n,"OF",len(items)); assert n == 213; c.close()'

echo "Safe DigiKala auto-link preflight on 538 actual variant titles (read-only)"
docker compose -f compose.fresh.yml exec -T sister-digikala python -m daily_sales_service.digikala_auto_link --dry-run

echo "Link only unambiguous DigiKala variants to exact physical SKU components"
docker compose -f compose.fresh.yml exec -T sister-digikala python -m daily_sales_service.digikala_auto_link --apply

echo "Verify DigiKala auto mappings are deduplicated and never exceed source variants"
docker compose -f compose.fresh.yml exec -T sister-digikala python -c 'from daily_sales_service.engine import dbconnect; from daily_sales_service.digikala_auto_link import audit_totals; c=dbconnect("/data/sales.sqlite3"); x=audit_totals(c); print("DK_AUTOLINK_FINAL",x); assert x["total"]==538; assert 0<=x["automatic"]<=x["mapped"]<=538; c.close()'


code=""
for _ in $(seq 1 50); do
  code="$(curl --max-time 4 --silent --output /dev/null --write-out '%{http_code}' http://127.0.0.1:18081/sales/ || true)"
  if [ "$code" = "302" ]; then break; fi
  sleep 2
done
if [ "$code" != "302" ]; then
  echo "ERROR: sales hub is not reachable (HTTP $code)" >&2
  docker compose -f compose.fresh.yml logs --tail=80 web
  exit 1
fi
echo
echo "SISTER_MASTER_CATALOG_READY"
echo "BODY_XLSX_PRODUCT_DEFINITIONS_READY"
echo "SISTER_PLATFORMS_AND_DATED_CAPITAL_READY"
echo "SISTER_PLATFORM_PACKS_SIZE_PRICING_READY"
echo "Read-only verification of sale-derived claims and comprehensive capital"
docker compose -f compose.fresh.yml exec -T sister-digikala python - <<'PY'
from daily_sales_service.engine import dbconnect
from daily_sales_service.capital_api import financial_capital
from daily_sales_service.digikala_daily_ui import daily_page
from daily_sales_service.effective_costs import today
db=dbconnect("/data/sales.sqlite3")
totals=financial_capital(db)
assert totals["total_receivable"]==sum(x["outstanding"] for x in totals["platform_receivables"].values())
if totals["total_value"] is not None:
    assert totals["total_capital"]==totals["total_value"]+totals["total_receivable"]+totals["cash_balance"]
page=daily_page(db,today()).body.decode("utf-8")
assert 'بارگذاری اکسل دیجی‌کالا' in page
assert 'فروش ثبت‌شده پلتفرم‌های دیگر' not in page
print("SISTER_DAILY_XLSX_UI_AND_CAPITAL_INVARIANT_PASS",{
    "inventory":totals["total_value"],"cash":totals["cash_balance"],
    "claims":totals["total_receivable"],"capital":totals["total_capital"]})
db.close()
PY

echo "DK_538_AUTO_LINK_AUDITED_READY"
echo "SISTER_DAILY_XLSX_AND_FINANCIAL_CAPITAL_READY"
echo "SISTER_FINANCE_BASALAM_15_PERCENT_LEDGER_READY"
echo "SISTER_DOCKER_OFFLINE_BUILD_NO_PIP_READY"
echo "Existing SSH tunnel: /settings/products/ ; /settings/products/platforms/ ; /settings/products/pricing/ ; /inventory/stock/ ; /report/sister-capital/ ; /sales/ ; /finance/ ; /finance/accounts/ ; /payments/"
docker compose -f compose.fresh.yml ps
