# AI START HERE — DARMA GENERAL

Last updated: 2026-08-27
Repository: `aliiitavazoeiii-afk/darma-general`
Default branch: `main`
Domain: `gozaresh.filmjadiid.ir`
Server project path: `/opt/darma-general`

> ARCHIVE NOTE (added 2026-08-29): This is the exact older v19-era AI handoff snapshot preserved for forensic history. It is not the current continuation entrypoint. Current entrypoint is `/docs/00_NEW_CHAT_READ_FIRST.md`.

## 1. Read this before changing anything

This is a live Django business-management system used instead of Excel for an apparel business. The user expects the AI to edit GitHub directly and then give short copy/paste deployment commands for the VPS.

Before doing any work:

1. Read this file completely.
2. Read `PROJECT_HANDOFF.md` completely for older history.
3. IMPORTANT: where `PROJECT_HANDOFF.md` conflicts with the v18/v19 sections below, THIS FILE is newer and wins.
4. Inspect current `main` files relevant to the requested change; do not rely only on old version names.
5. Do not assume code on `main` is already deployed. Confirm live server state from user output when deployment status matters.
6. Make a rollback branch before risky changes when practical.
7. Never run destructive inventory/database reset scripts for normal changes.

## 2. Non-negotiable safety rules

- Never use `server_inventory_fix.sh` for routine changes. It is destructive and resets business data.
- Never rerun the old v11 Excel stock baseline as a current Darma target.
- Never run `server_fix_khorshid_negative_v15.sh` as an apply operation.
- The historical `طوسی / XXL / خورشید = -50` anomaly was NOT repaired in isolation. It was superseded by the user's complete physical HOME + KHORSHID count and the v18 physical-baseline reconcile.
- Preserve current capital/accounting state unless the requested operation intentionally changes it. Deployment scripts should compare capital before/after where possible.
- Prefer atomic/idempotent inventory operations and explicit ledgers over inference from notes/text.
- All sale/import inventory changes must preserve stock/accounting invariants and rollback on mismatch.
- Existing SaleSnapshots are historical accounting records. Never rewrite old snapshots just because current costs/rules change later.

## 3. Current architecture and active source-of-truth routes on `main`

- Django 5.2
- PostgreSQL 16 Alpine
- Gunicorn
- WhiteNoise
- Caddy HTTPS
- Docker Compose
- True-glass navy UI; do not regress it.
- Jalali dates throughout business workflows.

Current `main` routes are intended to point to:

- dashboard: `core.excel_dashboard`
- sale brand selection: `core.sale_brand_v19`
- manual sale save: `core.excel_sales`
- manual sale stock engine: `core.sale_inventory_v19`
- daily Digikala XLSX: `core.daily_order_views_v8` using `core.daily_order_import_v12`
- daily report: `core.daily_report_v8`
- comprehensive report/capital: `core.report_v9`
- material report: `core.material_report_v19`
- payments/receipts: `core.business_tools_v14`
- inventory: `core.inventory_v19`
- inventory operations: `core.inventory_operations_v15`
- settings/rules: `core.settings_rules_v17`

Always verify against `core/urls.py` before editing.

## 4. Accounting model

Capital is intended to remain:

`accounts/persons + finished inventory + raw materials + Digikala receivable + assets - Takvin debt`

Key rules:

- Digikala receipt moves value from receivable to Mellat; capital unchanged.
- Raw-material purchase exchanges Mellat for raw-material inventory; capital unchanged.
- Sale reduces finished inventory by COGS and increases Digikala receivable by gross minus fee; capital rises only by sale profit.
- Internal stock transfers do not create capital.
- SaleSnapshot freezes pack quantity, COGS/unit cost and Digikala fee at sale time.

Current finished-goods valuation helper remains `core.inventory_valuation_v17.finished_inventory_value_v17()`, but v19 semantics are important: `انبارش` is excluded as an independent inventory asset; `Novani` is included as a real inventory brand.

## 5. v18 — authoritative Darma physical baseline after 1405/06/03 sales

The user supplied complete physical counts for both Darma locations after the sales of 3 Shahrivar 1405. The count is an END-OF-DAY baseline: sales of 1405/06/03 must NOT be reapplied or changed.

Physical totals supplied:

- HOME = 4,585 shorts
- KHORSHID = 8,890 shorts
- TOTAL = 13,475 shorts

The old historical audit had 13,467 net shorts, so the physical correction was +8 shorts. At the then-current 61,000 accounting value this was +488,000 toman.

User-reported totals after applying the physical baseline were:

- inventory total = `3,129,524,600`
- capital total = `5,485,803,435`

These were mathematically consistent with the prior totals by exactly +488,000.

Relevant v18 files:

- `core/management/commands/reconcile_darma_physical_v18.py`
- `server_darma_physical_v18.sh`

Do not treat the old `-50` Khorshid cell as a pending isolated repair anymore. For future Darma stock corrections, use fresh physical evidence and explicit adjustments/reconcile logic.

## 6. v19 — Anbaresh is SALES-ONLY, backed by Darma stock

This section SUPERSEDES the older v17 handoff wording that described Anbaresh as a normal inventory brand.

Business rule:

- `انبارش` exists only in daily sales/reporting.
- It must NOT appear in the inventory page or inventory operations.
- The user warehouses only Darma goods through this channel.
- Entering Anbaresh manually must show the same active codes/sizes/default sale prices as Darma without defining a separate catalog by hand.
- Anbaresh SaleLines remain brand=`انبارش` so daily/comprehensive sales reports show Anbaresh separately.
- Physical goods for an Anbaresh sale are deducted from REAL Darma HOME/KHORSHID stock using the Darma-style auto-transfer/shortage logic.
- Therefore Anbaresh has no independent StockBalance asset and must never be added to capital as separate inventory.
- Anbaresh SaleSnapshot COGS is calculated from the actual Darma colors/costs allocated to that sale so reported profit equals the real capital movement.

Relevant v19 files:

- `core/anbaresh_catalog_v19.py` — mirrors Darma catalog into Anbaresh for manual sale UI only.
- `core/sale_brand_v19.py`
- `core/sale_inventory_v19.py`
- `core/excel_sales.py`
- `core/cost_accounting_v14.py`
- `core/inventory_valuation_v17.py`

### XLSX coexistence rule

The user may have BOTH Digikala orders and manual Anbaresh sales on the same date.

Therefore:

- Digikala XLSX resolver is intentionally limited to `دارما` and `تکوین`.
- It must never resolve mirrored Anbaresh codes or Novani.
- Replacement semantics of an uploaded XLSX apply only to Darma/Takvin lines.
- Manual Anbaresh SaleLines on the same SaleDay must remain untouched if they are absent from the XLSX.

Current implementation for this is in `core/daily_order_import_v12.py`.

## 7. v19 — Novani is a REAL inventory/production brand

Business rule:

- Brand name: `Novani`.
- Novani appears in the inventory page beside Darma and Takvin.
- Novani is NOT a daily-sale brand at this stage.
- Novani has one inventory bucket/table only; there is no visible HOME/KHORSHID split.
- Internally its stock uses HOME as the single storage location.
- Current Novani accounting cost is 61,000 toman per finished short for all seeded color × size rows.
- Novani stock contributes to finished inventory value and capital.

Migration `0013_saleonly_anbaresh_novani_material_brand.py` seeds Novani with Darma's base color set × sizes at quantity zero and InventoryModelCost=61,000.

Relevant files:

- `core/inventory_v19.py`
- `templates/core/inventory_v19.html`
- `core/inventory_operations_v15.py`

Only Darma can transfer HOME↔KHORSHID. Novani inventory adjustments are forced into its single HOME bucket.

## 8. v19 — material reports are brand-aware

This section SUPERSEDES the older v16 assumption that every finished output goes to Darma KHORSHID.

Each `MaterialReportBlock` now has a required `brand` and allowed workflow brands are:

- `دارما`
- `Novani`

Historical material reports are assigned to Darma by migration because all pre-v19 reports were Darma-era reports.

Behavior remains split/idempotent:

1. Save = data only; no stock effect.
2. Apply Materials = raw-material consumption only; no finished goods.
3. Apply Output = only the new cumulative delta not previously applied.

Destination rule:

- Darma output → Darma KHORSHID, preserving existing v14/v16 cost-blending behavior.
- Novani output → Novani's single inventory bucket, currently valued at 61,000/unit.

Once any output has been applied for a material report, changing that report's brand is blocked to prevent moving historical production between brands silently.

Relevant files:

- `core/material_report_v19.py`
- `templates/core/material_report_v19.html`
- `MaterialReportBlock.brand`
- migration `0013_saleonly_anbaresh_novani_material_brand.py`

## 9. Takvin dated accounting costs remain v17

Takvin accounting cost is date-effective via `TakvinCostRule` and is distinct from sale price.

Default historical seed:

- M = 108,000
- L = 126,000
- XL = 139,500
- XXL = 153,000

`settings_rules_v17.py` can add a new full cost set with a Jalali effective date. `snapshot_sale_line()` freezes the rule effective on the SaleDay date. Never recalculate old sales from today's Takvin cost.

## 10. Darma s3 variable-color import remains v12

`Darma s3` is pack-1 and its sold color comes from the Digikala title/seller hint, not fixed ProductComposition.

Case-sensitive known hints:

- `s2` = کرم
- `s3` = مشکی
- `S3` = صورتی
- `s5` = سرمه‌ای
- white can also be recognized from title.

The XLSX importer must continue preserving this behavior.

## 11. v19 deployment status and safe script

Current `main` contains v19 code, but DO NOT claim it is live until the user shows successful VPS output.

Rollback branch:

`before-saleonly-anbaresh-novani-material-v19`

Safe deploy script:

```bash
cd /opt/darma-general
git pull --ff-only
bash server_saleonly_anbaresh_novani_v19.sh
```

The script intentionally guards before migration:

- DB backup must succeed.
- live web must be available to establish before-state.
- legacy Anbaresh stock quantity must be zero; otherwise deployment stops.
- legacy positive Anbaresh SaleLines must be zero; otherwise deployment stops for explicit reconciliation.
- Darma stock total is captured before migration and must be unchanged after migration.
- capital is captured before migration and must be exactly unchanged after metadata migration.
- migration drift/system/template/v19/capital checks must pass before live web is replaced.

Expected successful ending:

`SUCCESS: SALE-ONLY ANBARESH + NOVANI + MATERIAL BRAND V19 DEPLOYED`

Do not bypass these guards if the script fails. Diagnose the exact reason and patch safely.

## 12. Deployment discipline

For model/data-affecting changes:

- pg_dump first;
- `makemigrations --check --dry-run`;
- migrate in a fresh container;
- run relevant preflight management commands;
- compare expected capital/inventory before and after;
- do not recreate live web if a safety check fails;
- then recreate web/restart Caddy;
- run final live audits.

Useful current checks at that historical snapshot included:

```bash
python manage.py check
python manage.py check_excel_web
python manage.py check_v17_features
python manage.py check_v19_features
python manage.py check_capital_integrity_v14
python manage.py capital_audit_v9
```

## 13. User workflow expectations

- Keep UI simple and Excel-like, not ERP-heavy.
- Edit GitHub directly when implementation is requested.
- Give short copy/paste VPS commands.
- Do not ask for facts already available in repo/handoff.
- Diagnose pasted deployment errors from the exact failing step; do not ask user to bypass safeguards.
- Preserve true-glass styling and mobile behavior.
- Money uses Persian thousands separator `٬`; quantities/weights use normal decimals.

## 14. Immediate next state at this archived v19 snapshot

At the time of the old update:

- v18 physical Darma baseline was the authoritative post-1405/06/03 stock baseline.
- v19 code was on `main` and awaited confirmed safe deployment output.
- after v19, user intended to create/use a Novani material report for five fabric rolls currently belonging to Novani.
- Anbaresh was manual daily-sale only and could coexist with Digikala XLSX orders on the same date.

This archived "immediate next state" is now obsolete; current state is V37 and is documented in `docs/PROJECT_CONTEXT/08_LIVE_STATE_AND_CHECKPOINTS.md`.
