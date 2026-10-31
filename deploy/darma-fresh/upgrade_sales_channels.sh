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
docker compose -f compose.fresh.yml build web sister-digikala
echo "Django system checks — no changes to DB"
docker compose -f compose.fresh.yml run --rm --no-deps --entrypoint python web manage.py check
docker compose -f compose.fresh.yml run --rm --no-deps --entrypoint python web manage.py test core.tests_sister_sales -v 2

echo "Original DigiKala engine tests and fresh-stock test"
docker compose -f compose.fresh.yml run --rm --no-deps --entrypoint env sister-digikala -u SALES_START_EMPTY_STOCK python -m unittest discover -s tests -v

echo "Start the sister sales service and isolated Django web"
docker compose -f compose.fresh.yml up -d --no-deps sister-digikala web

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

docker compose -f compose.fresh.yml exec -T sister-digikala python -c 'import sqlite3; c=sqlite3.connect("/data/sales.sqlite3"); n=c.execute("SELECT count(*) FROM products").fetchone()[0]; print("SISTER_VARIANTS",n); assert n==538; print("CURRENT_STOCK_SELLER_AND_DIGIKALA",tuple(c.execute("SELECT sum(seller_stock),sum(digikala_stock) FROM products").fetchone())); c.close()'

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
echo "SISTER_SALES_CHANNELS_READY"
echo "Existing SSH tunnel: open /sales/ ; DigiKala: /sales/digikala/"
docker compose -f compose.fresh.yml ps
