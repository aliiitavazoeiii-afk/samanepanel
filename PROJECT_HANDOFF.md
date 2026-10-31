# PROJECT HANDOFF — DARMA GENERAL

Last updated: 2026-08-26
Repository: `aliiitavazoeiii-afk/darma-general`
Default branch: `main`
Production domain: `gozaresh.filmjadiid.ir`
Production path: `/opt/darma-general`

This document is the detailed continuation record for a new AI/chat. Read `AI_START_HERE.md` first, then this file.

---

## 1. What this project is

This is a custom Django web application replacing the user's operational Excel workflow for an apparel business. It is intentionally simpler than a full ERP. The application covers:

- daily sales entry and Digikala XLSX imports;
- Darma and Takvin product catalog/pricing;
- finished-goods inventory split between HOME and KHORSHID;
- raw-material stock for fabric/elastic and tailor/depot flows;
- production/material reports;
- Digikala receivables, receipts, payments and Mellat balance;
- comprehensive report and capital calculation;
- Jalali dates/calendars;
- mobile-first true-glass UI;
- newer `انبارش` sales brand and dated Takvin accounting costs.

The user expects direct implementation in GitHub, then short VPS commands to deploy/test.

---

## 2. Production stack

- Django `>=5.2,<5.3`
- PostgreSQL 16 Alpine
- Gunicorn
- WhiteNoise
- psycopg binary
- Caddy HTTPS
- Docker Compose via `compose.yml`
- requirements include `jdatetime` and `holidays`

Main VPS commands generally run from:

```bash
cd /opt/darma-general
```

Never expose `.env` contents.

---

## 3. UI contract — do not regress

The user strongly prefers the current transparent navy true-glass UI. Do not revert to older opaque cards/Tahoma styling.

Core visual intent:

- dark navy background;
- translucent glass cards with blur/saturation;
- Vazirmatn font;
- orange accent;
- responsive/mobile shell;
- bottom navigation on mobile;
- horizontal scrolling/sticky cells for wide tables.

Money formatting uses Persian thousands separator `٬`; weights/quantities remain ordinary decimal values.

Relevant UI files include:

- `templates/base.html`
- `templates/core/_mobile_shell.html`
- `static/core/ui-polish.css`
- `static/core/number_format.js`
- `static/core/jalali_picker.js`

---

## 4. Current routing/source-of-truth map

Always inspect `core/urls.py` before assuming a historical version file is active.

Current main routes are wired approximately as follows:

- dashboard → `core.excel_dashboard.dashboard`
- sales calendar → `core.daily_views.sale_calendar`
- sale brand screen → `core.sale_brand_v17.sale_brand`
- sale size screen → `core.daily_views.sale_size`
- manual sale save → `core.excel_sales.sale_line_save`
- daily Digikala XLSX upload → `core.daily_order_views_v8.import_daily_orders`
- importer implementation → `core.daily_order_import_v12`
- daily report → `core.daily_report_v8.daily_report`
- comprehensive report → `core.report_v9.report`
- manual report edits → `core.report_v9.manual_report_action`
- materials report → `core.material_report_v16`
- payments/receipts → `core.business_tools_v14`
- inventory → `core.inventory_v5`
- inventory operations → `core.inventory_operations_v15`
- Takvin purchases → `core.takvin_v5`
- settings/products → `core.pricing_v7`
- settings/stock → `core.settings_stock_v5`
- settings/rules → `core.settings_rules_v17`

---

## 5. Critical safety rules

### 5.1 Never use destructive reset scripts casually

`server_inventory_fix.sh` is destructive. It resets business tables and must NEVER be used for routine UI, pricing, import, finance or reconciliation work.

Also avoid old full-reset commands such as `reset_and_load_darma_inventory` unless the user explicitly requests a full destructive rebuild after backup and understands the effect.

### 5.2 Never blindly fix Darma `-50` KHORSHID

Known anomaly:

`دارما / طوسی / XXL / KHORSHID = -50`

A previous attempted repair dry-run showed:

```text
HOME BEFORE = 43
KH BEFORE   = -50
TOTAL       = -7
Cannot repair safely: Home has 43, but 50 units are required.
```

Therefore do NOT run `server_fix_khorshid_negative_v15.sh` and do NOT simply move 50 HOME→KHORSHID.

The correct strategy is a fresh physical count of the complete Darma HOME and KHORSHID matrix, then a new end-of-day baseline reconcile.

### 5.3 Do not reuse the old v11 opening snapshot as a current stock target

The v11 snapshot was valid for its historical baseline before subsequent sales/production. It is not the current physical inventory.

### 5.4 Preserve accounting invariants

Internal transfers/conversions should not arbitrarily change total capital. Use transactions/rollback and pre/post audits.

---

## 6. Capital/accounting model

The intended comprehensive capital equation is:

```text
capital = accounts/persons
        + finished inventory
        + raw materials
        + Digikala receivable
        + assets
        - Takvin debt
```

Current v17 integrity checker uses `finished_inventory_value_v17()` for finished inventory valuation.

Important principle: cash moving into another owned asset should not change capital.

Examples:

### Digikala receipt

```text
Digikala receivable -X
Mellat +X
Capital: unchanged
```

### Raw-material purchase

```text
Mellat -X
Raw material inventory +X
Capital: unchanged
```

### Sale

```text
Finished inventory decreases by COGS
Digikala receivable increases by gross - Digikala fee
Capital increases by sale profit
```

Relevant files:

- `core/report_v9.py`
- `core/finance_excel_v9.py`
- `core/business_tools_v14.py`
- `core/inventory_valuation_v17.py`
- `core/management/commands/capital_audit_v9.py`
- `core/management/commands/check_capital_integrity_v14.py` (name is historical; logic is now v17-aware)

---

## 7. Finance v9+ details

### Automatic Digikala receivable

`core/finance_excel_v9.py` maintains sale-derived receivable entries.

Expected sale receivable per line:

```text
gross sale - Digikala fee
```

A Digikala receipt:

- creates a settlement record;
- reduces Digikala receivable;
- increases Mellat;
- deletion must reverse both sides atomically.

Historical issue: `daily_order_import_v8.py` deletes sale receivable entries inside import flow. The current outer import flow rebuilds them after inventory sync; do not reintroduce a window where they remain deleted.

---

## 8. Daily Digikala XLSX import

Current importer path: `core.daily_order_import_v12.py`, invoked by `core.daily_order_views_v8.py`.

Properties:

- reads XLSX using Python zip/XML, not pandas/openpyxl in production path;
- max file size 10 MB;
- only first worksheet;
- requires `عنوان` and `تعداد ارسالی`;
- ignores qty <= 0;
- rejects unknown/inactive rows before writing;
- uploaded file becomes the truth for that SaleDay;
- omitted existing lines are zeroed and inventory restored;
- replacement/idempotent behavior;
- finance receivable rebuilt after import;
- brand stock-total invariant must match expected sale delta or entire transaction rolls back.

Known return-only file that must never enter sales:

`packageDeliveryReport_17851669002377.xlsx`

### Size aliases

- `36-38` → M
- `38-40` → L
- `40-42` → XL
- `42-44` → XXL
- `44-46` → 3XL
- `46-48` → 4XL

### Darma aliases

Important aliases include:

- pack5 → `pack 5`
- rah110 → `rah-110`
- rah220 → `rah-220`
- op / op-bnw → `op`
- 06 / pack6 → `06`
- 110/220/... resolve to corresponding D codes where configured.

---

## 9. Darma variable-color `s3` — v12

This was added because Digikala lists a single-item Darma product where color is customer-selectable.

The site stores a Darma product code `s3`, pack quantity 1, with no fixed composition. Color is resolved per uploaded row.

Known seller-code hints are case-sensitive:

- `s2` = کرم
- `s3` = مشکی
- `S3` = صورتی
- `s5` = سرمه‌ای

White is also recognized from title text.

Title is authoritative. Example:

```text
شورت زنانه دارما مدل s3 | XXL | کرم | ...
```

must deduct one Darma XXL cream short.

Relevant files:

- `core/variant_sale_v12.py`
- `core/daily_order_import_v12.py`
- `core/management/commands/sync_s3_variant_v12.py`
- `core/management/commands/check_s3_variant_v12.py`
- `server_s3_variant_v12.sh`

Pack-1 price row was added to Darma bulk pricing because Digikala delivery XLSX does not contain sale price. Import must reject `s3` if applicable sale price is zero.

---

## 10. Product catalog

### Darma known catalog

Current intended Darma codes include:

`D 110`, `D 220`, `D 330`, `D 440`, `D 550`, `D 660`, `pack 5`, `880`, `990`, `770`, `p12`, `400`, `06`, `rah-110`, `pgw`, `rah-220`, `op`, plus variable-color `s3`.

Do not reintroduce old unwanted Darma `rah` or `blk` aliases as separate active products.

### Takvin known catalog

15 codes:

`12`, `987`, `06مشکی`, `سفید 09`, `502`, `4444`, `654-1`, `555-1`, `2222`, `1010`, `787`, `23`, `16`, `gg`, `403`

Takvin active sizes are M/L/XL/XXL; 3XL and 4XL are excluded.

---

## 11. Darma colors

Darma base color/model set:

- مشکی
- سفید
- سرمه ای
- صورتی
- کرم
- قرمز
- زرد
- طوسی
- راه راه
- راه راه طوسی
- برعکس مشکی
- برعکس سفید
- برعکس سرمه ای

`core/brand_colors.py` normalizes Arabic/Persian letter variants, spacing and ZWNJ.

---

## 12. Historical Darma v11 baseline

This is HISTORY ONLY, useful for forensic understanding.

v11 successfully reconciled Darma to:

- total 14,311 shorts
- total value 872,971,000 toman at 61,000

Per-size totals:

- M = 2,086
- L = 4,063
- XL = 2,968
- XXL = 4,074
- 3XL = 1,120
- 4XL = 0

Important historical target for `طوسی / XXL` was **-3**. This matters because the v11 reconcile algorithm only adjusted HOME while preserving KHORSHID. Therefore a pre-existing negative KHORSHID row could survive and HOME would be altered to make the combined target equal -3.

Relevant file:

`core/management/commands/reconcile_darma_excel_v11.py`

Do not run its `--apply` now as a current stock fix.

---

## 13. Darma 1405/06/01–03 stock audit

Read-only `audit_darma_stock_v15` produced:

```text
DAY 1405/06/01: expected_shorts=160 allocations=160 applied_shorts=160
DAY 1405/06/02: expected_shorts=282 allocations=282 applied_shorts=282
DAY 1405/06/03: expected_shorts=402 allocations=402 applied_shorts=402
TOTAL EXPECTED SOLD SHORTS = 844
TOTAL CURRENT ALLOCATIONS  = 844
TOTAL APPLIED SHORTS       = 844
SALE LINE MISMATCHES       = 0
```

Current Darma net at that audit:

```text
CURRENT NET QTY = 13467
CURRENT VALUE @61000 = 821487000
HOME = 13517
KHORSHID = -50
```

The `821,487,000` total was confirmed correct. The confusion came from treating `863,211,000` as pre-day-1 when it was already post-day-1:

```text
872,971,000 historical start
- 9,760,000 day 1 (160 shorts)
= 863,211,000

then day 2 + day 3 COGS:
282 + 402 = 684 shorts
684 * 61,000 = 41,724,000
863,211,000 - 41,724,000 = 821,487,000
```

So sales for all three days were correctly applied. The remaining problem is location/cell integrity, especially the old KHORSHID negative row.

---

## 14. Other negative Darma rows observed in that audit

At that time:

- HOME زرد M = -4
- HOME قرمز L = -37
- HOME قرمز XL = -29
- HOME قرمز XXL = -39
- HOME قرمز 3XL = -2
- KHORSHID طوسی XXL = -50

Do not independently zero these unless a physical count/reconcile explicitly establishes the correct matrix. Negative rows may reflect historical opening data, shortage behavior, or legacy reconcile logic.

---

## 15. Planned new physical Darma baseline

User decided the clean solution is to physically count complete inventory and provide accurate quantities for HOME and KHORSHID.

Desired workflow when that count arrives:

1. Treat it as authoritative end-of-day 1405/06/03 baseline.
2. Build a new safe full-matrix reconcile command, separate from v11.
3. Dry-run exact per-cell changes first.
4. Back up database.
5. Apply HOME and KHORSHID independently to match physical count.
6. Verify total quantity/value and capital effect.
7. From day 4 onward, sales/production operate from this baseline.

Do not assume the capital should remain exactly unchanged if the physical count proves historical accounting stock was wrong; show the valuation delta before applying and let the user approve/understand it.

---

## 16. Raw materials system

Raw materials cover fabric and elastic with warehouse/tailor/depot locations.

Important models/services:

- `RawMaterialStock`
- `MaterialReportBlock`
- `MaterialReportConsumption`
- `MaterialReportOutputApplied`
- `core/material_flow.py`
- `core/material_receipt_sync.py`
- `core/material_cost_v13.py`
- `core/material_purchase_v14.py`

Raw-material values contribute to capital.

---

## 17. Material report evolution and current v16 behavior

Earlier versions incorrectly coupled save/production/material consumption and caused capital/inventory inflation. v16 deliberately separates them.

Current behavior in `core/material_report_v16.py`:

### Save

`material_block_save` stores input/output data only. No material or finished-goods inventory effect.

### Apply materials

`material_block_apply_materials` syncs fabric/elastic consumption only. It does NOT add finished shorts.

This apply is idempotent/delta-based through `MaterialReportConsumption`: changing desired consumption from 20 to 22 should consume only +2 more.

### Unapply materials

`material_block_unapply_materials` reverses only raw-material consumption. It does not touch finished-goods receipts.

### Apply finished-goods output

`material_block_apply_output` uses `MaterialReportOutputApplied` per color/model × size.

Example:

```text
Day A: pink total entered 100 → apply → +100
Day B: pink stays 100, black becomes 100 → apply → +100 black only
Day C: pink increased 100→150 → apply → +50 pink only
```

Previously applied output is never re-added.

If a user edits a cell below its already-applied cumulative quantity, v16 rejects it instead of automatically deleting stock. Decreases require an explicit inventory correction workflow.

Finished output goes to KHORSHID.

### Delete

A material block with applied output cannot simply be deleted, preventing orphaned inventory reversal mistakes.

Deployment script:

`server_material_split_v16.sh`

Rollback branch:

`before-split-material-production-apply-v16`

Important: deployment of v16 was not explicitly confirmed in the conversation immediately before v17 work. Do not assume production server is on v16 without checking.

---

## 18. Raw-material purchase/payment integrity

v14 replaced fragile note-only inference with a more explicit purchase linkage/ledger approach.

Goal:

- paying fabric/elastic supplier decreases Mellat;
- purchased raw material is added to warehouse;
- net capital stays unchanged;
- deleting a purchase/payment must reverse both money and material together;
- if exact material quantity cannot be reversed safely, deletion must fail atomically instead of returning cash only.

Relevant files:

- `core/business_tools_v14.py`
- `core/material_purchase_v14.py`
- `core/management/commands/check_capital_integrity_v14.py`

---

## 19. Production cost accounting

Darma historical accounting cost had been 61,000/short, but newer production logic can calculate/model actual costs using fabric, elastic and sewing wage.

`InventoryModelCost` stores brand/color/size unit costs.

`core/cost_accounting_v14.py` snapshots actual sold-color cost for Darma where allocation data is available. SaleSnapshot freezes COGS at sale time.

This is critical: reports should use frozen sale snapshots and not recalculate old sales from today's costs.

---

## 20. v17 — `انبارش` sales brand

Current `main` includes v17 code.

Migration `0012_takvin_cost_rule_and_anbaresh.py` seeds active brand:

`انبارش`

`core/sale_brand_v17.py` orders sale cards:

1. دارما
2. تکوین
3. انبارش

`انبارش` uses the normal ProductCode/ProductSize/SaleLine flow. To actually enter Anbaresh sales, products and active sizes/prices/costs must exist under the `انبارش` brand.

Intent: goods the user deposits/warehouses separately can be recorded as `انبارش` and should appear in daily/comprehensive sales calculations with gross, Digikala fee, COGS, profit, packs and shorts just like other brands.

The daily report already iterates any brands not in the preferred Darma/Takvin order, so Anbaresh metrics flow through the generic sale metrics path.

### Inventory valuation for Anbaresh

`core/inventory_valuation_v17.py` values non-Takvin brands primarily from `InventoryModelCost`. If Anbaresh has no cost row for a color/size, it attempts an average ProductSize unit cost from active products containing that color/size.

When defining Anbaresh products, ensure unit costs are populated so capital valuation is meaningful.

---

## 21. v17 — date-effective Takvin cost rules

New model:

`TakvinCostRule(size, effective_from, unit_cost)`

Unique per `(size, effective_from)`.

Migration seeds a historical rule set effective 1400/01/01 equivalent date with:

- M = 108,000
- L = 126,000
- XL = 139,500
- XXL = 153,000

Settings route now uses `core.settings_rules_v17.settings_rules` and template `templates/core/settings_rules_v17.html`.

User can add a full price set with an effective Jalali date. For example, a new rule effective 1405/06/10 must affect sales from that date onward, not earlier sales.

`core/takvin_pricing_v17.py` resolves the latest rule `effective_from <= sale date`.

`core/cost_accounting_v14.snapshot_sale_line()` freezes the Takvin cost based on `line.day.date`, so later price changes do not rewrite historical sales.

Current inventory valuation uses the currently effective Takvin rule via `finished_inventory_value_v17()`.

---

## 22. v17 deployment status and script

Code is committed to `main`, but production deployment was not confirmed by a successful terminal output in this handoff.

Safe script:

```bash
cd /opt/darma-general
git pull --ff-only
bash server_anbaresh_takvin_v17.sh
```

The script:

- starts/health-checks DB;
- creates pg_dump backup;
- captures capital before;
- builds;
- checks migration drift;
- migrates;
- runs `check`, `check_excel_web`, `check_v17_features`;
- compares capital after migration;
- refuses to replace live web if capital unexpectedly changed;
- recreates web and restarts Caddy;
- runs final v17 and capital checks.

Expected terminal ending:

```text
SUCCESS: ANBARESH + TAKVIN PRICING V17 DEPLOYED
```

The script explicitly does NOT repair the old Darma `-50 gray/XXL Khorshid` row.

Rollback branch:

`before-anbaresh-takvin-pricing-v17`

---

## 23. Current v17 preflight

Command:

```bash
python manage.py check_v17_features
```

It verifies:

- active `انبارش` brand exists;
- Takvin M/L/XL/XXL each have at least one dated cost rule;
- current resolved Takvin costs are positive.

Current capital integrity checker was updated to v17 valuation and expects material routes to point strictly to `core.material_report_v16`.

---

## 24. Important current migrations

Latest known migrations:

- `0010_brand_color_cleanup.py`
- `0011_material_report_output_applied.py`
- `0012_takvin_cost_rule_and_anbaresh.py`

Any new model change must add a new migration; always run:

```bash
python manage.py makemigrations --check --dry-run
```

in deployment preflight.

---

## 25. Darma bulk pricing

`core/darma_pricing.py` supports pack groups 1/3/4/5/6.

Historical pack pricing configured:

Pack 3:

- M 385,000
- L 405,000
- XL 430,000
- XXL 455,000
- 3XL 470,000
- 4XL 495,000

Pack 4:

- M 485,000
- L 515,000
- XL 545,000
- XXL 570,000
- 3XL 610,000
- 4XL 630,000

Pack 5:

- M 570,000
- L 618,000
- XL 658,000
- XXL 701,000
- 3XL 743,000
- 4XL 790,000

Pack 6:

- M 699,000
- L 755,000
- XL 795,000
- XXL 860,000
- 3XL 920,000
- 4XL 980,000

Pack 1 is used for `s3`; prices must be explicitly set and cannot remain zero before imports containing `s3`.

---

## 26. Digikala fee logic

Current `core/finance.py` uses configurable settings for:

- commission rate (historically 24%);
- processing rate (historically 7%);
- processing floor (historically 36,000);
- VAT rate (historically 10%);
- floor-taxable processing part (historically 18,000).

Do not hardcode new fee assumptions elsewhere. Use `digikala_fee_for_unit()` and SaleSnapshot.

---

## 27. Daily report and comprehensive report

`core/daily_report_v8.py` aggregates sale metrics by brand generically.

Preferred ordering currently starts with Takvin/Darma logic in historical code, then includes additional brands; v17 brand input screen explicitly orders Darma/Takvin/Anbaresh.

`core/report_v9.py` uses actual allocations for Darma color-sales reporting where available, which is required for variable-color `s3` and replacement colors.

Do not go back to fixed ProductComposition-only color reporting for Darma sold colors.

---

## 28. Inventory operations v15

`core/inventory_operations_v15.py` contains manual transfer/adjustment UI logic.

A guard was added so a transfer cannot reduce the source stock below zero. This is meant to prevent future negative-location rows from manual transfers.

Legacy negative rows may still exist from old data/import/reconcile behavior and should be resolved by authoritative physical reconcile rather than hidden adjustments.

---

## 29. Known bad repair script that must not be run

`server_fix_khorshid_negative_v15.sh`

It was designed for a simplistic +50 KHORSHID / -50 HOME repair, but its own dry-run proved HOME had insufficient quantity. Keep it as historical diagnostic code only; do not execute apply.

---

## 30. Rollback branches currently confirmed in GitHub

Confirmed branch list includes:

- `before-anbaresh-takvin-pricing-v17`
- `before-split-material-production-apply-v16`
- `before-khorshid-negative-fix-v15`
- `before-capital-integrity-v14`
- `before-material-apply-purchases-v13`
- `before-s3-variable-color-v12`
- `before-daily-order-upload-v8`
- `before-bulk-pricing-v7`
- `before-excel-product-catalog-v6`
- `before-brand-colors-takvin-production-v5`
- `before-report-materials-payments-fix-v4`
- `before-material-flow-v3`
- `before-raw-materials-v2`
- `before-finance-flow-v9`
- `before-finance-tools`
- `before-darma-clean-reset`
- `erp-full-v1`
- `excel-web-before-true-glass`
- `true-glass-before-calendar`
- `true-glass-calendar-before-mobile`

Do not claim a `before-darma-reconcile-v11` branch exists; it was not created. A known clean pre-v11 commit historically referenced is `d0171e654fe6aa05478de0abf2b26819910283b1`.

---

## 31. Important deployment scripts

Use the version-specific safe script that matches the requested feature. Current useful scripts include:

- `server_anbaresh_takvin_v17.sh`
- `server_material_split_v16.sh`
- `server_capital_integrity_v14.sh`
- `server_material_apply_v13.sh`
- `server_s3_variant_v12.sh`
- `server_darma_reconcile_v11.sh` (historical snapshot only; do not apply now)
- `server_sales_fix_v10.sh`
- `server_finance_flow_v9.sh`
- `server_daily_order_import_v8.sh`

Dangerous/obsolete for current live data:

- `server_inventory_fix.sh`
- `server_fix_khorshid_negative_v15.sh` apply path

---

## 32. Useful audit/check commands

Non-destructive checks include:

```bash
python manage.py check
python manage.py check_excel_web
python manage.py check_finance_flow_v9
python manage.py check_capital_integrity_v14
python manage.py check_material_split_v16
python manage.py check_v17_features
python manage.py capital_audit_v9
```

Darma stock diagnostics:

```bash
python manage.py audit_darma_stock_v15 --from-j 1405/06/01 --to-j 1405/06/03 --opening-value 863211000
python manage.py trace_negative_darma_v15 --color "طوسی" --size "XXL"
```

These are diagnostics. Avoid modifying stock while investigating.

---

## 33. Deployment troubleshooting pattern

When a user pastes a failure:

1. Determine exactly which numbered script step failed.
2. If failure is preflight-only, distinguish code functionality from a stale checker expectation.
3. Patch the checker/script in GitHub rather than telling the user to bypass safety checks.
4. Re-run the same safe script.
5. Remember that if a script fails before `RECREATE LIVE WEB`, GitHub/build code may be correct while production is still running the old container.

This mattered before when v12/v13 scripts failed in verification/preflight and the live site remained old.

---

## 34. Known deployment history notes

### v11

Confirmed successfully deployed historically. It produced a backup named similar to:

`backups/before-darma-reconcile-v11-20260825-133641.sql`

At that time capital was reconciled to a clean baseline and Darma was 14,311 pieces / 872,971,000.

### v12–v17

Some versions were developed and scripts created, but not every version has explicit success-output confirmation in the conversation. New chat must not infer live state solely from `main`.

Use server output (`git rev-parse HEAD`, deployment script success, or active route/version checks) when exact live state matters.

---

## 35. Suggested server state check before continuing

If the new task depends on whether v16/v17 is live, ask user to run only a minimal safe check such as:

```bash
cd /opt/darma-general
git rev-parse HEAD
git log -1 --oneline
docker compose exec -T web python manage.py check_v17_features
```

If `check_v17_features` is unavailable in the live container, main has not been fully deployed there yet.

Do not start by altering data.

---

## 36. Next high-priority business/data tasks

### Physical Darma stock reconcile

Wait for user's full count of HOME and KHORSHID by color × size. Build a new v18-style baseline reconcile around that authoritative physical state.

Requirements for that future command:

- read-only dry-run default;
- print current/target/delta per location/cell;
- compute total quantity/value before and target;
- show exact capital delta implied by physical correction;
- pg_dump before apply;
- atomic transaction;
- record InventoryMovement adjustment references;
- verify no unspecified rows are silently changed;
- do not depend on v11 historical targets.

### Verify v16 material workflow on production

Before entering old material reports again, confirm Save, Apply Materials and Apply Output are visibly separated and delta-based on live site.

### Deploy/verify v17

If not already live, deploy using `server_anbaresh_takvin_v17.sh` and verify capital unchanged.

### Populate Anbaresh catalog

The brand is seeded, but useful sales require actual ProductCode/ProductSize configurations under `انبارش`. Determine exact products/costs with the user before bulk seeding.

---

## 37. Future Anbaresh implementation cautions

The current v17 work primarily creates the brand/card and generic accounting pathway. Do not assume Digikala XLSX rows automatically map to Anbaresh unless aliases/product titles/codes exist in importer catalog resolution.

If Anbaresh will be entered manually, normal ProductSize rows suffice.

If Anbaresh will come from Digikala XLSX, extend resolver mappings carefully and preserve existing Darma/Takvin/s3 behavior.

Anbaresh inventory must be valued from real cost data; avoid zero-cost products because that would understate capital and overstate profit.

---

## 38. Takvin pricing semantics

The new dated cost rule is **accounting cost**, not necessarily sale price.

Do not confuse:

- `default_sale_price` — sales price used for SaleLine when no custom price is entered;
- `TakvinCostRule.unit_cost` — COGS per Takvin short effective from a date.

A new cost rule must only affect sales snapshots created for dates at/after its effective date. Existing historical SaleSnapshots should remain frozen.

---

## 39. SaleSnapshot contract

SaleSnapshot is critical for historical stability:

- pack quantity snapshot;
- unit cost snapshot;
- Digikala fee per-unit snapshot.

`core/cost_accounting_v14.snapshot_sale_line()` is current helper.

Darma uses actual allocated colors when possible.
Takvin uses dated `TakvinCostRule` by SaleDay date.
Other brands use ProductSize/inventory cost fallback.

Do not implement reports that recalculate old COGS directly from current ProductSize cost if a snapshot exists.

---

## 40. User-facing workflow style

Implementation should remain straightforward:

- user enters daily operational data;
- automatic calculations happen behind the scenes;
- visible controls should explain whether an action is only Save or actually changes inventory;
- risky actions should require explicit separate buttons;
- repeated Apply must be idempotent/delta-based;
- avoid hidden side-effects.

This is especially important for materials/production because older coupling caused real confusion.

---

## 41. GitHub workflow expectations

When the user asks for a site change:

- inspect current files first;
- edit `main` directly unless there is a reason to stage separately;
- create a rollback branch before risky changes;
- add/update preflight management command when behavior is materially new;
- add a safe deployment script for multi-step DB/model changes;
- do not leave a feature with only code but no deployment path;
- when a script fails due to stale checks, fix the checks rather than asking the user to disable them.

---

## 42. Current documentation commit context

Before these handoff docs, v17 code on `main` included commits ending with:

- `d0b09348f7e05de01b46b345269194561c5afb23` — safe Anbaresh/Takvin v17 deploy script
- `2ee539b26985eed59b96a1537223ed463ad4429f` — align capital integrity checker with v17 valuation

`AI_START_HERE.md` was then added in commit:

- `010aabd67a9c8d607f09f98e5c21b64588b860af`

This handoff file itself is committed after that, so `main` HEAD will be newer.

---

## 43. Exact first instruction for a new AI

The new AI should be told:

> Open `aliiitavazoeiii-afk/darma-general`. Read `AI_START_HERE.md` first and then `PROJECT_HANDOFF.md` completely. Treat them as the continuation state. Inspect current `main` before editing. Do not reset or repair Darma inventory and do not run the old -50 Khorshid repair. First confirm whether v16/v17 is live if the next task depends on deployment state. Continue from the documented pending work.

---

## 44. Final invariant checklist before any data-changing deployment

Before changing production data, verify:

- DB backup exists and is non-empty;
- migration drift check passes;
- Django system check passes;
- relevant feature preflight passes;
- capital before is recorded when finance/inventory changes are involved;
- operation is atomic or has a clear rollback;
- finished inventory / raw materials / Digikala ledger changes are balanced as intended;
- no old snapshot baseline is being mistaken for current physical stock;
- live container is not replaced if safety checks fail;
- final capital/inventory audit matches the expected delta.

If any of these are unclear, investigate before applying.
