#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/dia-darma-fresh
test "$(id -u)" = 0
test "$(git branch --show-current)" = "dia-darma-fresh"
git diff --quiet && git diff --cached --quiet || { echo "STOP: local uncommitted changes"; exit 1; }
git fetch origin dia-darma-fresh
git merge --ff-only origin/dia-darma-fresh
docker compose -f compose.fresh.yml config --quiet
CID="$(docker compose -f compose.fresh.yml ps -q web)"
test -n "$CID"
test "$(docker inspect -f '{{.State.Running}}' "$CID")" = true
case "$(docker inspect -f '{{.Name}}' "$CID")" in *dia-darma-fresh*) ;; *) echo "STOP: not isolated Dia web"; exit 1 ;; esac

umask 077
STAMP="$(date +%Y%m%dT%H%M%S)"
BACKUP="/opt/dia-darma-fresh/backups/calendar-day-$STAMP"
mkdir -p "$BACKUP/core" "$BACKUP/templates/core"
for path in core/sister_sales_pages_v1.py core/urls.py; do docker cp "$CID:/app/$path" "$BACKUP/$path"; done
# No database files are touched in this navigation-only patch.
for path in core/sister_sales_pages_v1.py core/urls.py templates/core/sister_sales_day_v1.html; do
  test -s "$path" || { echo "STOP: missing $path"; exit 1; }
done
docker cp core/sister_sales_pages_v1.py "$CID:/tmp/sister_sales_pages_v1.py"
docker cp core/urls.py "$CID:/tmp/sales_day_urls.py"
docker exec "$CID" python -m py_compile /tmp/sister_sales_pages_v1.py /tmp/sales_day_urls.py

CHANGED=0
rollback() {
  code=$?
  trap - ERR
  if [ "$CHANGED" -eq 1 ]; then
    docker cp "$BACKUP/core/sister_sales_pages_v1.py" "$CID:/app/core/sister_sales_pages_v1.py" || true
    docker cp "$BACKUP/core/urls.py" "$CID:/app/core/urls.py" || true
    docker exec "$CID" rm -f /app/templates/core/sister_sales_day_v1.html || true
    docker compose -f compose.fresh.yml restart web || true
  fi
  echo "CALENDAR_PATCH_FAILED backup=$BACKUP" >&2
  exit "$code"
}
trap rollback ERR
CHANGED=1
docker cp core/sister_sales_pages_v1.py "$CID:/app/core/sister_sales_pages_v1.py"
docker cp core/urls.py "$CID:/app/core/urls.py"
docker cp templates/core/sister_sales_day_v1.html "$CID:/app/templates/core/sister_sales_day_v1.html"
docker compose -f compose.fresh.yml exec -T web python manage.py check
docker compose -f compose.fresh.yml exec -T web python - <<'PY'
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings")
import django
django.setup()
from django.urls import reverse
from django.template.loader import get_template
assert reverse("sister_sales_day",kwargs={"jy":1405,"jm":9,"jd":6}) == "/sales/day/1405/9/6/"
assert get_template("core/sister_sales_day_v1.html")
from core.jalali_calendar import jalali_month_data
from datetime import timedelta
from core.sister_sales_pages_v1 import CHANNELS
assert len(CHANNELS)==4
print("CALENDAR_DAY_ROUTING_OK")
PY
docker compose -f compose.fresh.yml restart web
docker compose -f compose.fresh.yml exec -T web python - <<'PY'
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings")
import django
django.setup()
from django.urls import resolve
assert resolve("/sales/day/1405/9/6/").url_name=="sister_sales_day"
print("CALENDAR_DAY_LIVE_OK")
PY
trap - ERR
echo "CALENDAR_DAY_PATCH_OK"
echo "BACKUP=$BACKUP"
echo "NOTE: navigation-only container hotpatch; future image rebuild must include Git source."
