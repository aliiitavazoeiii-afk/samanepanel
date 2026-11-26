#!/usr/bin/env bash
# Offline/no-build sister-only code deployment, no Docker registry access.
# Isolated containers only. Databases are backed up, never overwritten.
set -Eeuo pipefail
APP=/opt/dia-darma-fresh
cd "$APP"
test "$(id -u)" = 0 || { echo "STOP: run as root"; exit 1; }
test "$(git branch --show-current)" = "dia-darma-fresh" || { echo "STOP: wrong branch"; exit 1; }
git diff --quiet && git diff --cached --quiet || { echo "STOP: uncommitted changes"; exit 1; }
docker compose -f compose.fresh.yml config --quiet

echo "=== Fetch current patch (fast-forward only) ==="
git fetch origin dia-darma-fresh
git merge --ff-only origin/dia-darma-fresh

for file in \
  daily_sales_service/app.py \
  daily_sales_service/sister_sales_overview_v1.py \
  core/sister_sales.py core/sister_sales_pages_v1.py \
  core/excel_dashboard_v89.py core/urls.py \
  templates/core/dashboard_excel_v89.html \
  templates/core/sister_sales_embedded.html \
  templates/core/sister_sales_calendar_v1.html \
  templates/core/sister_sales_report_v1.html \
  tests/test_sister_sales_overview_v1.py
do
  test -s "$file" || { echo "STOP: missing file $file"; exit 1; }
done

SALES_CID="$(docker compose -f compose.fresh.yml ps -q sister-digikala)"
WEB_CID="$(docker compose -f compose.fresh.yml ps -q web)"
test -n "$SALES_CID" && test -n "$WEB_CID" || { echo "STOP: sister containers missing"; exit 1; }
for cid in "$SALES_CID" "$WEB_CID"; do
  test "$(docker inspect -f '{{.State.Running}}' "$cid")" = true || { echo "STOP: container not running"; exit 1; }
  case "$(docker inspect -f '{{.Name}}' "$cid")" in
    *dia-darma-fresh*) ;;
    *) echo "STOP: unexpected container outside isolated sister stack"; exit 1 ;;
  esac
done

umask 077
STAMP="$(date +%Y%m%dT%H%M%S)"
BACKUP="$APP/backups/unified-sales-offline-$STAMP"
mkdir -p "$BACKUP/core" "$BACKUP/templates/core" "$BACKUP/daily_sales_service"
echo "=== Back up runtime code ==="
for file in core/sister_sales.py core/excel_dashboard_v89.py core/urls.py; do
  docker cp "$WEB_CID:/app/$file" "$BACKUP/$file"
done
for file in templates/core/dashboard_excel_v89.html templates/core/sister_sales_embedded.html; do
  docker cp "$WEB_CID:/app/$file" "$BACKUP/$file"
done
docker cp "$SALES_CID:/app/daily_sales_service/app.py" "$BACKUP/daily_sales_service/app.py"
echo "=== Back up both isolated data stores ==="
docker compose -f compose.fresh.yml exec -T sister-digikala python - "$STAMP" <<'PY'
import sqlite3,sys
stamp=sys.argv[1]
src=sqlite3.connect("file:/data/sales.sqlite3?mode=ro",uri=True)
with sqlite3.connect("/data/unified-sales-offline-"+stamp+".sqlite3") as dst:
    src.backup(dst)
src.close()
PY
docker cp "$SALES_CID:/data/unified-sales-offline-$STAMP.sqlite3" "$BACKUP/sister-sales.sqlite3"
test -s "$BACKUP/sister-sales.sqlite3"
docker compose -f compose.fresh.yml exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$BACKUP/django-postgres.sql"
test -s "$BACKUP/django-postgres.sql"
echo "BACKUP_READY=$BACKUP"

echo "=== Syntax-check new files inside matching current runtimes ==="
docker cp "$APP/daily_sales_service/sister_sales_overview_v1.py" "$SALES_CID:/tmp/sister_sales_overview_v1.py"
docker cp "$APP/daily_sales_service/app.py" "$SALES_CID:/tmp/unified_app.py"
docker exec "$SALES_CID" python -m py_compile /tmp/sister_sales_overview_v1.py /tmp/unified_app.py
for file in core/sister_sales.py core/sister_sales_pages_v1.py core/excel_dashboard_v89.py core/urls.py; do
  docker cp "$APP/$file" "$WEB_CID:/tmp/$(basename "$file")"
  docker exec "$WEB_CID" python -m py_compile "/tmp/$(basename "$file")"
done

CHANGED=0
rollback() {
  rc=$?
  trap - ERR INT TERM
  echo "ERROR: offline deployment failed (exit $rc); restoring original code" >&2
  if [ "$CHANGED" = 1 ]; then
    for file in core/sister_sales.py core/excel_dashboard_v89.py core/urls.py; do
      docker cp "$BACKUP/$file" "$WEB_CID:/app/$file" || true
    done
    for file in templates/core/dashboard_excel_v89.html templates/core/sister_sales_embedded.html; do
      docker cp "$BACKUP/$file" "$WEB_CID:/app/$file" || true
    done
    docker exec "$WEB_CID" rm -f /app/core/sister_sales_pages_v1.py /app/templates/core/sister_sales_calendar_v1.html /app/templates/core/sister_sales_report_v1.html || true
    docker cp "$BACKUP/daily_sales_service/app.py" "$SALES_CID:/app/daily_sales_service/app.py" || true
    docker exec "$SALES_CID" rm -f /app/daily_sales_service/sister_sales_overview_v1.py || true
    docker compose -f compose.fresh.yml restart sister-digikala web || true
  fi
  echo "SOURCE_ROLLBACK_BACKUP=$BACKUP" >&2
  echo "Databases were NOT restored or overwritten." >&2
  exit "$rc"
}
trap rollback ERR INT TERM

echo "=== Apply only changed code to running sister containers ==="
CHANGED=1
for file in daily_sales_service/app.py daily_sales_service/sister_sales_overview_v1.py; do
  docker cp "$APP/$file" "$SALES_CID:/app/$file"
done
for file in core/sister_sales.py core/sister_sales_pages_v1.py core/excel_dashboard_v89.py core/urls.py; do
  docker cp "$APP/$file" "$WEB_CID:/app/$file"
done
for file in templates/core/dashboard_excel_v89.html templates/core/sister_sales_embedded.html templates/core/sister_sales_calendar_v1.html templates/core/sister_sales_report_v1.html; do
  docker cp "$APP/$file" "$WEB_CID:/app/$file"
done
docker cp "$APP/tests/test_sister_sales_overview_v1.py" "$SALES_CID:/app/tests/test_sister_sales_overview_v1.py"

echo "=== Validate new code without updating inventory or sales ==="
docker compose -f compose.fresh.yml exec -T sister-digikala python -m unittest discover -s tests -p 'test_sister_sales_overview_v1.py' -v
docker compose -f compose.fresh.yml exec -T sister-digikala python - <<'PY'
from daily_sales_service.app import app
paths=app.openapi()["paths"]
assert "get" in paths.get("/daily-sales/api/sales-overview.json",{})
print("SISTER_API_ROUTE_OK",flush=True)
PY
docker compose -f compose.fresh.yml exec -T web python manage.py check
docker compose -f compose.fresh.yml exec -T web python - <<'PY'
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings")
import django
django.setup()
from django.urls import reverse
from django.template.loader import get_template
assert reverse("sale_start")=="/sales/"
assert reverse("sister_sales_report")=="/report/sales/"
for template in ("core/sister_sales_calendar_v1.html","core/sister_sales_report_v1.html","core/dashboard_excel_v89.html"):
    get_template(template)
print("DJANGO_CALENDAR_REPORT_TEMPLATES_OK",flush=True)
PY

echo "=== Restart ONLY the existing sister app containers; no build/recreate ==="
docker compose -f compose.fresh.yml restart sister-digikala web
echo "=== Verify live API ==="
docker compose -f compose.fresh.yml exec -T sister-digikala python - <<'PY'
import base64,datetime,json,os,time,urllib.request
auth=base64.b64encode((os.environ["SALES_ADMIN_USER"]+":"+os.environ["SALES_ADMIN_PASSWORD"]).encode()).decode()
day=datetime.date.today().isoformat()
url="http://127.0.0.1:8018/daily-sales/api/sales-overview.json?start="+day+"&end="+day
for attempt in range(15):
    try:
        req=urllib.request.Request(url,headers={"Authorization":"Basic "+auth})
        with urllib.request.urlopen(req,timeout=8) as response:
            data=json.loads(response.read())
            assert response.status==200
        assert isinstance(data.get("total"),dict)
        assert "gross" in data["total"] and "profit" in data["total"]
        print("UNIFIED_SALES_API_LIVE_OK",flush=True)
        break
    except Exception:
        if attempt==14:raise
        time.sleep(2)
PY
echo "=== Verify rendered authenticated date picker/page ==="
docker compose -f compose.fresh.yml exec -T web python - <<'PY'
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings")
import django
django.setup()
from django.test import RequestFactory
from types import SimpleNamespace
from core.sister_sales import channels
request=RequestFactory().get("/sales/?jy=1405&jm=9&jd=6")
request.user=SimpleNamespace(is_authenticated=True)
res=channels(request)
assert res.status_code==200
text=res.content.decode("utf-8")
for part in ("تقویم فروش روزانه","دیجی‌کالا","باسلام","فروش قالب"):
    assert part in text, part
print("DJANGO_SALES_CALENDAR_LIVE_OK",flush=True)
PY
trap - ERR INT TERM
echo "UNIFIED_SALES_OFFLINE_DEPLOYED_OK"
echo "BACKUP=$BACKUP"
echo "NOTE: Running container files are hotpatched. Future Docker recreation requires rebuilt images."
