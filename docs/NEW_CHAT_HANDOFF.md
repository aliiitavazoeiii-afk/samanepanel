# Handoff for the next ChatGPT chat — Second Digikala panel

## Repositories / ownership

- Target: `https://github.com/aliiitavazoeiii-afk/samanepanel`.
- Source of the audited fee and delivery-import logic: `https://github.com/aliiitavazoeiii-afk/darma-general`, branch `v126-payment-history-filters` (DO NOT edit this repository for the second seller account).
- This package adds a standalone FastAPI service at path `/daily-sales/`, with its **own** SQLite database and Docker Compose file. It is designed to coexist with the other chat's code. The `samanepanel` repository was EMPTY during this chat's initial inspection (2026-10-29); if other work has since appeared, inspect it before integration and do not overwrite anything.

## Data supplied by user

`digikala kala.xlsx` was a DigiKala **bulk price/inventory export**, not a sales report. Sheet `داده ها` had **538 variants**, 538 distinct `کد تنوع`, no missing titles: 325 `شورت مردانه`, 196 `شورت زنانه`, 9 `زیرپوش مردانه`, 8 `مراقبت کفش و لوازم جانبی`. Seller stock total 9,928, Digikala stock 85, reserved 106, available 9,907. All 538 titles and their product/variant codes, category, list/promotion rial prices, stock and active status are in `daily_sales_service/catalog_seed.b64` (zlib-compressed UTF-8 JSON list); the engine decodes this on empty database initialization. Do not overwrite current stock when rebuilding/deploying.

## User requirements

- Upload daily sales **XLSX**, auto-deduct relevant inventory, calculate gross, exact DigiKala charge, receivable/net after DigiKala and profit once actual unit costs are set.
- Commission men's products 24.3%, shoe molds 22.5%. Other processing 7%, VAT and floor rule unchanged relative to Darma panel. Women/other default rate 24% pending verification.
- Keep the other seller panel independent; current Darma panel must remain unchanged.
- Provide server deployment commands and verify readiness once the other panel's actual code and domain are known.

## Implementation checklist for the next chat

1. Read `README.md`, `daily_sales_service/engine.py`, `daily_sales_service/app.py`, catalog seed and tests in this repository. Inspect **all new code** in `samanepanel` and current deployment topology before commands or UI integration.
2. Run unit tests (6 tests for fees, seed, imported daily sales, correction, missing costs, insufficient stock, unknown ID). Run `python3 -m unittest discover -s tests -v`.
3. Confirm whether the existing panel uses Django/FastAPI/Node and its reverse proxy. Keep the daily-sales microservice isolated if API/framework differs; add link `/daily-sales/` in existing nav and reverse proxy the prefix, or carefully port the engine into current app architecture.
4. Set a strong secret in `.env` (`SALES_ADMIN_PASSWORD`); do not commit passwords. Build with `docker compose -f compose.daily-sales.yml up -d --build`. Check `/daily-sales/healthz`, then authenticated UI.
5. Reconcile seller and DigiKala opening inventory against current reality. Uploaded seed reflects a historic snapshot, not live stock; separate seller and DigiKala pools. Never perform destructive DB reset against populated production data.
6. Enter unit COGS for all active variants (user did **not** provide unit cost). Verify list vs discount/transaction prices with one actual daily delivery XLSX. Preview on one test day and reconcile against DigiKala fee settlement before production use.
7. Confirm women's 24% default and whether all shoe-care items have 22.5% commission. If only shoe molds qualify, narrow classification to exact variants and update regression tests.
8. Current implementation supports `عنوان`/`کد تنوع` and `تعداد ارسالی` (or aliases), status, explicit sale prices in labelled rial/toman fields. For unexpected export columns, extend parser with explicit test fixture; never guess matching of variants by product ID (many size/color variants share product ID).
9. Add automated backups, monitoring, user session integration, and a **separate returns ingestion and returns ledger** only after actual requirements/file sample are available. The present service does not import returns as sales.
10. Never suggest commands that copy Darma's databases, connect unrelated DBs, overwrite the other chat's working code, or expose the sales service directly to public internet.

## Accounting formulas

For a price P (toman):

- `commission = P × category_rate`
- `processing = max(P × 0.07, 36000)`
- `taxable_processing = 18000 if processing floor applies else processing / 2`
- `vat = (commission + taxable_processing) × 0.10`
- `digikala_fee = ROUND_HALF_UP(commission + processing + vat)` **per sold unit**
- `gross = sum(qty × selling_price)`
- `digikala_total_fee = sum(qty × digikala_fee)`
- `net_after_digikala = gross - digikala_total_fee`
- `profit = net_after_digikala - sum(qty × recorded unit_cost)` only when *all* relevant cost snapshots exist; otherwise profit is **null/unknown**, NOT a false zero.

Darma `finance.py` has a **single-day special exception** with zero commission for 1405/07/08; this is account-specific and is intentionally **not** imported to Samanepanel.

## Technical details

- App routes: `/daily-sales/`, `/daily-sales/import`, `/daily-sales/preview`, `/daily-sales/commit`, `/daily-sales/inventory`, `/daily-sales/settings`, `/daily-sales/api/report.json`, `/daily-sales/api/report.csv`, `/daily-sales/healthz`.
- Dependencies: FastAPI/Uvicorn/python-multipart; XLSX parsing uses stdlib zip+xml, no openpyxl.
- Auth: HTTP Basic through HTTPS only. Separate Basic credentials from existing panel; integration can add SSO later.
- DB schema established by `init_db`; uses SQLite WAL + volume `daily_sales_data`.
- Atomic `BEGIN IMMEDIATE` commit and stock movement events. Confirmation token expires in 30 minutes, used once. Existing day+source rows are completely replaced with desired set, delta restores or reduces inventory; insufficient stock aborts all writes.
- Frozen per-line fee and COGS protect historical reports from new fee/cost settings. If users need to restate old COGS, add an audited correction workflow instead of silently recalculating old days.

## Caveats

- UI date input is currently Gregorian (`YYYY-MM-DD`), not Jalali; add Jalali display/calendar if matching the other panel's UX.
- Current sale row uses one unit price per variant/day/source. If a single variant has multiple prices in one day, import rejects until a price-split line model is designed.
- Real sale price must be confirmed (the product inventory export includes both list price and promotion price; neither guarantees settlement actual).
- Inventory is local; future stock synchronization to Digikala requires an authenticated API integration and conflict policy, not currently implemented.

## NEW REQUIRED UI: «تعریف» → «تعریف محصولات» (owner request, 2026-10-29)

Read and implement **[`docs/PRODUCT_DEFINITIONS_SPEC.md`](PRODUCT_DEFINITIONS_SPEC.md)** before declaring the new panel's daily-sales feature complete. The user wants a clearly visible **«تعریف»** section (reuse existing section if available), containing **«تعریف محصولات»**. The 538 unique variants from the supplied inventory Excel must appear automatically there. The owner should enter **only each variant's بهای تمام‌شده (تومان)**; sale imports then automatically use that stored cost and the existing category-specific commission/processing/VAT formulas to calculate fees, receivable and profit. Do not require the owner to define products manually. Keep already entered costs and live stock intact, don't create duplicates, and never rewrite historical sale cost snapshots automatically.

**Current code note:** `/daily-sales/inventory` already lists catalog variants and allows single/bulk COGS edits, but there is no independent `تعریف` navigation. Reuse this functionality and integrate an intuitive definitions page into the *existing* panel's UI rather than making a second disconnected catalog. The spec sets acceptance tests and safe catalog-import behavior. This is a **pending implementation requirement**, not a claim the new UI is already deployed.
