# 06 — DEPLOYMENT SAFETY AND RECOVERY

This file defines how changes must be deployed to the production VPS and how failures must be interpreted.

Last synchronized: 2026-08-29 after confirmed V37 live deployment.

---

## 1. Production location

Server project path:

```bash
cd /opt/darma-general
```

Production domain:

```text
gozaresh.filmjadiid.ir
```

Stack:

- Docker Compose
- PostgreSQL container
- Django/Gunicorn web container
- Caddy
- historical Telegram bot orphan container may appear as `darma-general-bot-1`

---

## 2. Never equate GitHub main with production

A commit existing on `main` does not mean production is running it.

For any statement like "this is live" require explicit evidence such as:

- user-posted successful deploy script output;
- live route/check output;
- explicit current production image verification.

The latest confirmed deployment in this context pack is V37. See `08_LIVE_STATE_AND_CHECKPOINTS.md`.

---

## 3. Standard safe deployment pattern

For changes that can affect business behavior, use a purpose-specific deployment script with this pattern:

1. `cd /opt/darma-general`
2. load `.env` safely without printing secrets;
3. start/check DB;
4. take full `pg_dump` backup;
5. capture live economic/inventory invariants;
6. build latest web image;
7. run `makemigrations --check --dry-run`;
8. run `python manage.py check`;
9. run feature-specific regression/preflight commands in one-off container;
10. verify preflight changed no persistent business values;
11. only then recreate live web;
12. restart/reload Caddy if needed;
13. rerun live checks;
14. capture final invariants;
15. require exact match for deployment-only changes;
16. print explicit SUCCESS marker.

If any step fails, do not tell the user to skip it. Diagnose the cause.

---

## 4. Database backup is mandatory before risky mutation

Typical backup pattern:

```bash
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "backups/before-<feature>-${STAMP}.sql"
```

Then verify backup file is non-empty.

A deployment script must not proceed with a destructive/data-changing command if backup failed.

---

## 5. Rollback branch discipline

Before a risky code phase, create a branch pointing to the exact pre-change commit.

Examples from project history:

```text
before-darma-physical-baseline-v18
before-saleonly-anbaresh-novani-material-v19
before-payment-metadata-settlement-v22
before-digikala-title-precedence-v25
before-daily-report-drilldown-v26
before-strict-title-resolver-v27
before-elastic-purchase-audit-v28
before-mordad31-darma-baseline-v31
before-day3-physical-stock-v32
before-novani-material-sizes-v33
before-novani-wage-v34
before-both-brand-output-edit-v35b
before-reverse-cut-display-v35c
before-ui-simplify-returns-v36
before-standalone-returns-calculator-v37
```

These branches are code rollback anchors, not database rollback substitutes.

For a data mutation, use the pg_dump from that exact operation if database restoration is required.

---

## 6. Do not casually run historical server scripts

This repo contains many versioned `server_*.sh` scripts that were designed for one specific migration/reconcile moment.

Examples of scripts that must not be used as generic repair tools:

- `server_inventory_fix.sh` — destructive; never routine.
- old v11 inventory baseline script — historical target only.
- `server_fix_khorshid_negative_v15.sh` apply — never run; superseded by physical baseline.
- old reset/reconcile scripts — only if their documented preconditions still match an explicitly requested forensic state.

Always read the entire script before execution.

---

## 7. The source code is baked into the web image

Production Compose behavior observed in this project means source is generally baked into the Docker image, not live bind-mounted for web runtime.

Consequences:

- `git pull` alone does not update the running web container;
- a one-off `docker compose run web ...` without `--build` can use an older image depending on state;
- when a newly created management command must run before live recreate, use a freshly built image.

Typical safe pattern:

```bash
docker compose build web
docker compose run --rm --entrypoint python web manage.py <command>
```

Or for a standalone diagnostic when current image is definitely stale:

```bash
docker compose run --rm --build --entrypoint python web manage.py <command>
```

---

## 8. Always override entrypoint for one-off management commands when needed

A historical V26 deploy bug used:

```bash
docker compose run --rm web ...
```

without overriding entrypoint. The temporary container started Gunicorn and appeared to hang forever instead of running/finishing the intended command.

Correct pattern:

```bash
docker compose run --rm --entrypoint python web manage.py <command>
```

For shell:

```bash
docker compose run --rm --entrypoint python web manage.py shell -c '...'
```

If an old one-off container is stuck because it launched Gunicorn, Ctrl+C is safe if no mutation was in progress, then clean up only the intended temporary container.

---

## 9. Orphan bot warning

Docker Compose frequently prints a warning like:

```text
Found orphan containers (darma-general-bot-1) ...
```

This is not, by itself, a failure.

Do **not** tell the user to run:

```bash
--remove-orphans
```

because the bot may be intentionally running outside the current compose service set.

Treat it as harmless unless the user explicitly wants to remove/change that bot.

---

## 10. Deployment-only changes should preserve business invariants exactly

For a pure UI/routing/build deployment, compare at least:

```text
capital
finished inventory value
raw material value
Digikala receivable
Darma quantity
Takvin quantity
Novani quantity
SaleLine count
AccountEntry count
```

V37 did this before build, after preflight/new image, and after live recreate.

If any changed during a deployment that was not intended to change business data, stop.

---

## 11. Feature tests must rollback their own test data

Regression commands often run a real transaction to verify accounting behavior.

Correct pattern:

```python
with transaction.atomic():
    # create small test movement
    # verify exact side effects
    transaction.set_rollback(True)
```

Then compare final snapshot to pre-test snapshot.

This catches errors that static source inspection cannot.

V37 return regression follows this pattern.

V36 operational roundtrip check tests payments/prepayments/receipts and rolls them back.

---

## 12. Atomic command failures mean earlier writes may have been rolled back

Do not assume partial changes after seeing several log lines.

Example: V30 reset printed that it was reversing payments, then failed reversing a consumed fabric purchase. Because the entire command was inside `transaction.atomic`, the database transaction rolled back and **none of the prior reset writes persisted**.

When user says "nothing changed", that can be exactly correct.

Always inspect transaction scope before proposing a second correction.

---

## 13. Read-only commands must truly be read-only

A diagnostic should not call helpers that use `get_or_create` or auto-heal state unless explicitly designed to do so.

During capital audit work, even helper functions that merely "read" a total were reviewed because some could create missing account/setting rows.

For a true forensic command:

- prefer direct QuerySets;
- avoid `get_or_create`;
- print `NO DATA CHANGED` marker;
- do not run migrations;
- do not call syncing services.

---

## 14. Avoid massive diagnostic output

A V29 audit appeared to hang because it printed hundreds of individual inventory movements. It was not CPU/database stuck; terminal output was huge.

For diagnostics:

- aggregate movement references;
- print totals/counts;
- optionally show first/last/sample rows;
- add flags for verbose output;
- keep the default result compact enough to reach the final interpretation marker.

If a command is clearly only printing huge read-only output, Ctrl+C is safe.

---

## 15. Server down after a bad one-off/deploy attempt

If the web server is unavailable:

1. do not start deleting containers indiscriminately;
2. SSH to VPS;
3. check `docker compose ps`;
4. start DB first;
5. inspect web logs/status;
6. if needed rebuild/recreate only web;
7. restart Caddy;
8. run Django check;
9. verify business invariants.

Reboot the VPS only when necessary, not as the first application-debugging step.

---

## 16. Data-reset commands need explicit scope

If the user requests a rebuild from a baseline:

- define exact date boundary;
- define exact tables/objects to reverse/delete;
- define whether payment effects are reversed or rebased/preserved;
- define whether physical/manual inventory adjustments are preserved;
- define whether Digikala receipts are reversed;
- define exact target inventory after reset;
- dry-run first;
- backup;
- apply atomically;
- verify final counts/totals.

Never write "delete all sales/payments" without stating what happens to their inventory/cash/receivable/material effects.

---

## 17. Physical baseline commands require no later sales if they are date-specific

A baseline like "31 Mordad end-of-day" or "3 Shahrivar end-of-day" must guard against later SaleDays being present if applying the baseline would overwrite subsequent business activity.

The safe sequence used in the forensic rebuild was:

1. remove/reverse later workflows;
2. apply exact historical baseline;
3. re-enter days sequentially;
4. audit after each day;
5. apply physical day-3 baseline;
6. continue day-by-day.

This is a debugging workflow, not a normal routine reset.

---

## 18. Current V37 deploy script behavior

`server_standalone_returns_calculator_v37.sh` is the latest confirmed live deployment script.

It protects against accidental formula drift by checking that V37 did not modify:

- `core/finance.py`
- `core/report_v9.py`
- `core/inventory_valuation_v17.py`
- `core/business_tools_v22.py`
- `core/material_report_v22.py`
- `core/final_services.py`

It also verifies:

- old daily return route removed;
- V37 standalone returns routes present;
- V37 calculator routes present;
- daily report returned to v21 template;
- exact existing Digikala fee engine still exists;
- capital equation unchanged;
- sidebar returns navigation injected;
- regression tests pass;
- pre/final business invariants match.

---

## 19. Confirmed successful V37 production output

The user posted the final production output:

```text
CAPITAL=5441972371
FINISHED=1115731500
RAW=1994448050
DIGI=812517154
DARMA=12072
TAKVIN=1195
NOVANI=3630
SALES=202
ACCOUNT_ENTRIES=206

SUCCESS: STANDALONE RETURNS + CALCULATOR V37 DEPLOYED
Backup: backups/before-standalone-returns-calculator-v37-20260829-205844.sql
```

This proves V37 was live at that point.

The backup filename is important if rollback of that deployment's data context is ever needed:

```text
backups/before-standalone-returns-calculator-v37-20260829-205844.sql
```

Do not restore it casually after later legitimate business activity; restoring a DB backup would erase later transactions.

---

## 20. New-change recommended template

For the next feature, prefer:

1. create branch `before-<feature>` at current main;
2. inspect exact active routes/files;
3. edit only necessary source scope;
4. create/update feature-specific regression command;
5. create `server_<feature>.sh` with backup + invariants;
6. user runs:

```bash
cd /opt/darma-general
git pull --ff-only
bash server_<feature>.sh
```

7. require posted SUCCESS before calling it live.
