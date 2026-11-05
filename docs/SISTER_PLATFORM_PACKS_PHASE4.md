# Sister panel / platform bundles V4

**Scope:** only the isolated `dia-darma-fresh` branch and isolated
`/opt/dia-darma-fresh` Django + FastAPI/SQLite services. Never copy
or modify original Darma or Dia Gallery databases, servers or volumes.

## Confirmed workflow
1. `تعاریف → محصولات و کدها → تعریف محصولات` is physical SKU truth,
   including category, model title/subtype, each color and size.
2. `تعاریف → محصولات و کدها → پلتفرم‌ها` shows four uncluttered cards:
   DigiKala, Basalam, site, molds. DigiKala remains in its pre-existing
   manual catalog (538 external variants), pending separate safe mapping.
3. Enter site, Basalam or molds. First card is product definition:
   category (molds fixed to قالب), **model**, **units per pack (1–6)**,
   independently chosen color for each physical unit (repetitions allowed),
   then **checkboxes for eligible sizes**. A size is eligible only if every
   chosen color has an unambiguous active physical SKU of that exact size
   and model. Invalid/ambiguous sizes fail closed without partial writes.
   An optional custom listing title is supported.
4. Beneath that is a compact search and a table of platform product listings.
   Historical V3 single-SKU listings are kept separately under a collapsed
   read-only details section, NOT silently converted into multi-color packs.
5. `قیمت‌گذاری → قیمت فروش` contains only **platform-defined bundle
   variants** grouped under their listing. Each size gets an independent
   **price for the entire pack**, distinct between site/Basalam/molds.
   No product definitions in that platform means no price fields.
   Legacy generic SKU pricing is preserved for historical V3 sales but
   is not editable through the new user workflow.
6. `فروش روزانه` chooses a registered platform variant and warehouse.
   One pack decrements one unit of each configured color at the chosen size;
   repeated colors decrement multiple units of that same SKU.
   Multiple packs aggregate the quantities; all stock checks and updates
   happen inside a single BEGIN IMMEDIATE SQLite transaction, with
   audit events per changed SKU, immutable sale parts and cost snapshot.
   Order refs are deduplicated in both new and old sale ledgers.
   Unknown commissions remain NULL; never claim a definitive net margin.
7. Platform sales summary merges both legacy V3 and V4 sale ledgers, without
   re-posting or re-deducting prior sales. Current independent sister capital
   values physical home + KhorShid inventory at applicable effective-dated
   costs; historic sale COGS is not retroactively changed.

## New additive schema
- `platform_bundle_models`: one platform listing with model, category, pack
  count, ordered color-slot composition.
- `platform_bundle_variants`: one size per listing, with its own pack price.
- `platform_bundle_parts`: one specific physical SKU per color slot/size.
- `platform_bundle_sales`: dated transaction for selling N packs of a size.
- `platform_bundle_sale_parts`: immutable per-physical-SKU consumption.

All existing `master_products`, `master_stock_events`,
`platform_listings`, `platform_sales`, `products` (DigiKala)
and `sales` remain intact. New tables are created idempotently.

## Safety & tests

- Regression tests `tests/test_sister_platform_v4.py` cover three colors,
  duplicate color slots, M/L independent prices, six-item pack, mold sizes,
  cross-channel price isolation, insufficient stock atomic rollback and
  duplicate refs across legacy and new ledgers.
- GitHub Actions `Sister product master checks` tests Python engine,
  Django routes/CSRF bridge, and actual HTTP create/price/sell flows.
- Upgrade script takes backups of only the sister PostgreSQL and SQLite,
  compiles Python, tests routes, then restarts only isolated web/DigiKala
  containers. No stock import or migration from original businesses.
- Next phase (NOT yet performed): DigiKala 538 external variant mapping
  to the platform/SKU catalog with explicitly reviewed pack composition
  and color/size matching. Do not silently bulk-map ambiguous items.
