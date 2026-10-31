# 19 — DIGIKALA DELIVERIES V41

V41 refines the V40 read-only Digikala Open API integration into an operational delivery board.

Status at creation: **committed to GitHub, not yet confirmed live**.

## Why V41 exists

The V40 dashboard showed `GET /orders` row count (396 at the first probe) as "current orders". The user clarified that this is not the operational number they need each day. In the Digikala seller panel the important number is the number of effective commitments / items that still need delivery.

A live reconciliation was performed against the official commitments API.

Observed live values at the final probe before V41 implementation:

```text
TOTAL COMMITMENTS     = 202
EFFECTIVE COMMITMENTS = 201   # user-confirmed seller panel
```

The unfiltered commitments list returned 69 product variants and its item-level counters summed to:

```text
nextDays = 201
today    = 0
delayed  = 1
all      = 202
```

This exactly explains why the earlier user-observed 194 could no longer be reproduced: new commitments had arrived. No synthetic subtraction (for example `onTheWay`) is used.

The official metadata endpoint exposes:

```text
summary_statistics.totalCommitments
summary_statistics.effectiveCommitments
summary_statistics.nonEffectiveCommitments
summary_statistics.totalPenalty
```

The list endpoint exposes per-variant:

```text
variantId
supplierCode
titleFa
orders
commitment.nextDays
commitment.today
commitment.delayed
commitment.all
onTheWay
product_image
product_link
```

V41 uses `effectiveCommitments` as the headline "باید تحویل بدهم" number and uses `nextDays + today` for the itemized actionable rows. If the two sources temporarily disagree, the UI explicitly shows a warning rather than silently forcing equality.

## V41 files

New:

```text
core/digikala_delivery_v41.py
core/management/commands/check_digikala_delivery_v41.py
server_digikala_deliveries_v41.sh
UI_SAFETY_V41.md
```

Changed:

```text
core/digikala_views_v40.py
templates/core/digikala_v40.html
templates/core/dashboard_excel.html
```

No model, migration, accounting, inventory, sale, XLSX-import, payment, material, return, calculator, route or Docker secret-mount semantics are changed.

## User-facing behavior

Dashboard Digikala card now prioritizes:

- باید تحویل بدهم = metadata `effectiveCommitments`;
- کل تعهدات;
- inventory variant count;
- invoice count.

Dedicated `/digikala/` page shows:

- effective commitments headline;
- total commitments;
- delayed quantity;
- actionable variant count;
- itemized delivery table with supplier code, variant ID, parsed size label, full Digikala title, quantity to deliver, number of orders, optional product image/link;
- client-side search over code/title/size/variant ID.

The itemized table is based only on current GET responses. It is not persisted to the DARMA database.

## Read-only boundary

V41 must not:

- create or edit SaleLine/SaleSnapshot/SaleAllocation;
- change StockBalance or InventoryMovement;
- change Digikala receivable or AccountEntry;
- replace the XLSX importer;
- alter capital, raw/finished inventory valuation, fees, costs, wages, payments or returns;
- call Digikala write endpoints.

The only POST still reachable from the Open API integration is the V40 official token refresh endpoint.

## Deployment

Rollback branch:

```text
before-digikala-deliveries-v41-20260830
```

Deploy script:

```text
server_digikala_deliveries_v41.sh
```

It takes a pg_dump, captures live business invariants, source-scope guards from pre-V41 main `4695bb45c685c300e9695dbb12f1ee735462ecb2`, builds, runs Django/V37/V40/V41 checks, verifies secret isolation, recreates web, and requires exact before/after business invariant equality.

Expected marker:

```text
SUCCESS: DIGIKALA DELIVERIES V41 DEPLOYED
```

Do not record a V41 production checkpoint until the user posts the actual deploy output.
