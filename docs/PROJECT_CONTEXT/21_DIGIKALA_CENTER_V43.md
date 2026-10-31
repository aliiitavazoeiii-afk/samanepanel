# 21 — DIGIKALA CENTER V43

V43 converts the external Digikala Open API area from one delivery page plus one warehouse page into a separate Digikala mini-app inside DARMA.

Status at creation: **prepared on GitHub; not production-confirmed until the user posts a successful V43 deploy output**.

## User requirement

The user wants the Digikala section to be self-contained and visually/operationally separate from the rest of the business panel. Entering Digikala should show several clean boxes/sections rather than mixing Digikala widgets throughout the main workflow.

Required sections:

1. سفارش روزانه
2. محموله‌ها
3. گزارش فروش
4. موجودی انبار
5. مرجوعی

The normal internal accounting/inventory/sales panel must remain untouched by ordinary Digikala browsing.

## Routes

V43 route map:

```text
/digikala/                         -> center home
/digikala/summary/                 -> existing async summary JSON
/digikala/orders/                  -> daily commitments
/digikala/packages/                -> packages list
/digikala/packages/<package_id>/   -> package detail
/digikala/sales/                   -> sales report
/digikala/warehouse/               -> V42 free warehouse page
/digikala/returns/                 -> return-stock visibility
```

All page routes are login-protected GET views.

## New source

```text
core/digikala_center_v43.py
core/management/commands/check_digikala_center_v43.py
templates/core/_digikala_nav_v43.html
templates/core/digikala_center_v43.html
templates/core/digikala_orders_v43.html
templates/core/digikala_packages_v43.html
templates/core/digikala_package_detail_v43.html
templates/core/digikala_sales_v43.html
templates/core/digikala_returns_v43.html
server_digikala_center_v43.sh
UI_SAFETY_V43.md
```

Changed:

```text
core/digikala_views_v40.py
core/urls.py
```

No model/migration/economic source is changed.

## Daily orders: DKP first, DKPC inside

The user explicitly distinguishes:

- DKP = product code / product identity;
- DKPC = product variant code, e.g. size/color variation.

The page must group by DKP with the Digikala product image. Expanding a DKP shows DKPC, seller code, parsed size and quantity.

Example intent:

```text
PACK-5 / DKP 16659505 / image
  36-38 / DKPC 57642066 / qty ...
  XL    / DKPC ...      / qty ...
```

This is a presentation grouping only; it does not change internal product resolution rules used by XLSX import.

## Tomorrow / day-after split

The unfiltered commitments list remains the primary current quantity source.

V43 attempts to derive exact future-day buckets using the official commitments filters described in the supplied OpenAPI material:

```text
search[is_effective]=true
search[to_commitment_date]=YYYY-MM-DD
```

It reads cumulative maps through today, tomorrow and day-after and derives:

```text
tomorrow = through_tomorrow - through_today
day_after = through_day_after - through_tomorrow
later = nextDays - tomorrow - day_after
```

The split is defensive:

- negative values clamp to zero;
- if tomorrow + day-after exceeds the unfiltered `nextDays`, that row is not assigned a false date and its future quantity stays in `later`;
- if Digikala rejects the date filter entirely, the page remains available but future quantities fall back to `later` and a warning is displayed.

Live deployment output must be inspected before treating tomorrow/day-after numbers as confirmed semantics.

## Packages

The OpenAPI material indicates a Package family exists, but the exact current package list/detail path available to this seller token was not proven before V43 coding.

V43 tries a read-only candidate route:

```text
GET /open-api/v1/packages
GET /open-api/v1/packages/<package_id>
```

Failure is non-fatal and shown in the page/check output as an endpoint-not-yet-verified warning.

No package creation, shipment request, deletion or status mutation is enabled.

### Internal daily-report bridge is intentionally disabled

The user's final intended workflow is:

```text
finalized Digikala package for date X
        -> internal daily sales/report for date X
```

V43 does NOT perform this bridge because it would mutate SaleLine/inventory/accounting and must first have:

- exact live package endpoint/schema;
- exact shipped/accepted quantity meaning;
- unique package/shipment key;
- idempotency guard so refresh/retry cannot import twice;
- safe reuse of the existing authoritative internal sale/import services.

The current XLSX importer remains authoritative.

## Sales report

V43 reads current Order API rows and creates a current Jalali-month quantity report:

- total quantity found in the month;
- source order-row count;
- distinct DKP/product groups where product_id is available;
- top sellers;
- bottom sellers.

Only rows with a parseable API datetime inside the current Jalali month are included. Rows with missing/nonpositive quantity are skipped rather than silently assumed to be one item.

### Money deliberately deferred

The user ultimately wants full monetary analytics, but V43 does not invent sales amounts from an unverified field. Price/discount/final-paid semantics must first be reconciled with live order data. The page clearly states that the current report is quantity-only.

## Warehouse

V43 keeps `/digikala/warehouse/` on the V42 empirically reconciled free/sellable warehouse implementation. No V42 formula is changed.

See:

```text
docs/PROJECT_CONTEXT/20_DIGIKALA_FREE_WAREHOUSE_V42.md
```

## Returns

V43 initially exposes rows where Inventory API reports:

```text
return_stock > 0
```

It shows title/code/size/DKPC and return quantity.

The user's desired eventual bridge is:

```text
Digikala return physically received
        -> HOME inventory increase
```

But the user also wants take-back requests. Requesting take-back is NOT equivalent to physically receiving the item. Therefore V43 has no HOME write.

A later bridge must require:

- exact API return/take-back endpoint;
- exact state proving physical receipt;
- unique external return/item identifier;
- idempotent internal application;
- reuse of the V37 HOME-only return semantics without sale/receivable/account side effects.

## Isolation invariant

V43 is an external read-only center. It must not change:

```text
SaleLine
SaleSnapshot
SaleAllocation
StockBalance
InventoryMovement / InventoryAdjustment
Digikala receivable
AccountEntry
capital
materials
production
payments
XLSX import behavior
V37 standalone return behavior
calculator/economic formulas
```

The V43 source only uses the inherited GET client. No new DB model or migration exists.

## Performance

Do not load every heavy board on `/digikala/`.

The center home uses the existing light summary/delivery data. Heavy pages are opened on demand and cached:

```text
daily commitments 60s
packages          60s
sales             60s
returns           120s
warehouse         existing V42 60s
```

Pagination is bounded.

## Rollback/deployment

Pre-change rollback branch:

```text
before-digikala-center-v43-20260830
```

Build branch used during implementation:

```text
digikala-center-v43-build
```

Deployment script:

```text
server_digikala_center_v43.sh
```

It starts from pre-V43 main:

```text
a1af5a867834b24fefdbcac78c9166ab9b28587a
```

It takes a pg_dump, captures all economic/inventory invariants, protects economic/model/migration/compose sources, builds, checks migration drift, runs V37/V40/V41/V42/V43 checks, separates rate-limit-heavy warehouse live reconciliation, recreates web and requires exact before/after business invariant equality.

Expected final marker:

```text
SUCCESS: DIGIKALA CENTER V43 DEPLOYED
```

Until the user posts that output, V43 is GitHub-prepared, not confirmed live. Do not update numeric production checkpoint using assumptions.
