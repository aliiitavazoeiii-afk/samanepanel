# V111 — PRODUCT DEFINITION AS THE CANONICAL CATALOG

Branch: `v111-product-definition-catalog-sales`
Base: `v110-material-summary-box-grid` (includes V109 and the V108 stable baseline).

## Product definition

A fourth card, **تعریف محصول**, appears under محصولات و کدها. It opens the existing canonical editor at `/settings/products/new/`, now featuring an independent required **عنوان محصول** field as well as:
- brand
- code (unique per brand)
- pack quantity
- quantity of each currently registered color for that brand
- active sizes and dated sale prices
- active/inactive state
- unchanged optional legacy note

Selected color counts must sum exactly to pack quantity. The existing special Darma variable-color codes retain their specific validation and may not acquire fixed composition.

Saving uses the existing transactional `settings_product_v60.settings_product_form`, `ProductCode`, `ProductComposition`, and `ProductSize`. The save redirects straight to `/settings/products/?section=colors`, so the new code, title, colors and sizes are immediately visible.

## Title schema

New additive database migration:
`core/migrations/0018_productcode_title.py`

Adds only:
`ProductCode.title = CharField(max_length=160, blank=True, default="")`.

No old title is inferred from notes; existing `note` is never overwritten. Legacy rows remain valid with a blank title. New/edit form requires the user to enter the product title when saving.

## Daily order / manual sales

`core/sale_entry_v60.sale_size` already reads current active `ProductSize` and `ProductCode` for every size. V111 displays:
- product code
- independent title when present
- live `ProductComposition` colors and per-color quantities

on both desktop and mobile, from the SAME persisted rows as رنگ‌بندی‌ها. No copy/sync table is introduced.

The existing Digikala XLSX title-only model resolver is intentionally unchanged; it still requires the actual model code in the marketplace title. Creating an internal title alone must not result in fuzzy or incorrect product matching.

The Darma -> Anbaresh catalog mirror also copies the independent title field. It does not create Anbaresh stock.

## Price safety

The existing price-validation and date-effective sale-price workflow remains unchanged: enabled sizes need a positive sale price, and Darma/Takvin future prices do not rewrite historical sale lines.

## Data safety and deployment

Migration 0018 is additive. Before migrating, back up the full database and snapshot business-state fields. The V111 deployment checks the existing V108/V110 and V93 regressions plus `check_product_definition_v111`, which creates and displays a test code/title/composition/size under a rollback transaction and compares database hashes before/after. Only the old ProductCode fields are included in cross-schema hashes; the new column is checked separately.

No data import, broad catalog sync, stock reset, accounting formulas, material sync, inventory valuation, or sale-history rewrite.

Production confirmation requires:

`SUCCESS: PRODUCT DEFINITION + COLORS + DAILY SALES V111 DEPLOYED`

Do not call GitHub-only work a live deployment without server PRE/PROJECTED/FINAL hashes and the final marker.
