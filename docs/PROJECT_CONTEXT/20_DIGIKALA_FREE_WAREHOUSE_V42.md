# 20 — DIGIKALA FREE WAREHOUSE V42

V42 adds a separate read-only operational page for checking current Digikala warehouse stock that is still free/sellable and has not already been consumed by current reservations.

Status at creation: **committed to GitHub, not yet confirmed live**.

## User requirement

The user does not want the raw Digikala `warehouse_stock` field by itself. They want, for every product variant, the quantity physically available in Digikala's sellable warehouse pool that is still unsold/unreserved.

Example intent:

```text
PACK-5 / 36-38
sellable Digikala warehouse stock = 15
reserved from Digikala stock      = 11
free / unsold                     = 4
```

## Live evidence used to derive the calculation

For Digikala variant `57642066` (PACK-5 / 36-38), a live inventory row showed:

```text
reserve                  = 15
marketplace_seller_stock = 845
warehouse_stock          = 8
available                = 836
```

A per-item inventory detail call showed 8 physical items: 6 in normal sellable warehouse `انبار دانش` and 2 in `انبار مرجوعی مرکزی`. Therefore the return warehouse items were not part of the normal sellable pool.

The commitments data for that variant showed the seller's own current commitment quantity, and the user's operational rule is that Digikala fulfills orders from its own sellable warehouse stock first; only the remainder becomes seller delivery commitment.

The validated live relation was:

```text
sellable_dk_stock = available - marketplace_seller_stock + reserve
```

and the reservation attributable to the Digikala pool is derived as:

```text
requested_dk_reserve = reserve - seller_commitment
```

V42 computes this safely per variant:

```text
sellable_dk_stock = max(0, available - marketplace_seller_stock + reserve)
requested_dk_reserve = max(0, reserve - seller_commitment)
reserved_from_current_dk_stock = min(sellable_dk_stock, requested_dk_reserve)
free_dk_stock = sellable_dk_stock - reserved_from_current_dk_stock
reserve_over_stock = max(0, requested_dk_reserve - sellable_dk_stock)
```

`seller_commitment` comes from `commitment.all` in the current commitments list.

The first full diagnostic supplied by the user returned:

```text
TOTAL SELLABLE IN DK = 256
TOTAL RESERVED IN DK = 200
TOTAL FREE IN DK     = 63
VARIANTS WITH FREE   = 26
```

That diagnostic's `TOTAL RESERVED` summed requested reserve even when a row's requested reserve exceeded current stock. V42 instead caps displayed/aggregated `reserved_stock` to the current sellable stock per row, preserving the identity `sellable = reserved + free`. Any excess reservation is separately exposed as `reserve_over_stock`.

These live values are evidence for the algorithm, not constants. V42 must never hard-code 256, 200, 63 or 26.

## New route

```text
/digikala/warehouse/ -> core.digikala_views_v40.digikala_warehouse
```

The main `/digikala/` page includes a direct link to this separate warehouse section.

## New files

```text
core/digikala_warehouse_v42.py
templates/core/digikala_warehouse_v42.html
core/management/commands/check_digikala_warehouse_v42.py
server_digikala_warehouse_v42.sh
UI_SAFETY_V42.md
```

Changed:

```text
core/digikala_views_v40.py
core/urls.py
templates/core/digikala_v40.html
docs/PROJECT_CONTEXT/README.md
docs/00_NEW_CHAT_READ_FIRST.md
```

## Page behavior

The page displays dynamically:

- free/sellable unreserved stock total;
- sellable Digikala warehouse stock before current reservations;
- reservation quantity covered by current Digikala stock;
- free-stock variant count;
- per-variant supplier code, variant ID, parsed size, full title, sellable stock, reserved stock and free stock;
- seller commitment as an audit hint;
- optional warning where requested reservation is larger than current sellable warehouse stock;
- client-side search;
- filters: free stock / zero free (needs refill) / all.

Default filter is `free` because this is the user's recurring operational question.

## API/performance behavior

V42 reads:

```text
GET /open-api/v1/commitments
GET /open-api/v1/inventories
```

Inventory pagination uses size 100; commitments use size 50. Page counts are bounded defensively. The final derived board is cached for 60 seconds.

Crucially, the V42 warehouse calculation is **not fetched on every dashboard or `/digikala/` page load**. It is only fetched when the user opens `/digikala/warehouse/`, preventing unnecessary repeated reads of roughly 1,382 inventory variants on the small production VPS/API quota.

`?refresh=1` bypasses the 60-second board cache.

## Read-only invariant

No internal business data is written. V42 must not modify accounting, inventory, sales, Digikala receivable, materials, payments, production, returns, SaleSnapshots, SaleAllocations, XLSX import behavior or capital.

## Deployment

Rollback branch:

```text
before-digikala-free-warehouse-v42-20260830
```

Deployment script:

```text
server_digikala_warehouse_v42.sh
```

Expected success marker:

```text
SUCCESS: DIGIKALA FREE WAREHOUSE V42 DEPLOYED
```

Do not update the numeric production checkpoint until the user posts actual successful server output and the final invariant block.
