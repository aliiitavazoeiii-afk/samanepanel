# Samanepanel – Digikala Daily Sales (isolated service)

A fully isolated, optional daily-sales service for the second Digikala seller account. It **does not** change Darma's `darma-general` data or require Darma's database. It is intended to be integrated by the next developer/chat without replacing any existing `samanepanel` project files.

## What is included

- Catalog seed from the uploaded `digikala kala.xlsx`: **538 unique variant IDs** (325 men's briefs, 196 women's briefs, 9 men's undershirts, 8 shoe-care items). Seller stock 9,928 units, Digikala stock 85 units. This is a **snapshot**; reconcile with actual stock before live use.
- Configurable commission: men and men's undershirts **24.3%**, shoe molds/care **22.5%**, women and all other products **24%** (default pending confirmation).
- Processing charge **max(sale price × 7%, 36,000 toman)**. VAT **10% of commission + taxable processing**. For the processing floor, the taxable portion is **18,000 toman**; otherwise it is **half of processing**. This follows the finance function in `darma-general/core/finance.py` on branch `v126-payment-history-filters`, without importing Darma-specific promotional exceptions.
- Sales Excel import: quantity, product title or **Digikala variant ID**, optional status, optional explicit transaction price. Strict matching and fail-closed unknown/ambiguous variants. Multi-file aggregation supported.
- Preview then commit, transactional inventory deduction and stock event audit, per-day **replacement** import semantics (re-upload updates existing day, absent lines are reversed), no double deductions.
- Separate seller vs Digikala stock; inventory adjustments with audit; per-variant COGS, bulk cost import; dashboard fees, gross, net after fees, **profit only when unit costs are known**. CSV and JSON reports.
- HTTP Basic auth, app token via environment, SQLite WAL persistent volume, health check, no Darma dependencies.

## Install on a server

From this module's root directory (where `Dockerfile` and `compose.daily-sales.yml` are):

```bash
cp .env.example .env
# EDIT .env with a long unique SALES_ADMIN_PASSWORD. Never commit it.
docker compose -f compose.daily-sales.yml up -d --build
docker compose -f compose.daily-sales.yml ps
curl --fail http://127.0.0.1:8018/daily-sales/healthz
```

Then put the service behind the **existing HTTPS reverse proxy** on the **same domain**. Example Caddy snippet (add to the actual site's block; do **not** blindly replace its existing Caddyfile):

```caddyfile
handle /daily-sales/* {
    reverse_proxy 127.0.0.1:8018
}
```

The service handles its own `/daily-sales/*` prefix, so **do not** use `handle_path` (which strips the prefix). If the reverse proxy is Dockerized, `127.0.0.1` inside the proxy container is not the host; use the reachable host gateway or shared Docker network. Make sure SSL is active before entering credentials, and keep port 8018 bound only to localhost. Visit `https://YOUR_EXISTING_DOMAIN/daily-sales/`, authenticate with the credentials in `.env`. In the other panel, add a navigation link to `/daily-sales/`.

## Test

```bash
python3 -m unittest discover -s tests -v
```

## Financial configuration

| Category | Commission |
|---|---:|
| شورت مردانه | 24.3% |
| زیرپوش مردانه | 24.3% |
| مراقبت کفش و لوازم جانبی | 22.5% |
| شورت زنانه | 24% default, **needs confirmation** |

Other fee components are copied from the existing Darma dashboard fee formula: processing 7%, floor 36,000 toman per item, 10% VAT over commission and the processing taxable basis, floor taxable component 18,000 toman, otherwise half processing. **VAT is not a flat 10% tax on the gross selling price.**

Fee example for a men's item sold at **500,000 toman**: commission 121,500, processing 36,000 (floor), VAT 13,950, total fee **171,450 toman**; net after Digikala fees 328,550 toman. Actual profit additionally subtracts **unit product cost**.

The uploaded inventory file provides selling prices in **rial**, not production/acquisition cost. No cost is invented. Add costs from `/daily-sales/inventory` or via a second XLSX with columns `کد تنوع` and `بهای تمام‌شده (تومان)` before relying on a profit figure. Historical line costs are frozen at import time; entering a cost later intentionally does **not** rewrite history.

If the daily orders XLSX contains an explicit `قیمت واحد (تومان)` or `(ریال)قیمت فروش`, that value is used. Without it, the seed's **list price**, NOT promotion price, is used and a warning appears. Confirm against the actual order/settlement export; a promotion or coupon can make list-price-based profit wrong. Imported data must be an actual delivered sales report, not the inventory export.

## Data safety

1. Create a database backup from the `daily_sales_data` Docker volume before any major change.
2. Align the initial inventory snapshot with real counts; do not treat the Excel snapshot as permanently live. Imported sales update this **local** inventory; they do **not** send stock changes back to Digikala.
3. Enter costs before production reporting, reconcile actual fee invoices and special promotions, and validate one day manually before full rollout.
4. For old days and re-imports, use the **same sale date and same stock source**. Re-import replaces that day's lines; missing variants are set to zero and stock restored. Source `seller` is not interchangeable with source `digikala`.
5. Do not route return Excel files into the sales endpoint. Returns and cross-source transfers require explicit stock adjustment/accounting workflow; they are not misclassified as sales.
6. If a product is unknown, inactive, ambiguous, has conflicting prices, or insufficient stock, no sale is committed. Always use explicit variant IDs when possible.

## Source reference

- `https://github.com/aliiitavazoeiii-afk/darma-general/blob/v126-payment-history-filters/core/finance.py`
- `https://github.com/aliiitavazoeiii-afk/darma-general/blob/v126-payment-history-filters/core/daily_order_import_v8.py`
- `https://github.com/aliiitavazoeiii-afk/darma-general/blob/v126-payment-history-filters/core/daily_order_views_v60.py`

Further integration notes: `docs/NEW_CHAT_HANDOFF.md`.

## Required panel navigation: «تعریف» → «تعریف محصولات»

The next integration must expose an obvious **«تعریف»** menu and **«تعریف محصولات»** page (or reuse this menu if the main panel already has it). The 538 variants from `digikala kala.xlsx` are already auto-seeded on **initial empty database creation**; in the definitions page, the owner should only need to supply a **per-variant unit cost in toman**. The daily-sales import must read that cost automatically for its frozen COGS snapshot and calculate the correct Digikala charges and profit. Keep old costs and stock on redeploy/reimport. The existing `/daily-sales/inventory` page already supports manual and bulk cost edits; the dedicated definitions **navigation/UI and future-safe catalog sync remain integration work**.

**Complete Persian product / UI / financial specification and acceptance criteria:** [`docs/PRODUCT_DEFINITIONS_SPEC.md`](docs/PRODUCT_DEFINITIONS_SPEC.md).
