#!/usr/bin/env bash
# Deploy unified sister-sales calendar/dashboard/report. Read-only data feature.
# Only /opt/dia-darma-fresh and its isolated sister services are touched.
set -Eeuo pipefail
APP=/opt/dia-darma-fresh
COMPOSE="docker compose -f compose.fresh.yml"
cd "$APP"
test "$(id -u)" = 0 || { echo "STOP: run as root"; exit 1; }
test "$(git branch --show-current)" = "dia-darma-fresh" || { echo "STOP: wrong git branch"; exit 1; }
git diff --quiet && git diff --cached --quiet || { echo "STOP: tracked local changes"; exit 1; }
test -f compose.fresh.yml
$COMPOSE config --quiet
echo "=== Fetching unified sales changes (fast-forward only) ==="
git fetch origin dia-darma-fresh
git merge --ff-only origin/dia-darma-fresh
for file in daily_sales_service/sister_sales_overview_v1.py core/sister_sales_pages_v1.py templates/core/sister_sales_calendar_v1.html templates/core/sister_sales_report_v1.html; do
    test -f "$file" || { echo "STOP: missing $file"; exit 1; }
done

echo "=== Read-only backup of existing isolated databases ==="
umask 077
STAMP="$(date +%Y%m%dT%H%M%S)"
BACKUP="$APP/backups/unified-sales-v1-$STAMP"
mkdir -p "$BACKUP"
$COMPOSE exec -T sister-digikala python -c 'import sqlite3; import sys; s=sqlite3.connect("/data/sales.sqlite3"); d=sqlite3.connect("/data/backup-unified-"+sys.argv[1]+".sqlite3"); s.backup(d); d.close(); s.close()' "$STAMP"
CID="$($COMPOSE ps -q sister-digikala)"
test -n "$CID"
docker cp "$CID:/data/backup-unified-$STAMP.sqlite3" "$BACKUP/sister-sales.sqlite3" >/dev/null
test -s "$BACKUP/sister-sales.sqlite3"
$COMPOSE exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$BACKUP/django-postgres.sql"
test -s "$BACKUP/django-postgres.sql"
echo "BACKUP_READY=$BACKUP"

echo "=== Build images without replacing running services ==="
$COMPOSE build web sister-digikala
echo "=== Pre-deployment unit and Django route checks ==="
$COMPOSE run --rm --no-deps sister-digikala python -m unittest discover -s tests -p 'test_sister_sales_overview_v1.py' -v
$COMPOSE run --rm --no-deps --entrypoint python web manage.py check

echo "=== Upgrade only isolated sister app web + sister-digikala ==="
$COMPOSE up -d --no-deps web sister-digikala
$COMPOSE exec -T web python manage.py check
$COMPOSE exec -T sister-digikala python - <<'PY'
import base64,datetime,json,os,time,urllib.request
from daily_sales_service.app import app
paths=app.openapi()["paths"]
assert "get" in paths["/daily-sales/api/sales-overview.json"]
pwd=os.environ["SALES_ADMIN_PASSWORD"]
auth=base64.b64encode(("bridge:"+pwd).encode()).decode()
day=datetime.date.today().isoformat()
url=f"http://127.0.0.1:8018/daily-sales/api/sales-overview.json?start={day}&end={day}"
for attempt in range(15):
    try:
        req=urllib.request.Request(url,headers={"Authorization":"Basic "+auth})
        with urllib.request.urlopen(req,timeout=5) as response:
            data=json.loads(response.read())
        assert "total" in data and "days" in data
        print("UNIFIED_SALES_API_OK",day,flush=True)
        break
    except Exception:
        if attempt==14:raise
        time.sleep(2)
PY
$COMPOSE exec -T web python - <<'PY'
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings")
import django
django.setup()
from django.urls import reverse
assert reverse("sale_start")=="/sales/"
assert reverse("sister_sales_report")=="/report/sales/"
print("DJANGO_SALES_CALENDAR_REPORT_ROUTES_OK")
PY
echo "UNIFIED_SALES_V1_DEPLOYED"
echo "BACKUP=$BACKUP"
echo "CALENDAR=https://forosh.filmjadiid.ir/sales/"
echo "REPORT=https://forosh.filmjadiid.ir/report/sales/"
echo "DASHBOARD=https://forosh.filmjadiid.ir/"
