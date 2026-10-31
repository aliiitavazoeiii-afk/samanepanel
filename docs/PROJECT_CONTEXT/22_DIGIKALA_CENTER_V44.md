# 22 — DIGIKALA CENTER V44

V44 is the corrective pass after the user opened V43 in production-facing use and reported four concrete problems: future-date commitments were not split, old products were absent, sales requests failed, pages were slow, and the returns page showed sellable items instead of the physical return warehouse.

Status at creation: **prepared on GitHub; not production-confirmed until successful V44 server output is posted**.

## Confirmed user rules / observations

1. Tomorrow and day-after must show both quantity and the actual DKP/DKPC products due on those dates.
2. Product visibility must include existing/old products; it must not depend on whether a product was newly created.
3. Digikala pages must not perform a large fan-out of API requests on every open.
4. Actual returned merchandise is defined physically by inventory located in a warehouse whose title contains `مرجوعی` (for example `انبار مرجوعی مرکزی`). Top-level `return_stock` is not the authoritative return list for this UI.

## Commitment date fix

V43 combined:

```text
search[is_effective]=true
search[to_commitment_date]=future-date
```

The official schema defines `is_effective` relative to today's performance date. That combination can suppress future commitments and left tomorrow/day-after empty.

V44 uses only cumulative `search[to_commitment_date]` for tomorrow and day-after. It derives the current past+today base from the unfiltered row:

```text
through_today = commitment.all - commitment.nextDays
```

then:

```text
tomorrow = through_tomorrow - through_today
day_after = through_day_after - through_tomorrow
later = nextDays - tomorrow - day_after
```

The two future cutoff reads run concurrently with bounded workers. If the identity does not reconcile, the row fails closed into later rather than inventing a date.

## Products

New route:

```text
/digikala/products/
```

Products are grouped by `product_id` (DKP) from the already-working inventory endpoint. Variant rows expose DKPC, supplier code, size and warehouse stock. This includes old/current products and does not depend on a product-creation endpoint.

## Sales report

V44 tries read-only sources in this order:

```text
/open-api/v1/orders/history
/api/v3/orders/history
/open-api/v1/orders
```

It no longer sends the speculative `sort=id` parameter that could cause validation failure. The report remains quantity-only until price/discount units are verified against live data.

## Returns

V44 scans each inventory row's nested `warehouse` entries and counts only entries whose `warehouse_title`/title/name contains `مرجوعی`.

Quantity source:

```text
warehouse.count
```

with `physical_stock` only as fallback if count is absent/zero.

Sellable warehouse locations such as `انبار دانش` must never appear as returns merely because another top-level field is nonzero.

## Performance

New shared module:

```text
core/digikala_shared_v44.py
```

It provides bounded concurrent pagination and shared raw caches:

- inventory rows: 10 min;
- commitment rows: 3 min;
- derived order board: 3 min;
- products/packages/sales/returns: 10 min;
- warehouse V42 derived board: 5 min.

Django cache is changed from implicit per-process LocMemCache to `FileBasedCache` under `/tmp/darma-shared-cache`, because Gunicorn runs 3 workers and process-local cache caused repeated API misses across workers.

The `/digikala/` center home no longer calls V40 summary + V41 delivery live. It opens immediately and only displays a cached delivery KPI if one already exists.

## Package fallback

V44 attempts read-only package list routes in a safe fallback sequence, including the Open API path and the compatible Seller API path. Package parsing now handles `package_id`, `package_number`, nested status, nested warehouse title, `received_at_forecast` and `received_at`.

## Safety

V44 does not modify internal models, migrations, sales, stock, receivable, accounting, materials, payments, production, returns, XLSX import or capital. All business API calls remain GET-only; the existing V40 credential-refresh POST remains the only POST in the integration.

Rollback code branch:

```text
before-digikala-center-v44-20260830
```

Expected deploy marker:

```text
SUCCESS: DIGIKALA CENTER V44 DEPLOYED
```

Do not advance the numeric live checkpoint until the user posts the actual final invariant block.
