# V93 — Unified Product / Pricing Center

Prepared: 2026-09-28
Branch: `v93-product-pricing-center`
Base: V92 `da6d9d3754622d4599c0a04a11854e4ff25acda0`

## Goal

Make **Products & Codes** the single operational entry point for product-related setup without migrating, rewriting, or duplicating existing pricing/cost/catalog data.

The V93 landing page contains exactly three top-level sections:

1. **قوانین و قیمت‌های پایه**
2. **قیمت‌گذاری‌ها**
3. **رنگ‌بندی‌ها**

The visible UI is intentionally compact: explanatory subtitles were removed from the landing cards and inner section headers, while the primary section titles were enlarged.

## 1. Rules and base prices

The old `settings/rules/` data sources are preserved.

V93 only moves their management UI into Products & Codes:

- Darma date-effective per-short cost remains the V55 source.
- Novani date-effective per-short cost remains the V59 source.
- Takvin cost remains date-effective **per size** (M/L/XL/XXL) through `TakvinCostRule` / `takvin_pricing_v17`.
- Generic AppSettings such as commission, processing, VAT, wage, and other calculation settings remain the same rows and keys.

No inventory, capital, COGS, sale snapshot, or accounting consumer is rewired to a new source.

For compatibility:

- GET `/settings/rules/` redirects to `/settings/products/?section=rules`.
- POST to the old rules URL still executes the original V17 mutation workflow.
- Rules POSTs made from the V93 center also delegate to the original V17 mutation workflow.

## 2. Sale pricing

The authoritative sale-price engine remains `sale_price_v60.py`.

V93 does not create a new pricing table or model. It exposes the already-supported date-effective per-ProductSize rules more completely.

### Darma

The existing V60 bulk editor by pack quantity remains first.

Below it, every active Darma code is listed with its active sizes so one code can receive a different price from another code with the same pack quantity.

Example use case:

- ordinary 3-pack = one price
- striped 3-pack = another price

Both still use the same V60 date-effective rule storage.

### Takvin

Takvin bulk sale pricing is grouped by the requested pack quantities:

- pack 1
- pack 2
- pack 3
- pack 5
- pack 6

Each bulk row applies M/L/XL/XXL sale prices **only** to active Takvin ProductSize rows whose product has that exact `pack_qty`. It never creates missing products or sizes. A pack row with no active products is disabled.

Below the bulk editor, every active Takvin code is listed separately with its active sizes for per-code overrides.

Takvin **sale price** remains independent of Takvin **cost**.

### Pricing layout

Both Darma and Takvin per-code pricing editors use aligned fixed-column grids:

`code | pack | effective date | sizes | save`

The bulk editors use the same aligned approach. Input heights are fixed, size headings live in one header row, and product-code text uses the normal UI font instead of the previous code-style font.

### Historical safety

V60 semantics are preserved:

- historical positive SaleLine prices remain frozen;
- a future rule does not leak into today's sales;
- a rule affects new sale rows according to its effective date;
- legacy ProductSize default sale price remains only the fallback before the first managed rule.

## 3. Color arrangements

The existing Products & Codes catalog table is moved under **رنگ‌بندی‌ها** without changing its product/composition/size data sources.

The existing per-product edit route remains active.

The Darma `s3` special UI marker is preserved.

## Settings home cleanup

The separate top-level Rules card is removed from Settings Home.

Products & Codes becomes the single visible entry point for:

- base rules/costs;
- sale pricing;
- product/color composition.

## No schema/data migration

V93 introduces no Django model and no migration.

It does not automatically write any:

- AppSetting;
- TakvinCostRule;
- ProductCode;
- ProductSize;
- ProductComposition;
- SaleLine;
- inventory row;
- accounting row.

Writes happen only when the user explicitly submits one of the existing/new pricing forms.

## Regression

`check_product_pricing_center_v93` is read-only after transactional rollback and verifies:

- `/settings/products/` is routed to V93;
- old `/settings/rules/` compatibility is active;
- all V93 templates compile and render;
- every active Darma ProductSize in supported sale sizes is represented in the per-code editor;
- every active Takvin ProductSize in supported sale sizes is represented in the per-code editor;
- Takvin bulk rows are exactly pack 1/2/3/5/6;
- each Takvin pack row reports the exact active products for that pack;
- a transactional Takvin bulk test changes only the selected pack and does not leak into another pack quantity;
- V60 date-effective sale-price semantics directly through the authoritative `sale_price_v60` engine:
  - future Darma/Takvin prices do not leak into today;
  - prices activate on their effective date;
  - changing a rule does not rewrite an existing historical `SaleLine.sale_price`;
- Rules / Darma Pricing / Takvin Pricing / Colors UI markers render;
- final fingerprints prove AppSettings, Takvin cost rules, products, product sizes, compositions, SaleDays and SaleLines are unchanged.

The older V60 regression still contains a historical route assertion that `/settings/products/` must point directly at `pricing_v60`. V93 intentionally wraps that engine, so V93 owns the replacement route-aware sale-price semantic check instead of changing the old V60 regression.

Expected marker:

`SUCCESS: PRODUCT PRICING CENTER V93 CHECK PASSED`

## Deployment

Use:

`bash server_product_pricing_center_v93.sh`

The deploy script:

- creates a non-empty PostgreSQL backup;
- verifies V93 changed-file scope;
- protects authoritative pricing/cost/accounting/import/material mutation files;
- uses the Docker Hub -> `mirror.gcr.io` fallback introduced after the V91 registry 403;
- runs migration drift / Django checks;
- runs V59 cost, V89 pricing-monitor, V90, V91, V92, and V93 regressions;
- V93 itself transactionally regression-tests the V60 sale-price engine semantics and Takvin per-pack isolation described above;
- compares pre/projected/final business + catalog/pricing fingerprints;
- recreates only `web`;
- never uses `--remove-orphans`.

Production is confirmed only after the VPS prints:

`SUCCESS: PRODUCT PRICING CENTER V93 DEPLOYED`
