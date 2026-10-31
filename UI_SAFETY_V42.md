# UI SAFETY V42 — DIGIKALA FREE WAREHOUSE

V42 adds a separate read-only Digikala warehouse page for the seller's current free/sellable stock physically held by Digikala.

## Scope

New route:

```text
/digikala/warehouse/
```

The page reads current Digikala Open API inventory and commitment data on demand and caches the derived board for 60 seconds.

## Empirically reconciled calculation

The seller's live account was inspected for variant `57642066` (PACK-5 / 36-38). The observed inventory row and seller workflow established the calculation used by V42:

```text
sellable_dk_stock = max(0, available - marketplace_seller_stock + reserve)
requested_dk_reserve = max(0, reserve - seller_commitment)
reserved_from_current_dk_stock = min(sellable_dk_stock, requested_dk_reserve)
free_dk_stock = sellable_dk_stock - reserved_from_current_dk_stock
```

`seller_commitment` is the current per-variant `commitment.all` quantity from the commitments list.

The calculation is performed per variant. `free_dk_stock` is never allowed below zero. Return/dead stock is not counted as free/sellable warehouse stock.

The first full live reconciliation supplied by the user produced:

```text
TOTAL SELLABLE IN DK = 256
TOTAL RESERVED IN DK = 200   # requested reserve before per-row stock cap in the diagnostic script
TOTAL FREE IN DK     = 63
VARIANTS WITH FREE   = 26
```

The V42 UI deliberately reports `reserved_total` as the quantity actually covered by current sellable Digikala stock (`min(stock, requested reserve)`) so that, per row and in total:

```text
sellable = reserved_from_current_stock + free
```

Any requested Digikala reserve beyond current stock is shown separately as `reserve_over_stock` rather than making free stock negative.

## Read-only boundary

V42 must never:

- create/edit/delete internal SaleLine, SaleSnapshot or SaleAllocation;
- change StockBalance or InventoryMovement;
- change Digikala receivable, AccountEntry, capital or valuation;
- replace or feed the XLSX sales importer;
- modify internal product composition, material, payment, production, return or calculator state;
- call Digikala inventory/order/shipment write endpoints.

All V42 business API calls are GET requests through the existing V40 client. The only POST permitted anywhere in this integration remains the official V40 token refresh endpoint.

## Performance boundary

The warehouse page is not loaded as part of the main dashboard or the main Digikala delivery page. It is opened explicitly by the user. The result is cached for 60 seconds. This avoids repeatedly fetching the approximately 1,382 inventory variants during ordinary navigation.

## Display contract

The page must show:

- total free/sellable unreserved Digikala stock;
- total current sellable Digikala stock before reservation;
- current reservation quantity covered by that stock;
- number of variants with free stock;
- searchable per-variant code, size, title, sellable stock, reserved stock and free stock;
- filters for free-stock rows, zero-free/refill rows and all warehouse rows;
- a warning when requested reservation exceeds current stock for one or more variants.

No hard-coded live quantity is allowed. All numbers are derived from the current API response.
