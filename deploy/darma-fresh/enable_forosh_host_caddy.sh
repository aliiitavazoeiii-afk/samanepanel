#!/usr/bin/env bash
# Deploy forosh.filmjadiid.ir behind the EXISTING host-level Caddy service.
# Never modify the Dia Gallery Compose project or its business database.
set -Eeuo pipefail

DOMAIN=forosh.filmjadiid.ir
APP=/opt/dia-darma-fresh
COMPOSE=compose.fresh.yml
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run as root"
for cmd in docker git python3 curl caddy; do
  command -v "$cmd" >/dev/null || die "$cmd not installed on the host"
done
docker compose version >/dev/null || die "Docker Compose plugin unavailable"
[ -f "$APP/.env" ] && [ -f "$APP/$COMPOSE" ] || die "Isolated sales panel not installed in $APP"
[ "$(cd "$APP" && git branch --show-current)" = "dia-darma-fresh" ] || die "Wrong sales Git branch"
cd "$APP"
git diff --quiet && git diff --cached --quiet || die "Tracked local source changes: stop before any modification"

# We observed host caddy listening on 80 and 443, not a Docker Caddy container.
# Extract the live config from the running Caddy process, not a guessed path.
CADDY_PID=""
if command -v systemctl >/dev/null && systemctl is-active --quiet caddy; then
  CADDY_PID="$(systemctl show caddy --property MainPID --value)"
fi
if [ -z "$CADDY_PID" ] || [ "$CADDY_PID" = 0 ]; then
  if command -v pgrep >/dev/null; then
    CADDY_PID="$(pgrep -xo caddy || true)"
  fi
fi
[ -n "$CADDY_PID" ] && [ -r "/proc/$CADDY_PID/cmdline" ] || die "Running host Caddy process not found"
CMD="$(tr '\0' ' ' < "/proc/$CADDY_PID/cmdline")"
[[ "$CMD" == *"caddy"*"run"* ]] || die "Unexpected Caddy process command line (check ps -p $CADDY_PID -o args=)"
CONFIG="$(python3 - "$CADDY_PID" <<'PY'
import pathlib, sys
pid=sys.argv[1]
args=[s.decode() for s in pathlib.Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\x00') if s]
for i, arg in enumerate(args):
    if arg in ('--config', '-c') and i+1 < len(args):
        print(args[i+1])
        break
    if arg.startswith('--config='):
        print(arg.partition('=')[2])
        break
PY
)"
[ -n "$CONFIG" ] || die "Active Caddy process has no explicit --config. Refusing to guess; inspect: ps -p $CADDY_PID -o args="
[ -f "$CONFIG" ] && [ -w "$CONFIG" ] || die "Live Caddyfile missing or not writable: $CONFIG"
case "$CONFIG" in *.json) die "Active Caddy is configured with JSON, not Caddyfile; no automatic edits";; esac
echo "HOST_CADDY_PID=$CADDY_PID"
echo "LIVE_CADDY_CONFIG=$CONFIG"
echo "HOST_CADDY_CMD=$CMD"

caddy validate --config "$CONFIG" --adapter caddyfile >/dev/null || die "Existing active Caddyfile fails validation"
JSON="$(caddy adapt --config "$CONFIG" --adapter caddyfile 2>/dev/null)" || die "Cannot adapt original Caddyfile"
[[ "$JSON" == *samaneh.filmjadiid.ir* ]] || die "Active Caddy config does not serve samaneh.filmjadiid.ir; refusing to modify it"

MARK="# BEGIN FOROSH SAMANEPANEL HOST-CADDY"
if [[ "$JSON" == *"$DOMAIN"* ]]; then
  if ! grep -Fq "$MARK" "$CONFIG" || ! grep -Eq 'reverse_proxy[[:space:]]+127\.0\.0\.1:18081' "$CONFIG"; then
    die "Domain already exists outside our managed site block; refusing to overwrite"
  fi
  echo "Existing managed domain block recognized: no duplicate will be created"
else
  if grep -Fq "$MARK" "$CONFIG"; then
    die "Managed site block exists but live Caddy JSON does not contain domain; inspect manually"
  fi
fi

STATUS="$(curl --noproxy '*' --silent --max-time 8 --output /dev/null --write-out '%{http_code}' http://127.0.0.1:18081/login/ || true)"
[ "$STATUS" = 200 ] || die "Fresh Django login backend is not ready on 127.0.0.1:18081 (HTTP $STATUS)"

# Download code without raw.githubusercontent.com cache. Same repository and branch only.
echo "Fetching isolated Samanepanel code"
git fetch origin dia-darma-fresh
git merge --ff-only origin/dia-darma-fresh
git diff --quiet && git diff --cached --quiet || die "Unexpected tracked changes after fetch"
# The current fresh Compose declares this pre-existing isolated external
# network. Ensure it exists even when the user has not rerun the old upgrade.
docker network inspect forosh_edge >/dev/null 2>&1 || docker network create --driver bridge forosh_edge >/dev/null
docker compose -f "$COMPOSE" config --quiet

umask 077
mkdir -p "$APP/backups"
STAMP="$(date +%Y%m%d-%H%M%S)"
ENV_BACKUP="$APP/backups/forosh-host-env-$STAMP"
CADDY_BACKUP="$APP/backups/forosh-host-Caddyfile-$STAMP"
cp -p "$APP/.env" "$ENV_BACKUP"
cp -p "$CONFIG" "$CADDY_BACKUP"
[ -s "$ENV_BACKUP" ] && [ -s "$CADDY_BACKUP" ] || die "Backup creation failed"

# Change only the new panel's .env, preserving all DB/admin secrets.
python3 - "$APP/.env" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])
values={
  "ALLOWED_HOSTS":"forosh.filmjadiid.ir,127.0.0.1,localhost",
  "CSRF_TRUSTED_ORIGINS":"https://forosh.filmjadiid.ir",
  "DIA_DARMA_SSH_ONLY":"0",
  "DEBUG":"0",
}
seen=set()
result=[]
for line in p.read_text().splitlines():
    key=line.split("=",1)[0].strip() if "=" in line else None
    if key in values:
        if key not in seen:
            result.append(f"{key}={values[key]}")
            seen.add(key)
    else:
        result.append(line)
for key,value in values.items():
    if key not in seen:
        result.append(f"{key}={value}")
p.write_text("\n".join(result)+"\n")
p.chmod(0o600)
print("Fresh Django host, origin and secure cookie settings updated")
PY

# Recreate only the isolated Django WEB container (no DB or Dia restart).
# Its already-published host loopback 18081 is what Caddy will use.
if ! docker compose -f "$COMPOSE" up -d --no-deps web; then
  cp -p "$ENV_BACKUP" "$APP/.env"
  docker compose -f "$COMPOSE" up -d --no-deps web || true
  die "Fresh web could not be updated; .env restored, Caddy left unchanged"
fi
READY=0
for i in $(seq 1 50); do
  STATUS="$(curl --noproxy '*' -H "Host: $DOMAIN" --silent --max-time 4 --output /dev/null --write-out '%{http_code}' http://127.0.0.1:18081/login/ || true)"
  if [ "$STATUS" = 200 ]; then READY=1; break; fi
  sleep 2
done
if [ "$READY" != 1 ]; then
  cp -p "$ENV_BACKUP" "$APP/.env"
  docker compose -f "$COMPOSE" up -d --no-deps web || true
  die "Fresh web did not accept new domain; .env restored, original Caddy not touched"
fi

if [[ "$JSON" != *"$DOMAIN"* ]]; then
  cat >> "$CONFIG" <<'CADDY'

# BEGIN FOROSH SAMANEPANEL HOST-CADDY
forosh.filmjadiid.ir {
    encode zstd gzip
    reverse_proxy 127.0.0.1:18081
}
# END FOROSH SAMANEPANEL HOST-CADDY
CADDY
fi

restore_caddy() {
  echo "Restoring previous Caddyfile after validation/reload failure" >&2
  # In-place write keeps the same inode/permissions for any bind mount.
  cat "$CADDY_BACKUP" > "$CONFIG"
  caddy reload --config "$CONFIG" --adapter caddyfile || true
}
if ! caddy validate --config "$CONFIG" --adapter caddyfile; then
  restore_caddy
  die "Caddyfile validation failed; original Caddy restored"
fi
if ! caddy reload --config "$CONFIG" --adapter caddyfile; then
  restore_caddy
  die "Caddy reload failed; original Caddy restored"
fi

echo "HOST_CADDY_CONFIG_LOADED"
echo "PUBLIC_DOMAIN=https://$DOMAIN"
TLS_OK=0
for i in $(seq 1 8); do
  STATUS="$(curl --noproxy '*' --silent --max-time 8 --resolve "$DOMAIN:443:127.0.0.1" --output /dev/null --write-out '%{http_code}' "https://$DOMAIN/login/" 2>/dev/null || true)"
  if [ "$STATUS" = 200 ]; then TLS_OK=1; break; fi
  sleep 3
done
if [ "$TLS_OK" -eq 1 ]; then
  echo "FOROSH_HTTPS_READY=https://$DOMAIN/login/"
else
  echo "FOROSH_CADDY_CONFIGURED_TLS_NOT_YET_VERIFIED"
  echo "Check DNS, inbound 80/443, and Caddy ACME certificate logs."
fi
echo "Original host Caddy backup: $CADDY_BACKUP"
echo "Fresh env backup: $ENV_BACKUP"
echo "Existing Dia Gallery and other Docker containers were not modified."
docker compose -f "$COMPOSE" ps
