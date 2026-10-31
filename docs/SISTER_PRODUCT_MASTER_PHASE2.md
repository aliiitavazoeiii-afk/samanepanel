# Sister ERP phase 2 — Master definitions, pricing and Darma-style stock

Scope: ONLY repository `aliiitavazoeiii-afk/samanepanel` branch
`dia-darma-fresh`, Docker compose project `dia-darma-fresh`,
server directory `/opt/dia-darma-fresh`. Never modify either original site
(Darma `/opt/darma-general`, original Dia `/opt/dia-gallery`).

## Navigation and UI

تعاریف → محصولات و کدها has three cards:
- تعریف محصولات: category, title, optional bodyguard type, color list, size list.
  **NO user-entered product code, retail price or COGS.** A hidden stable
  `AUTO-...` code is created for relational integrity and DigiKala mapping.
  Re-entering same category/title/type with additional color/size is idempotent.
  Existing linked SKUs keep their IDs and inventory. UI uses responsive model
  cards rather than the previous overflowing table.
- قیمت‌گذاری → بهای تمام‌شده: one central rule per زیرپوش دارما,
  شورت زنانه دارما, شورت زنانه دیا, bodyguard اسلیپ and پادار separately,
  and قالب separately for کوچک, متوسط, بزرگ. Current inventory value and
  future DigiKala cost snapshots are computed from these rules; historical sale
  cost snapshots remain unchanged. An unset cost results in an UNKNOWN stock
  value, not a fabricated zero valuation.
- قیمت‌گذاری → قیمت فروش: site, Basalam, and mold channels only.
  Bulk assign price by category, optional model, optional size/type. Stored
  per SKU in `master_channel_prices`, completely independent from DigiKala
  prices. No sales on those three channels until order flows are implemented.
- محصولات دیجی‌کالا: pre-existing 538 external variants and SKU mappings,
  original daily-sale pricing under DigiKala-specific area only.

## Inventory from Darma visual structure

`/inventory/stock/` now shows five category tabs, model/type/search filters,
then three separate responsive color × size tables for the selected model:
- موجودی کل
- موجودی خانه
- موجودی انبار خورشید

Zero is strong red; low balance (1-9) is soft red; totals and stock valuation
are in the footer. Changes are made via `/inventory/operations/`:
choose category, model, size, and warehouse; enter desired final counts for
one or multiple colors; empty cells mean unchanged. Changes and source/destination
transfers are atomic and recorded in `master_stock_events` and
`master_transfers`. Both directions (home ↔ KhorShid) are allowed, and
a source cannot become negative. Original Darma inventory and old endpoints
remain under `/inventory/legacy...` for diagnostics only.

## Data preservation and compatibility

Previous `master_products.seller_stock` remains HOME stock, not overwritten.
A new `khorshid_stock` column starts at zero. Existing
`digikala_stock` is a separate **legacy DigiKala warehouse** field and is
**NOT** silently moved to KhorShid or shown as part of the two physical
warehouse totals. If historical data exists there, the UI shows a warning for
later explicit reconciliation. Historical day/source sales remain in place.
New DigiKala import shows source choices home and KhorShid only, and deducts
the chosen master balance atomically. The legacy `digikala` source remains
valid in storage for accurate historical reimports. The price returned by
daily XLSX takes precedence over the DigiKala variant-specific price;
no price defaults to the main SKU's old price unless configured. The cost
now uses centralized cost rules, falling back to existing master COGS
during transition when no rule exists.

No automatic bulk import of the five category workbooks: owner has yet
to provide them and actual field names must be inspected before upload.
No data is copied from the original Darma or Dia production databases.

## Upgrade and acceptance

Run the isolated safe upgrade script from the branch:
```bash
cd /opt/dia-darma-fresh
curl -fsSL https://raw.githubusercontent.com/aliiitavazoeiii-afk/samanepanel/dia-darma-fresh/deploy/darma-fresh/upgrade_sales_channels.sh -o /root/upgrade_sister_master.sh
bash /root/upgrade_sister_master.sh
```

It backs up existing sister data, builds only isolated containers,
compiles Python and tests Django, old and new sister engines and
both warehouses before rollout. Expected marker:
`SISTER_MASTER_CATALOG_READY`. No original site or volume is changed.

Acceptance:
1. Definitions show no code/COGS/sale price fields and overflow is eliminated.
2. All five category filters present.
3. Pricing cost screens show bodyguard slip/boxer and small/medium/large molds.
4. Selling prices split into Site, Basalam, mold; DigiKala absent there.
5. Each category/model shows 3 Darma-style stock tables.
6. Manual changes and multi-color transfers journal changes exactly once.
7. Existing stock, external DigiKala variants and sales survive upgrade.
8. Unlinked DigiKala sales still fail closed and mapped sales use chosen warehouse.
