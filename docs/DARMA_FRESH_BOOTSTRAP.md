# Samanepanel — Full Darma fresh copy (separate branch and database)

## What this does
The repository `aliiitavazoeiii-afk/samanepanel` hosts an independent branch
named `dia-darma-fresh`. A GitHub Actions bootstrap copies the **full source tree**
from `aliiitavazoeiii-afk/darma-general`, branch
`v126-payment-history-filters`, pinned commit
`90a79e993adced1689c70d5b0777ce2ea7f2789f`.

This is a new root commit (no Darma Git history and no production database).
It contains the Darma Django UI, models, views, templates and business logic.
Only source *seed-data migrations* are neutralized and startup skips `seed_base`
to keep the new business instance empty. One settings override permits access
through an SSH tunnel, and a new loopback-only Docker Compose file provides
an isolated PostgreSQL database.

Important: there is **no import of Darma's production database**, and there
is **no import of the 538 Samanepanel Digikala variants yet**. These will be
added later as the owner's business-specific data. Product/business names
inside the still-unmodified UI logic remain Darma-specific until adapted.

## GitHub bootstrap
Workflow: `.github/workflows/bootstrap-dia-darma.yml`

On a push changing the workflow or `deploy/darma-fresh/**`, it attempts to
create branch `dia-darma-fresh` if absent. Alternatively trigger the workflow
manually in GitHub Actions via **Run workflow**.

Before running the installer, verify that the branch exists:
https://github.com/aliiitavazoeiii-afk/samanepanel/tree/dia-darma-fresh

The workflow deliberately **never overwrites an existing branch**.

## Install on Dia Gallery server (root)
Requirements: git, python3, curl, openssl, iproute2 (`ss`), Docker and
Docker Compose plugin. Existing Dia Gallery website must keep its own
compose project, database and 80/443 ports.

```bash
curl -fsSL https://raw.githubusercontent.com/aliiitavazoeiii-afk/samanepanel/dia-darma-fresh/deploy/darma-fresh/install.sh -o /root/install-dia-darma-fresh.sh
bash /root/install-dia-darma-fresh.sh
```

The installer refuses to overwrite `/opt/dia-darma-fresh`, uses Docker Compose
project name `dia-darma-fresh`, uses dedicated PostgreSQL volume
`dia-darma-fresh_pgdata`, and binds the application only on
`127.0.0.1:18081` on the *server*. It creates `/opt/dia-darma-fresh/.env`
locally with new unique secrets. Never add it to Git.

On your computer:
```bash
ssh -N -L 18081:127.0.0.1:18081 root@SERVER_IP
```
While the tunnel is open, browse:
`http://127.0.0.1:18081/login/`.

## Do NOT run
- The upstream `deploy.sh`: it uses the Darma production hostname/path and
  takes host ports 80 and 443.
- The upstream default `compose.yml`: it includes a Darma-specific secret mount
  and a Caddy service binding 80/443.
- Any legacy `server_*.sh`, `reset_*.py` or reconciliation command.

## Safety checks after install
```bash
cd /opt/dia-darma-fresh
docker compose -f compose.fresh.yml ps
docker compose -f compose.fresh.yml exec -T web python manage.py check
docker compose -f compose.fresh.yml exec -T web python manage.py shell -c 'from core.models import SaleDay,ProductCode,Brand,StockBalance; print(SaleDay.objects.count(),ProductCode.objects.count(),Brand.objects.count(),StockBalance.objects.count())'
```

Expected business counts are all zero. Startup creates only generic stock
location keys and an independent Django administrator. On a blank database
some screens may not be usable until the new brand, products, accounts and
settings are entered.

This bootstrap **does not deploy itself** to any production server.
