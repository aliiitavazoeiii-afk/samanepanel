# Sister panel — Phase 1: Product master, stock and DigiKala mappings

## Scope
This is ONLY the `dia-darma-fresh` branch of `samanepanel`, on server `/opt/dia-darma-fresh`.
It does not modify `/opt/darma-general`, `/opt/dia-gallery`, their PostgreSQL databases,
their configurations, or their Docker volumes.

## Canonical identity
One physical sellable SKU = (category, code, color, size), unique.
The five categories (exactly): زیرپوش دارما; شورت زنانه دارما; شورت زنانه دیا; بادیگارد; قالب.

The `master_products` table is in the existing **isolated sister_sales_data SQLite volume**.
It has one seller stock and one DigiKala stock field, initialized to **zero**.
Do not seed current stock from the old DigiKala export (historical snapshot).
Manual stock corrections are absolute counts with a mandatory reason and immutable
`master_stock_events` trail. No stock reset on upgrade or re-import.

Main UI:
- `/settings/products/` — 2 cards: main products and DigiKala products.
- `/settings/products/new/` — product master creation, five category filters,
  title, code, size, color, price and cost, searchable and editable.
- `/settings/products/digikala/` — the existing 538 external variant IDs,
  search and link to one main physical SKU + optional DigiKala-specific sales price.
- `/inventory/stock/` — main physical SKU stock, by seller/DigiKala source.
- `/inventory/` redirects to canonical stock.
- Legacy ERP pages remain at `/settings/products/legacy/`, `/inventory/legacy/`,
  `/inventory/legacy-stock/` only for reference, not used by sister sales.

DigiKala order import still uses existing preview/commit workflow, but in
`SALES_MASTER_STRICT=1` **must** resolve every external variant ID to a linked
active master SKU. An unknown/unmapped SKU blocks the import. Prices from daily
XLSX take precedence; otherwise DigiKala-specific configured price; otherwise
SKU master price; zero/missing price blocks. Fee category comes from mapped
master category. The master stock of selected source is decreased atomically.
Multiple DigiKala variant IDs may map to one SKU; stock sufficiency is checked
against their **aggregate** quantity. Re-importing the same sale date/source
replaces the previous posting and adjusts only the difference. An import cannot
remap a variant with previously posted sales to a different SKU without manual
reconciliation. Cost/profit snapshots from committed sales remain historical.

Legacy variant stock edits are blocked in strict mode to prevent competing
sources of truth. Django PostgreSQL business/financial dashboard is still a
**legacy view**, not yet unified with this master; new master/sales data live in
the dedicated sister SQLite volume. Site/Basalam/mold sales cards are placeholders
and do not yet change stock; those channel flows should be implemented against
this same SKU master next, never against a second inventory ledger.

## body.xlsx definitions supplied 2026-10-31
User uploaded `body.xlsx`, Sheet1 (used range A1:R47). Parsed and preserved
normalized color/design labels from these ranges:

| Group | Source | Colors | Sizes | SKUs | Master category |
| --- | --- | ---: | --- | ---: | --- |
| Men's slip | E5:E22 | 18 | L,XL,2XL,3XL | 72 | بادیگارد |
| Men's legged/padar | N5:N26 | 22 | L,XL,2XL,3XL | 88 | بادیگارد |
| Undershirts | E30:E32 | 3 | M,L,XL | 9 | زیرپوش دارما |
| Dia women's | E37:E40 | 4 | M,L,XL,XXL | 16 | شورت زنانه دیا |
| Darma women's | E43:E47 | 5 | M,L,XL,XXL,3XL | 25 | شورت زنانه دارما |
| Shoe molds | User conversation (not file) | — | کوچک,متوسط,بزرگ | 3 | قالب |
| TOTAL | | | | **213** | |

Source labels and provenance (including which size sets are inferred) are in
`daily_sales_service/catalog_body_20261031.json` and checked in
`tests/test_catalog_import.py`. **Women's Darma sizes were absent in the
uploaded sheet:** five sizes were provisionally based on the owner's previously
specified size range, and should be confirmed before relying on them. Molds
were specified by owner verbally, not listed in the workbook.

The source does not provide factory SKUs, prices, or opening stock:
`catalog_import.py` generates stable **internal** codes BG-SL-01 etc.,
uses zero prices, null cost and zero opening seller/DigiKala stock.
Import is idempotent, also matches an existing exact design with an alternate
manually chosen code, and never overwrites any existing price, cost, stock,
or sale history. The 538 DigiKala variant references are separate and
require manual mapping to one of these master SKUs.

Deployment: obtain current
`deploy/darma-fresh/upgrade_sales_channels.sh` after commit
`78ca73788cf50291194990cb91fd4b5e4f36019b`, then run on isolated server.
It backs up databases, runs tests, deploys only the isolated services and
executes `python -m daily_sales_service.catalog_import --dry-run` followed by
`--apply`. Success markers: `SISTER_BODY_CATALOG_213_IMPORTED`,
`BODY_CATALOG_MATCHES 213 OF 213`,
`BODY_XLSX_PRODUCT_DEFINITIONS_READY`.

**Not deployed by the assistant** (no shell access to owner's VPS).
The owner must run the script; check its output before claiming data is live.

## Financial caution
Men's product commission 24.3%, molds/shoe category 22.5%.
Women's 24% and other/bodyguard 24% remain provisional and require owner
confirmation before financial reliance.

## Upgrade
Use only `deploy/darma-fresh/upgrade_sales_channels.sh`:
backs up fresh PostgreSQL and existing sister SQLite; builds only fresh
web and sister-digikala; compiles and runs engine/route tests before replacing
running services. No reset of volumes or original Darma/Dia sites.
The final marker should be `SISTER_MASTER_CATALOG_READY`.

## Acceptance
1. Five categories on main definitions and editable SKU list.
2. One SKU stock is visible and manually adjustable with audit entry.
3. 538 DigiKala variants retained and searchable, mapped SKU/color/category
   and optional distinct selling price editable.
4. Unlinked import blocked; no stock deducted on preview.
5. Linked import deducts the master stock, aggregated across external variants.
6. Same-day replacement idempotent and cannot cause negative stock.
7. Other sale channels still explicitly disabled until integrated.
