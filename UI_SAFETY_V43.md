# UI SAFETY V43 — DIGIKALA CENTER

V43 reorganizes the external Digikala integration into an isolated mini-app under `/digikala/`.

## User-facing sections

```text
/digikala/                         center home
/digikala/orders/                  daily commitments grouped by DKP/DKPC
/digikala/packages/                package visibility
/digikala/packages/<package_id>/   package detail
/digikala/sales/                   current Jalali-month sales quantity report
/digikala/warehouse/               existing V42 free warehouse board
/digikala/returns/                 current return-stock visibility
```

The center uses a common Digikala-only navigation bar and intentionally stays separate from the normal sales/accounting/inventory workflow.

## Daily orders

The current unfiltered commitments list remains the source of truth for current quantities. V43 groups rows by `productId` (DKP) and exposes each `variantId` (DKPC), parsed size, supplier code and due quantity inside the DKP card.

For tomorrow/day-after presentation V43 attempts read-only cumulative commitment filters using `search[is_effective]=true` and `search[to_commitment_date]=YYYY-MM-DD`. The date split must reconcile back to the unfiltered `nextDays` total. If the filter is rejected or any row becomes inconsistent, V43 fails closed: it does not invent a date and keeps the affected future quantity in the generic later bucket.

No date-specific count may be hard-coded.

## Packages

The partial OpenAPI material available during implementation confirms a Package API family exists, but the exact currently authorized package endpoint/schema was not yet live-verified. V43 therefore probes the candidate read-only list/detail route and keeps the page operational with a visible warning if it is unavailable.

Package write/request operations are NOT enabled in V43.

Most importantly, no package can create/replace an internal SaleDay/SaleLine in V43. The existing XLSX importer remains authoritative for internal Digikala daily sales until a later bridge phase has exact package semantics and idempotency.

## Sales report

V43 reads the Order API and builds a current Jalali-month quantity-only report: total item quantity, product count, top products and bottom products.

The monetary report is intentionally not fabricated. Price/discount/final-sale semantics must first be reconciled from a live Order row. Until then `price_ready=False` and the UI says so.

No Order API row is persisted into internal SaleLine/accounting in V43.

## Warehouse

`/digikala/warehouse/` remains the V42 empirically reconciled free-stock calculation. V43 does not alter its formulas or business boundary.

## Returns

V43 currently shows `return_stock` rows from the inventory API. This is visibility only.

A Digikala return/request must NOT increase HOME merely because it exists or because a take-back request was submitted. The future HOME bridge is allowed only when an exact external state proves the physical item was actually received by the user, and it must have an idempotent external return/item key so refresh/retry cannot add inventory twice.

V43 does not activate this bridge.

## Hard isolation boundary

V43 must not create/update/delete or synchronize:

- SaleLine / SaleSnapshot / SaleAllocation;
- StockBalance / InventoryMovement / InventoryAdjustment;
- Digikala receivable / AccountEntry / capital;
- XLSX import results;
- materials / production / payments;
- standalone V37 return records;
- calculator/economic formulas.

All V43 business API requests use the existing `get_json()` GET client. The only external POST elsewhere in this integration remains the official token refresh flow inherited from V40.

No new model or migration is allowed in this phase.

## Performance

Heavy sections are on-demand, not loaded on the center home:

- daily commitments: 60-second cache;
- packages: 60-second cache;
- sales: 60-second cache;
- returns: 120-second cache;
- V42 warehouse: existing 60-second cache.

Pagination is bounded defensively. The deployment separates live checks with a rate-limit wait before the full V42 warehouse reconciliation.

## Deployment safety

Rollback code branch:

```text
before-digikala-center-v43-20260830
```

Deployment script:

```text
server_digikala_center_v43.sh
```

It must take a pg_dump, protect all accounting/inventory/import/model/migration files, run regression/source checks, verify no migration drift, perform live read checks and require exact pre/post business invariant equality.

Expected success marker:

```text
SUCCESS: DIGIKALA CENTER V43 DEPLOYED
```

Do not call V43 live until the user posts successful production output.
