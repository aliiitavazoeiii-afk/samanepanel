# DARMA GENERAL — NEW CHAT READ FIRST

**AUTHORITATIVE CONTINUATION ENTRYPOINT — READ THIS FILE COMPLETELY BEFORE TOUCHING CODE OR DATA**

Last continuation synchronization: **2026-10-04 through V108 final stable baseline built on the complete V106/V105 lineage**.

Repository: `aliiitavazoeiii-afk/darma-general`

Production domain: `gozaresh.filmjadiid.ir`

Production server path: `/opt/darma-general`

Default branch: `main`

Functional-code head immediately before this handoff-document synchronization: `226c300ee0fe74999a409847537fbc8d1ed4c163`.

## V102 CURRENT CONTINUATION

After this entrypoint, read **every numbered file** in `docs/PROJECT_CONTEXT/` through `57_FINAL_STABLE_BASELINE_V108.md`.

Current GitHub development line: `stable-final-2026-10-04`.

V108 final-baseline rule: after `SUCCESS: FINAL STABLE BASELINE V108 DEPLOYED`, every new feature branch must start from `stable-final-2026-10-04`; never resume work from an older V97-V107 branch.

For Finance, V102 supersedes the sibling V101 branch: the sidebar has one direct `مالی و ابزار` root, and `/finance/` contains exactly three cards (Payments, Accounts, Calculator). V103 makes that link native in `base.html`. Do not restore an expandable Finance submenu unless the user explicitly changes this rule. The accidental sibling `v102-person-payments-three-deliveries` was based on obsolete V101 and must never be used as the continuation base.

V102 also makes `current_capital_breakdown()` the single current-capital calculator consumed by Comprehensive Report. The capital equation itself is unchanged.

This application is a live business system replacing the user's Excel workflow. It contains real sales, finished inventory, raw material, receivables, accounts, production, payment, cost and capital data. A cosmetic-looking mistake can corrupt accounting or physical stock if an AI changes the wrong layer. Do not improvise.

---

# 0. SOURCE AUTHORITY — NEVER GUESS WHEN SOURCES CONFLICT

Use this priority order:

1. the user's explicit current business rule;
2. current physical evidence/uploaded source for the requested event;
3. structured ledgers/history such as `SaleAllocation`, purchase ledgers, `MaterialReportOutputApplied`, `InventoryMovement`, etc.;
4. current active code and live DB aggregate state;
5. the newest `docs/PROJECT_CONTEXT/` document that explicitly supersedes an older rule;
6. older handoff/history docs;
7. assumption/inference only as the last resort.

Never silently reconcile two conflicting sources. State the conflict before any mutation.

GitHub `main` is **not** proof that production runs that code. Production is confirmed only by user-posted successful deploy output or direct live evidence. Never say a revision is live merely because it exists in GitHub.

---

# 1. MANDATORY READING ORDER FOR A NEW CHAT

Before changing anything, read in this order:

1. this file completely;
2. `docs/PROJECT_CONTEXT/01_BUSINESS_RULES_AND_INVARIANTS.md`;
3. `02_ACCOUNTING_FORMULAS_AND_LEDGER_SEMANTICS.md`;
4. `03_ACTIVE_CODE_MAP.md`;
5. `04_SALES_DIGIKALA_AND_RETURNS.md`;
6. `05_INVENTORY_MATERIALS_PRODUCTION_PAYMENTS.md`;
7. `06_DEPLOYMENT_SAFETY_AND_RECOVERY.md`;
8. `07_BUG_HISTORY_AND_DO_NOT_REPEAT.md`;
9. `08_LIVE_STATE_AND_CHECKPOINTS.md`;
10. `09_UI_AND_USER_WORKFLOW_CONTRACT.md`;
11. `10_EXACT_BASELINES_CATALOG_AND_SPECIAL_CASES.md`;
12. `11_DATA_MODEL_AND_LEDGER_RELATIONSHIPS.md`;
13. `12_VERSION_TIMELINE_V18_TO_V37.md`;
14. `13_NEW_CHAT_OPERATING_PROTOCOL.md`;
15. `14_HANDOFF_SCOPE_AND_COMPLETENESS.md`;
16. `15_CODE_FINGERPRINT_AT_HANDOFF.md`;
17. `16_UI_MODERNIZATION_V38.md`;
18. `17_LOGO_TYPOGRAPHY_V39.md`;
19. `18_DIGIKALA_API_V40.md`;
20. `19_DIGIKALA_DELIVERIES_V41.md`;
21. `20_DIGIKALA_FREE_WAREHOUSE_V42.md`;
22. `21_DIGIKALA_CENTER_V43.md`;
23. `22_DIGIKALA_CENTER_V44.md`;
24. `23_DIA_GALLERY_V45.md`;
25. `24_NO_AUTO_TRANSFER_V46.md`;
26. `25_BLACK_RED_UI_V47.md`;
27. `26_DAILY_REPORT_STABILITY_V48.md`;
28. `27_INVENTORY_OPERATIONS_V49.md`;
29. `28_INVENTORY_OPERATIONS_V50.md`;
30. `UI_SAFETY_V37.md` through `UI_SAFETY_V47.md`;
31. current `core/urls.py`;
32. exact active source/template files for the subsystem being changed;
33. `AI_START_HERE.md` and `PROJECT_HANDOFF.md` only at the end for historical rationale.

Older numbered docs can contain statements superseded by later explicit rules. In particular, any older sentence saying sales may automatically transfer KHORSHID -> HOME is obsolete; V46 is authoritative.

---

# 2. NON-NEGOTIABLE IMPLEMENTATION PROTOCOL

Before code change:

1. identify the subsystem;
2. re-read current `core/urls.py` and resolve the active route/module;
3. read the relevant context docs;
4. fetch the exact current source and templates from GitHub;
5. identify invariants affected;
6. classify the request as UI-only, operational, accounting, or data-reconcile;
7. edit only after the above.

For any business/data-affecting work:

- create/verify a rollback branch at the exact pre-change commit;
- take a PostgreSQL `pg_dump` before mutation;
- use `transaction.atomic()` for multi-row accounting/stock operations;
- use delta/idempotent synchronization, not blind additive writes;
- run `python manage.py makemigrations --check --dry-run`;
- run `python manage.py check`;
- run feature-specific regression tests;
- compare before/after economic invariants;
- never bypass a failing guard merely to finish deployment;
- never use `--remove-orphans` because of the Docker orphan warning alone;
- never run historical reset/reconcile scripts casually.

The source is baked into the web image. `git pull` alone does not update the running application. Safe deploy normally rebuilds/recreates web.

One-off Django commands should use an explicit entrypoint, e.g.:

```bash
docker compose run --rm --entrypoint python web manage.py <command>
```

Do not use a plain `docker compose run web ...` when the image entrypoint starts Gunicorn.

---

# 3. CANONICAL CAPITAL / ACCOUNTING FORMULAS — FROZEN UNLESS USER EXPLICITLY CHANGES THEM

## 3.1 Capital equation

The structural equation remains:

```text
capital = accounts/persons
        + finished inventory
        + raw materials
        + Digikala receivable
        + assets
        - Takvin debt
```

After Dia Gallery V45, Dia receivable is included **inside the accounts component**, not as a separate new top-level capital term:

```text
accounts_total = manual accounts/persons + dia_gallery_receivable

capital = accounts_total
        + finished_inventory
        + raw_materials
        + digikala_receivable
        + assets
        - takvin_debt
```

Never edit a displayed capital number directly to make totals match. Find the wrong component/ledger.

The editable comprehensive-report Digikala field means **desired current total**, not raw opening/base. When the user enters the desired current Digikala receivable:

```text
stored_base = desired_current_total - current_ledger_total
current_receivable = stored_base + current_ledger_total
```

## 3.2 Normal sale line economics

Canonical helper: `core.finance.sale_line_metrics()`.

```text
gross = packs * sale_price_per_pack
fee = packs * frozen_or_current_fee_per_pack
shorts = packs * frozen_or_current_pack_qty
COGS = shorts * frozen_or_current_unit_cost
profit = gross - fee - COGS
```

Correct sale balance-sheet movement:

```text
finished inventory  -= COGS
Digikala receivable += gross - fee
capital delta        = gross - fee - COGS = profit
```

A sale is not a cash receipt. Cash changes only when an explicit settlement/receipt is recorded.

## 3.3 Exact Digikala fee engine

Canonical function: `core.finance.digikala_fee_for_unit(sale_price)`.

Defaults/configuration:

```text
commission_rate    = 24%
processing_rate    = 7%
processing_floor   = 36,000 toman
VAT_rate           = 10%
floor_taxable_part = 18,000 toman
```

Exact computation:

```text
commission = sale_price * commission_rate
raw_processing = sale_price * processing_rate

if raw_processing < processing_floor:
    processing = processing_floor
    taxable_processing = floor_taxable_part
else:
    processing = raw_processing
    taxable_processing = processing / 2

VAT = (commission + taxable_processing) * VAT_rate
fee = round_toman(commission + processing + VAT)
```

Never replace this with a simple percentage approximation.

## 3.4 SaleSnapshot

`SaleSnapshot` freezes historical accounting inputs, including:

- pack quantity;
- unit cost / COGS basis;
- Digikala fee unit.

Old sales must not be recalculated using new fee/cost/composition settings. `sale_line_metrics()` uses snapshot values when they exist and falls back to current values only when a snapshot field is absent.

## 3.5 Digikala receipt

A Digikala receipt is an owned-asset transfer:

```text
Digikala receivable -= X
Mellat               += X
capital               unchanged
```

Delete/edit must reverse both sides atomically. Never delete only the receipt row.

## 3.6 Internal HOME/KHORSHID transfer

```text
source -= q
destination += q
combined quantity unchanged
finished value unchanged
capital unchanged
```

## 3.7 Physical inventory adjustment/reconcile

A physical correction is different from an internal transfer and may legitimately change capital because the owned quantity has changed. Do not compensate with a fake finance entry merely to preserve the previous capital number.

## 3.8 Material purchase with goods

```text
Mellat -= actual_paid
raw material inventory += invoice/goods value
capital delta = goods_value - actual_paid
```

Actual paid is allowed to differ from invoice value.

Historical example:

```text
elastic16: 5 kg * 2,600,000 = 13,000,000
elastic25: 5 kg * 2,600,000 = 13,000,000
goods value = 26,000,000
actual paid = 25,584,000
capital delta = +416,000
```

## 3.9 Material prepayment without goods

```text
Mellat -= X
supplier prepayment asset += X
capital unchanged
```

## 3.10 Sewing wage

Confirmed rule:

```text
110,000 toman per 12 delivered pieces
```

Wage is based on cumulative **delivered finished pieces**, not cut quantity.

For cumulative output changing from old to new:

```text
wage_change = wage_for_pieces(new) - wage_for_pieces(old)
```

Positive wage change reduces tailor balance; negative wage change restores it. Cumulative piece ledgers prevent double application.

---

# 4. BRAND, SIZE, LOCATION AND INVENTORY CONTRACTS

## 4.1 Darma

- real finished inventory asset;
- active sizes: `M, L, XL, XXL, 3XL, 4XL`;
- physical locations: HOME + KHORSHID;
- material-report production output goes to KHORSHID;
- normal sale/accounting cost historically often 61,000, but current per-cell/model valuation may override; inspect valuation code before assuming a permanent constant.

## 4.2 Takvin

- real inventory/sales brand;
- active sizes: `M, L, XL, XXL`;
- date-effective sale cost through `TakvinCostRule` and `SaleSnapshot`;
- Takvin debt is a liability subtracted from capital.

## 4.3 Novani

- real production/inventory brand;
- current sizes: `S, M, L, XL, XXL, 3XL`;
- one logical inventory bucket represented internally by HOME;
- no visible HOME/KHORSHID split;
- material-report output goes to Novani's own inventory;
- output must never touch Darma.

## 4.4 Anbaresh

- sales channel only;
- not an independent inventory asset;
- physical stock comes from Darma;
- its manual SaleLines survive Digikala XLSX replacement on the same day;
- never value Anbaresh StockBalance as separate capital.

---

# 5. V46 AUTHORITATIVE LOCATION RULE — NEVER REINTRODUCE AUTO-TRANSFER

The user explicitly changed the business rule in V46:

```text
EVERY Darma-backed sale -> subtract HOME only
HOME may become negative
KHORSHID sale delta = 0
```

This applies to:

- normal Darma sales;
- Anbaresh sales backed by Darma stock;
- variable-color `s3`;
- replacement-color paths;
- Dia Gallery.

Physical KHORSHID -> HOME movement happens only when the user explicitly records a manual transfer.

Example:

```text
HOME = 5
sale = 15
HOME after = -10
KHORSHID unchanged
```

Then later the user physically transfers 30:

```text
HOME = -10
KHORSHID = 50
manual transfer 30
HOME after = 20
KHORSHID after = 20
```

Do not put automatic replenishment back into sales/import logic even if HOME is negative and KHORSHID has stock.

V46 historical repair uses the authoritative end-of-day 3 Shahrivar physical baseline and reverses only post-baseline phantom `auto-transfer` / `replacement-transfer` movements. It is idempotent via `v46-reverse-auto:<source_id>` references.

Observed first V46 repair result:

```text
HOME=2620
KHORSHID=8890
COMBINED=11510
SUCCESS: V46 REVERSED 19 PHANTOM AUTO-TRANSFER UNITS
```

The first deploy shell then incorrectly failed its final economic guard because Django shell printed an automatic-import banner whose object count changed (e.g. 54 vs 55). The repair itself had already committed. The guard was corrected to compare only explicit `KEY=value` invariant lines. Do not undo those 19 units.

Formal full V46 deployment must still not be claimed from docs alone unless the final success marker was posted; behavioral/live evidence exists but formal marker history is incomplete.

---

# 6. AUTHORITATIVE PHYSICAL / FORENSIC INVENTORY HISTORY

End-of-day 3 Shahrivar physical Darma baseline:

```text
HOME      = 4,585
KHORSHID  = 8,890
TOTAL     = 13,475
```

Per-size totals:

```text
M=1,948
L=3,807
XL=2,529
XXL=3,716
3XL=1,071
4XL=404
```

Later audited sales after that baseline:

```text
1405/06/04 Darma = 302
1405/06/05 Darma = 471
1405/06/07 Darma = 633
1405/06/09 Darma = 562
```

One non-sale adjustment after baseline:

```text
صورتی / 3XL / HOME / +3
```

Combined arithmetic:

```text
13,475 - 302 - 471 - 633 - 562 + 3 = 11,510
```

The white M investigation proved the final V32 baseline was the correct source, not a remembered intermediate UI number:

```text
end day3 HOME white M = 150
04 Shahrivar -18 => 132
05 Shahrivar -17 => 115
07 Shahrivar -21 => 94
09 Shahrivar -20 => 74
KHORSHID white M = 120
combined white M = 194
```

Do not force a remembered 59 onto the DB; 74 HOME was consistent with the physical baseline plus audited sales.

---

# 7. SALES / DIGIKALA XLSX CONTRACT

Active Digikala XLSX mutation flow remains:

```text
daily_order_views_v8
-> daily_order_import_v23.apply_delivery_report
```

Rules:

- title is authoritative for product identity;
- seller code is intentionally discarded and must not regain precedence;
- import replacement is authoritative only for Darma/Takvin on that SaleDay;
- existing manual Anbaresh lines on that day must survive;
- omitted existing Darma/Takvin lines become target quantity zero and are reversed through normal sale sync;
- operation is atomic;
- actual historical colors come from `SaleAllocation` when available;
- do not recompute old physical colors from today's ProductComposition.

Critical title resolver bug not to repeat:

A Digikala row with seller code `rah220` but title `D-220` was once misclassified as `rah-220`. Title-first V27 fixed this permanently.

Darma code `06` composition is:

```text
مشکی
سفید
سرمه ای
صورتی
کرم
طوسی
```

Do not reintroduce the old erroneous red component.

Variable color hints include case-sensitive historical mapping:

```text
s2 = کرم
s3 = مشکی
S3 = صورتی
s5 = سرمه‌ای
```

Lowercase `s3` and uppercase `S3` are not interchangeable.

Known return-only XLSX filename `packageDeliveryReport_17851669002377.xlsx` must never be imported as normal daily sales.

---

# 8. DIGIKALA OPEN API V40-V44 — READ-ONLY BUSINESS BOUNDARY

Authentication is complete. Runtime access/refresh tokens are mounted under `/run/secrets/digikala`; RSA private key remains outside the web container.

Only GET/read business endpoints are currently allowed by the integration design. Auth refresh is the allowed POST exception. Do not add write mutations merely because the external API may support them.

Initial observed endpoint status:

```text
orders               HTTP 200
order_statistics     HTTP 200
inventory            HTTP 200
profile              HTTP 200
commitments          HTTP 200
commitment_meta      HTTP 200
invoices             HTTP 200
insight              excluded after errors
sales_reports        validation/fallback work needed
```

V41 commitment interpretation:

```text
variants = 69
nextDays = 201
today = 0
delayed = 1
all commitments = 202
metadata effective commitments = 201
```

Headline "باید تحویل بدهم" = effective commitments = 201. Do not subtract `onTheWay` from that seller-panel semantics.

Business fact from user:

> Digikala fulfills every order from Digikala warehouse first if that variant is available there; only when DK warehouse stock is unavailable does the order become seller delivery commitment.

V42 free/sellable Digikala warehouse formula:

```text
sellable_dk_physical = max(0, available - marketplace_seller_stock + reserve)
seller_commitment = commitment.all (default 0)
requested_dk_reserve = max(0, reserve - seller_commitment)
reserved_from_stock = min(sellable_dk_physical, requested_dk_reserve)
free_stock = max(0, sellable_dk_physical - reserved_from_stock)
reserve_over_stock = max(0, requested_dk_reserve - sellable_dk_physical)
```

Do not use `warehouse_stock - reserve`.

V44 corrections:

- future commitment split uses cumulative `to_commitment_date` cutoffs;
- products derive from inventory rows grouped by DKP rather than only newly-created product endpoint behavior;
- returns are detected from nested warehouse titles containing `مرجوعی`;
- shared filesystem cache is used across Gunicorn workers;
- bounded concurrent pagination; no heavy polling on the tiny VPS;
- Digikala home should remain API-light.

---

# 9. DIA GALLERY V45

Dia Gallery is a sales channel for Darma physical goods, not a new inventory brand.

Rules:

```text
one entered unit = one Darma short
fixed sale price = 71,000 toman per short
Digikala fee = 0
receivable account key = dia_gallery
account title = فروش Dia Gallery
```

For each Dia sale:

```text
gross = quantity * 71,000
COGS = quantity * frozen Darma unit_cost
profit = gross - COGS
Dia receivable += gross
Darma HOME stock -= quantity   (V46 location rule)
capital delta = gross - COGS
```

Dia sales are stored separately from `SaleLine`, so Digikala XLSX replacement must never erase them. Dashboard/daily/comprehensive reporting should include Dia sales according to V45 behavior. No settlement workflow was defined unless the user later explicitly requests one.

---

# 10. RETURNS V37

Active standalone page: `/returns/`.

Two modes:

1. by color = loose shorts;
2. by code = complete fixed-composition packs.

Effect is HOME-positive inventory only:

```text
finished inventory += returned stock value
capital += same value
```

Must not create/change:

- SaleLine;
- SaleSnapshot;
- Digikala fee;
- Digikala receivable;
- AccountEntry;
- raw material;
- cash/bank.

Old daily-report return box was retired and must not be reintroduced unless explicitly requested.

---

# 11. MATERIAL / PRODUCTION / PAYMENT CONTRACTS

Material-report workflow is deliberately split into three independent actions:

1. Save form data only;
2. Apply Materials = synchronize raw-material consumption only;
3. Apply Output = synchronize cumulative finished output + sewing wage only.

Never merge these into one implicit save.

Darma output destination: KHORSHID.

Novani output destination: Novani single HOME bucket.

`MaterialReportOutputApplied` is the cumulative idempotency ledger per block/model/size. For each output cell:

```text
target = entered cumulative delivered qty
done = already-applied quantity
delta = target - done
```

- delta > 0: add only difference;
- delta = 0: no-op;
- delta < 0: reverse only reduction after validation.

All affected rows must be prevalidated/locked so a failed reduction does not partially mutate stock/wage.

Raw-material purchase provenance must come from purchase ledger/movement history, not aggregate-row note text.

Elastic variants 16 and 25 are separate:

```text
q16/p16
q25/p25
```

Never sum both quantities into each variant.

BusinessPayment V22 delete/update must use guarded reverse paths. Do not raw-delete a payment row if physical/cash effects cannot be reversed safely.

---

# 12. LAST NUMERICALLY CONFIRMED PRODUCTION CHECKPOINT

The last **fully numeric deploy checkpoint actually posted with a formal successful invariant block** remains V38:

```text
CAPITAL=5430972371
FINISHED=1115731500
RAW=1994448050
DIGI=812517154
DARMA=12072
TAKVIN=1195
NOVANI=3630
SALES=202
ACCOUNT_ENTRIES=206
```

Backup:

```text
backups/before-ui-modernization-v38-20260829-223111.sql
```

These numbers are forensic checkpoints, **not permanent targets**. Later legitimate business activity changes them. Never restore/force them merely because they are documented.

V37 capital was 5,441,972,371 while the V38 boundary was 5,430,972,371. The -11,000,000 difference happened before the V38 UI deploy and was not caused by V38; the V38 guard proved before/after equality during the deploy.

---

# 13. COMPLETE CURRENT-CHAT CHRONOLOGY — 2026-09-03 HANDOFF

This section records the work and mistakes/diagnostics from the current chat so the next chat does not repeat them.

## 13.1 Dashboard/UI attempt and rollback

The user initially wanted the actual site dashboard built in a sleek black/red glass style matching a prior visual concept, with real data, red Darma logo, red-glow sidebar, top-selling colors, sales chart, recent orders, inventory cards, and top KPI cards including monthly profit instead of Digikala cost. The user explicitly said not to generate more images and to build the site/code.

During this attempt an incorrect assumption was made that templates were under `core/templates`. Production/project settings actually use root-level:

```text
templates/
static/
```

not `core/templates`.

The user executed a rollback-like command:

```bash
git checkout HEAD~1 -- core/templates static/core
docker compose restart web
```

Because `core/templates` does not exist, that path assumption was wrong. The user later stated the UI had returned to the older navy/sormei look and explicitly said to leave UI alone. **Current instruction: do not resume black/red dashboard redesign unless the user asks again.**

A pre-dashboard backup directory was created:

```text
backups/before-dashboard-v48/
```

The first DB backup command incorrectly used role `postgres` and failed:

```text
FATAL: role "postgres" does not exist
```

The actual DB environment showed:

```text
POSTGRES_USER=darma
POSTGRES_DB=darma
```

The corrected backup command succeeded:

```bash
docker compose exec -T db pg_dump -U darma darma > backups/before-dashboard-v48/database.sql
```

A copy attempt from `core/templates` failed because that directory does not exist. Remember this path fact.

## 13.2 Saved daily-sales report HTTP 500 investigation

The user reported that **every day with a saved daily sale/report** returned server 500 when opened from the sales calendar. Empty/new days could open normally.

Runtime model discovery showed:

```text
SaleDay
SaleLine
DiaGallerySale
SaleSnapshot
SaleAllocation
SaleShortage
```

A real example:

```text
SaleDay id=26
DATE=2026-08-31
```

Route inspection proved:

```text
/sales/<day_id>/report/
-> core.daily_report_v8.daily_report
```

`core/urls.py` also confirmed related active routes for sale brand, Dia Gallery, XLSX import, price edit and delete.

Root cause found in the active V45 daily-report child template: `templates/core/daily_report_v45.html` used the `groupnum` filter but did not itself load the custom tag library. The same class of bug had already occurred in the comprehensive report. Django template tag libraries loaded in a parent are not automatically available to the child template.

Fix:

```django
{% extends 'core/daily_report_v21.html' %}{% load jalali %}
```

This changes presentation/template loading only; no sale/accounting/inventory formula was intentionally changed.

V48 artifacts created:

- `templates/core/daily_report_v45.html` fixed;
- `core/management/commands/check_daily_report_runtime_v48.py` added;
- `server_daily_report_stability_v48.sh` added;
- `docs/PROJECT_CONTEXT/26_DAILY_REPORT_STABILITY_V48.md` added;
- context manifest/README refreshed.

The V48 runtime regression is designed to render **every existing sales day** and fail unless all saved-day reports render HTTP 200. The deploy script backs up DB, checks migrations/templates, runs the render regression and requires business invariant equality.

Production status caution: no formal final V48 success block is preserved in this chat handoff, so do not claim V48 deployment-confirmed solely from GitHub.

## 13.3 GitHub capability clarified

In this chat the assistant had working GitHub connector access and directly read/modified `aliiitavazoeiii-afk/darma-general`, created files/commits/branches and inspected source. The assistant cannot SSH into the VPS. Standard working model:

1. assistant changes GitHub;
2. user runs short `git pull` + purpose-specific deploy command on VPS;
3. user posts output;
4. assistant verifies and continues.

Do not tell the user GitHub is unavailable without first checking the connector in a new chat.

## 13.4 V49 inventory operations — absolute single correction + bulk transfer

The user requested two narrow changes on `/inventory/operations/` and explicitly said not to touch anything else.

### V49 correction semantics

Old UI asked the user for a delta such as `-3` / `+5`.

User wanted to enter the **actual final physical stock** instead.

Required example:

```text
site says pink M = 160
physical counted stock = 140
user enters 140
final stock must become 140
```

Implementation preserves existing audit/model semantics:

```text
delta = target_qty - locked_current_qty
```

Then creates normal `InventoryAdjustment` and applies through unchanged `sync_inventory_adjustment()`.

Example:

```text
160 -> target 140 -> internal delta -20 -> final 140
```

No adjustment row is created when target already equals current quantity.

### V49 transfer workflow

Old transfer form was one color at a time with `from`, `to`, `qty`, `note`.

User wanted:

```text
date | brand | size
all Darma colors listed together with quantity fields
[ثبت انتقال]
```

Direction is hard-coded business behavior:

```text
KHORSHID -> HOME
```

No from/to selector and no transfer note.

Blank/zero colors are ignored. Every non-zero color still creates its own normal `StockTransfer` and uses unchanged `sync_stock_transfer()`. Whole batch is atomic. If any requested color exceeds KHORSHID stock, the entire submit fails and no colors move.

Rollback branch created and verified:

```text
before-inventory-operations-v49-20260903
```

V49 files:

- `core/inventory_operations_v15.py`;
- `templates/core/inventory_operations.html`;
- `core/management/commands/check_inventory_operations_v49.py`;
- `server_inventory_operations_v49.sh`;
- `docs/PROJECT_CONTEXT/27_INVENTORY_OPERATIONS_V49.md`.

V49 regression proves inside rollback transaction:

```text
absolute 160 -> 140 -> delta -20
bulk transfer two colors x120 KHORSHID -> HOME
combined stock unchanged by transfer
no test rows survive rollback
```

Important live evidence: after this work, the user explicitly said the **خورشید به خانه transfer was OK and excellent**. This is behavioral evidence that the V49-style transfer UI/functionality reached production at some point. However the user did not paste the formal V49 `SUCCESS:` invariant block into this handoff, so distinguish behavioral confirmation from formal deploy-marker confirmation.

## 13.5 V50 inventory operations — compact cards + bulk absolute physical count

User then requested a follow-up while keeping V49 transfer behavior unchanged.

UI requirement:

```text
[ انتقال از خورشید به خانه ] [ اصلاح موجودی ]
```

Two compact cards side-by-side on desktop, stacking responsively on smaller screens.

Transfer card remains V49 semantics:

```text
date | brand | size
all Darma colors
fixed KHORSHID -> HOME
```

Correction card changed from single color to a fast physical-count matrix:

```text
date | brand | size | location
all colors for the selected brand
[ثبت اصلاح موجودی]
```

The correction-reason field was explicitly removed by the user.

For each brand color:

- blank = do not change this color;
- explicit `0` = final stock exactly zero;
- any non-negative integer = exact final physical stock for selected brand/size/location.

Example:

```text
brand = دارما
size = M
location = HOME
pink current = 160
physical count entered = 140
final HOME pink M = 140
internal adjustment delta = -20
```

If HOME is corrected while KHORSHID is not touched, combined Darma stock remains the normal derived sum:

```text
combined = HOME + KHORSHID
```

No separate forced total reconcile and no compensating finance entry.

The form supports multiple brands. To prevent hidden/stale fields for one brand colliding with another brand's color IDs/names, target field names were made brand-aware/collision-safe:

```text
target_<brand_id>_<color_id>
```

Backend independently gets `colors_for_brand(selected_brand)` and reads only those target fields.

V50 bulk correction outer transaction calls existing absolute-target helper for each entered color, so if any target is invalid the entire batch fails.

Rollback branch exists:

```text
before-inventory-operations-v50-20260903
```

V50 files:

- `core/inventory_operations_v15.py`;
- `templates/core/inventory_operations.html`;
- `core/management/commands/check_inventory_operations_v50.py`;
- `server_inventory_operations_v50.sh`;
- `docs/PROJECT_CONTEXT/28_INVENTORY_OPERATIONS_V50.md`.

V50 regression proves:

```text
color A HOME 160 -> target 140 => delta -20
color B HOME 20  -> target 35  => delta +15
explicit target 0 => final stock 0
bulk transfer two colors x120 KHORSHID -> HOME
combined quantity unchanged by transfer
all test data rolled back
```

No V50 model/migration/finance/sale/import/final_services changes were intended.

## 13.6 V49 deploy guard failure after V50 files existed

The user ran the V49 deploy script after GitHub already contained V50 files and got:

```text
FAILED: unexpected V49 file changed: core/management/commands/check_inventory_operations_v50.py
```

This is **not a business/data failure**. It is the V49 source-scope guard correctly refusing to deploy a tree containing files outside the V49 allowlist.

The V49 script order is backup -> live snapshot -> source-scope check, so this failure happened before build/live mutation. Do not bypass the guard or edit the allowlist merely to make V49 accept V50.

Correct command for the current V50 tree is:

```bash
cd /opt/darma-general
git pull --ff-only
bash server_inventory_operations_v50.sh
```

Expected final marker:

```text
SUCCESS: INVENTORY OPERATIONS V50 DEPLOYED
```

**As of this handoff, the user has NOT pasted that final V50 success marker. Therefore V50 is GitHub-prepared/current source, but full production deployment confirmation is pending.**

---

# 14. CURRENT ACTIVE INVENTORY-OPERATIONS SOURCE CONTRACT (V50 GITHUB)

Route:

```text
/inventory/operations/
-> core.inventory_operations_v15.inventory_operations
```

Current backend helpers introduced for V49/V50:

### `_set_inventory_target(...)`

Locks one `StockBalance`, calculates:

```text
delta = target_qty - current_qty
```

and uses normal `InventoryAdjustment` + `sync_inventory_adjustment()`.

### `_bulk_set_inventory_targets(...)`

Processes multiple selected-brand color targets atomically. Blank fields are omitted by caller; explicit zero is valid; negative target rejected.

### `_bulk_transfer_khorshid_to_home(...)`

Darma-only, fixed KHORSHID -> HOME. Prevalidates all requested colors' KHORSHID stock under lock, then creates normal `StockTransfer` rows and calls unchanged `sync_stock_transfer()`.

The current template is root-level:

```text
templates/core/inventory_operations.html
```

not `core/templates/...`.

---

# 15. UI STATUS AT THIS HANDOFF

Do not assume the black/red V47/V48 dashboard concept is the user's current task.

The user explicitly said after the rollback episode:

> کاری به UI نداریم ... برگشت به UI قدیم و سرمه‌ای، ولش کن.

Therefore current instruction is:

- preserve the existing current UI unless a new request changes it;
- do not automatically resume the red glass dashboard project;
- inventory-operation compact layout requested in V50 is still part of the functional workflow request and should remain.

V47 black/red UI was a reversible runtime CSS overlay concept. It was never formally confirmed by a posted full success marker in this handoff. Do not infer that it is active.

---

# 16. CURRENT PRODUCTION-CONFIRMATION MATRIX

Use cautious wording:

- V38: formally confirmed numeric deploy marker and invariant block.
- V39: no separate formal marker; later code may have included it.
- V40: user said it came up/was operational; no newer complete numeric invariant block.
- V41-V44: user interacted with the resulting Digikala center features, but separate formal numeric markers are not preserved.
- V45 Dia Gallery: later page/server behavior indicates code reached production, but formal latest numeric marker absent.
- V46: 19 phantom units definitely reversed; HOME/KH split result observed; first script final guard false-failed due shell banner; formal corrected final marker not preserved here.
- V47: no formal success marker preserved; later user chose to leave old navy UI.
- V48: GitHub fix exists; no formal final success marker preserved in this handoff.
- V49: user explicitly said the new KHORSHID -> HOME transfer UI worked and was excellent; formal deploy marker not pasted here.
- V50: current GitHub source; first attempted deploy used wrong V49 script and was safely stopped by source guard; final V50 success marker not yet pasted.

Never convert this matrix into stronger claims without new evidence.

---

# 17. CURRENT SAFE COMMAND FOR THE LATEST INVENTORY-OPERATIONS TREE

If the new chat is continuing the exact pending V50 deployment, first inspect current Git status/source and do not blindly re-run if the user already executed it after this handoff. If still pending, the designed command is:

```bash
cd /opt/darma-general
git pull --ff-only
bash server_inventory_operations_v50.sh
```

The script creates a full PostgreSQL backup, captures business snapshots, validates source scope/migration drift/template, runs rollback-only regression, recreates web, reruns regression, and requires exact deployment-time invariant equality.

Do not use `server_inventory_operations_v49.sh` on the V50 tree.

---

# 18. NEW-CHAT OPERATING STYLE

The user wants direct implementation, not long tutorials.

Preferred workflow:

1. inspect GitHub/context without asking the user to repeat known facts;
2. implement directly in the repo;
3. protect accounting/data with rollback branch + backup + tests;
4. give one short copy/paste VPS command block;
5. interpret posted output precisely;
6. update context docs after important changes;
7. after confirmed successful deploy, update live checkpoint using the **actual server output**, not copied old numbers.

If a guard fails, diagnose that exact guard. Do not tell the user to skip safety checks.

---

# 19. ONE-SHOT PROMPT FOR THE NEXT CHAT

Copy/paste this exactly into the new chat:

> Open my connected GitHub repository `aliiitavazoeiii-afk/darma-general` and continue the existing live DARMA General ERP project. Before answering or changing anything, read `docs/00_NEW_CHAT_READ_FIRST.md` completely, then read every numbered file in `docs/PROJECT_CONTEXT/` in order through `28_INVENTORY_OPERATIONS_V50.md`, then `UI_SAFETY_V37.md` through `UI_SAFETY_V47.md`, then current `core/urls.py`, then the exact active source/template files relevant to my next request. Treat later explicit rules as authoritative over older text, especially V46: every Darma-backed sale deducts HOME only, HOME may go negative, and KHORSHID changes only through explicit manual transfer. Preserve all frozen capital, sale, Digikala-fee, SaleSnapshot, inventory-valuation, payment, material, production, XLSX replacement, return and ledger semantics. The current GitHub inventory-operations design is V50: compact transfer and correction cards; transfer is fixed KHORSHID -> HOME with one selected size and all Darma colors; correction is date + brand + size + location + all colors for that brand, where blank means unchanged, explicit 0 means final stock zero, and every entered number is the absolute final physical count converted internally to InventoryAdjustment delta. Do not resume the abandoned black/red dashboard UI unless I explicitly ask. Never assume GitHub main is live; inspect production evidence and require my posted deploy output. Use the connected GitHub tools directly, implement rather than giving me tutorials, and after code changes give me only the short safe VPS command(s) I need to run. If anything conflicts, stop and show me the exact conflict before mutating data.

---

# 20. FINAL DO-NOT-DO LIST

Never:

- reintroduce automatic KHORSHID -> HOME on sale;
- treat HOME negative as an error that must be silently replenished;
- value Anbaresh as independent inventory;
- recalculate old SaleSnapshots from current costs/fees;
- use Digikala seller code to override title product identity;
- make Digikala XLSX additive-only instead of authoritative replacement for Darma/Takvin;
- erase Anbaresh or Dia Gallery on XLSX replacement;
- use `warehouse_stock - reserve` as the V42 free-stock formula;
- change capital total directly to match a remembered target;
- raw-delete payments/sales without reversing ledgers/stock;
- merge Save / Apply Materials / Apply Output;
- treat cut as sewing-wage basis;
- turn a blank V50 physical-count field into zero; blank means unchanged;
- reject explicit zero in V50 correction; zero is a valid final physical count;
- accept negative absolute physical-count targets;
- make a V50 correction change KHORSHID when HOME was the selected location, or vice versa;
- make transfer change combined stock/value/capital;
- run V49 deploy script against the V50 source tree;
- assume root templates are under `core/templates`;
- assume a GitHub commit is production-live without evidence;
- restore an old DB checkpoint after later legitimate activity unless the user explicitly requests that exact rollback.

When uncertain, read the active code and ledgers instead of guessing.
