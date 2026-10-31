# UI SAFETY V44 — DIGIKALA CENTER CORRECTIONS

V44 corrects the read-only Digikala Center after the first production-facing V43 observations.

## User-confirmed problems corrected

- Tomorrow and day-after commitment buckets were empty because V43 combined the future `to_commitment_date` filter with `is_effective=true`. The official API defines `is_effective` against today's performance date. V44 removes that incompatible future filter and derives tomorrow/day-after from cumulative commitment cutoffs.
- Product visibility no longer depends on a Product-creation endpoint. `/digikala/products/` is derived from the already-working inventory list, so old/current products are included.
- Sales report tries the order-history read endpoint first, falls back safely, and does not send speculative sort fields that can cause API validation errors.
- Returns are no longer inferred from top-level `return_stock`. The user confirmed actual return merchandise is physically located in a warehouse whose title contains `مرجوعی` (for example `انبار مرجوعی مرکزی`). V44 counts only those nested warehouse rows.
- API reads are shared/cached and pagination is bounded/concurrent to reduce page latency on the small VPS.

## Read-only boundary

V44 must never create/update/delete:

- SaleLine / SaleSnapshot / SaleAllocation;
- StockBalance / InventoryMovement;
- Digikala receivable / AccountEntry / capital;
- materials / production / payments / internal returns;
- XLSX daily-order imports.

All business data endpoints remain GET-only. The only POST in the wider integration remains the existing credential refresh endpoint from V40.

## Performance boundary

- shared inventory rows cache: 10 minutes;
- shared commitment rows cache: 3 minutes;
- orders derived board: 3 minutes;
- products/packages/sales/returns boards: 10 minutes;
- center home must not synchronously call the full Digikala API fan-out;
- inventory and paginated API pages use bounded concurrency, max 3 workers.

Manual `?refresh=1` remains available for operational freshness.

## Return warehouse rule

For each inventory variant, V44 inspects `warehouse` entries and counts only entries where the warehouse title contains `مرجوعی`. Quantity preference is the warehouse entry `count`, falling back to `physical_stock` only when `count` is absent/zero. Sellable warehouse rows such as `انبار دانش` must not appear in the returns page.

## No live checkpoint assumption

Code on GitHub is not proof of production deployment. Record V44 as live only after the user posts the deploy SUCCESS marker and final invariant block.
