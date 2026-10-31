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

## Pending user input
The five category Excel workbooks have not been supplied in this conversation.
No user-specific products from those files have yet been populated. The 538
DigiKala variants are pre-existing **external variant references**, not
physical master SKUs and not current inventory.

Before bulk import, inspect actual Excel column names and identity structure,
especially pack vs piece quantity and variant/color/size. Implement a
preview/idempotent upsert based on exact incoming columns, then import into
`master_products` with **zero opening stock** until reconciled.

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
