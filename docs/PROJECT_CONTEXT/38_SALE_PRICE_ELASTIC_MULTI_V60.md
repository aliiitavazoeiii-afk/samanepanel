# V60 — DATE-EFFECTIVE DARMA/TAKVIN SALE PRICES + MULTI-COLOR ELASTIC PAYMENT

Date prepared: 2026-09-06

## User-requested behavior

### Darma and Takvin sale prices

Changing a product selling price from Products/Codes must not retroactively rewrite today's already-recorded sales or older sales.

The new rule is:

- each Darma/Takvin ProductSize may have date-effective default sale-price rules;
- Products/Codes exposes a Jalali `قیمت فروش از تاریخ` field;
- default effective date in the UI is tomorrow;
- if a new price is entered today with tomorrow as the effective date, today's unsaved/new sale defaults still use today's old price;
- from tomorrow, new sale rows for tomorrow use the new price;
- an existing `SaleLine.sale_price` is authoritative/frozen and is never rewritten by a later default-price rule;
- a manual price override entered on a specific SaleDay remains the exact saved price for that line;
- Digikala XLSX imports use the rule effective on the selected SaleDay when creating a new line;
- historical SaleDays therefore resolve their own dated default instead of today's current product price.

The source is `core/sale_price_v60.py`, stored as date-keyed `AppSetting` rows. No schema migration is required.

The legacy `ProductSize.default_sale_price` remains the fallback for dates before the first V60 rule. Scheduling a future price for an existing ProductSize does not overwrite that fallback.

## Active sale paths moved to V60

`core/urls.py` routes:

- sale size screen -> `core.sale_entry_v60.sale_size`
- manual sale save -> `core.sale_entry_v60.sale_line_save`
- Digikala XLSX import -> `core.daily_order_views_v60.import_daily_orders`
- Products/Codes -> `core.pricing_v60.settings_products`
- product create/edit -> `core.settings_product_v60.settings_product_form`

`core.sale_entry_v60.sale_size` places the date-effective price into the ProductSize object only in memory for rendering. It does not save ProductSize.

`core.sale_entry_v60.sale_line_save` uses `sale_price_for(ps, day.date)` only as the default if no explicit price is submitted.

`core.daily_order_views_v60` pre-seeds only missing/zero new import lines with the SaleDay-effective price, then delegates to the established V23 import engine. Existing positive SaleLine prices are left untouched.

## Bulk Darma sale-price workflow

The bulk Darma price grid also receives a Jalali effective date. It schedules a rule for every matching active Darma ProductSize instead of calling the old immediate `apply_group_prices()` path.

This is important: a future bulk price must not mutate today's `ProductSize.default_sale_price` and leak into today's sales.

## Takvin parity

Takvin sale prices now use the same V60 date-effective default-sale-price model as Darma. This is independent from Takvin **cost** rules:

- sale price = customer/Digikala selling price per product/size/date;
- Takvin cost = per-short COGS/finished-inventory valuation by size/date.

Changing one must never silently change the other.

## Multi-color elastic purchase in one payment

Before V60, one material payment for elastic represented exactly one color plus quantities/prices for variants 16 and 25.

V60 adds an `elastic_multi` purchase payload:

```text
one BusinessPayment
  -> one actual paid amount
  -> many elastic colors
     -> each color can have qty/price for 16
     -> each color can have qty/price for 25
```

Blank color/variant fields are ignored.

The full authoritative payload is stored in the existing V14 purchase `MoneyMovement` ledger, whose note is a TextField. `BusinessPayment.note` keeps only a compact V60 compatibility marker because that model field is limited.

## Accounting semantics for multi-color elastic

Existing V22 accounting remains authoritative:

When goods are received:

```text
Mellat -= actual paid
Raw material inventory += sum(each color/variant qty * its unit price)
capital delta = invoice value - actual paid
```

No supplier-prepayment asset is created for received goods.

When goods are not received and the user enters only a payment, the existing material-prepayment behavior remains unchanged.

All colors in a multi-color elastic purchase are one atomic payment operation. If any populated color/variant is invalid, the whole payment fails.

## Edit and delete safety

V60 preserves V22's guarded edit/delete semantics:

- date/note/actual-paid-only edits on an unchanged physical purchase adjust finance only;
- changing color/quantity/unit price reverses the old physical purchase and applies the new one atomically;
- deletion reverses the exact purchase quantity/value contribution plus the payment effect;
- reverse refuses when current warehouse state cannot safely support removing the purchased quantity/value.

Legacy one-color elastic payments remain readable/editable; the V60 UI expands them into the new all-color matrix with the old color prefilled.

## UI

`templates/core/payments_v60.html` inherits the stable V22 payments page and adds `core/static/core/payments_elastic_multi_v60.js`.

The script converts each elastic purchase block into an all-color matrix with columns:

- color;
- kg elastic 16;
- price 16;
- kg elastic 25;
- price 25.

It also calculates the invoice total across all colors and restores values when editing an existing V60 multi-color purchase.

## Regression

`check_sale_price_elastic_multi_v60` verifies transactionally:

- Darma future sale-price rule does not leak into the previous day;
- Takvin future sale-price rule does not leak into the previous day;
- rules activate on/after their effective date;
- scheduling a rule does not overwrite legacy current ProductSize defaults;
- an existing SaleLine price remains frozen after a later rule;
- V60 routes are active;
- a two-color elastic purchase parses as one payload;
- invoice arithmetic is exact;
- both color/variant quantities apply and reverse to their starting quantities;
- all test writes roll back.

Success marker:

`SUCCESS: SALE PRICE + ELASTIC MULTI V60 CHECK PASSED`

## Deployment

`server_sale_price_elastic_multi_v60.sh`:

1. backs up PostgreSQL;
2. verifies V60 source scope;
3. builds and runs Django + V48/V55/V56/V57/V58/V59/V60 regressions;
4. carries forward the idempotent V59 Takvin purchase-stock repair because the user's previous V59 attempt stopped before that repair;
5. verifies that repair can change only Takvin quantity/finished value/capital by the computed amount;
6. calculates projected state under the new image;
7. recreates live web;
8. requires final live state to equal the projection.

Deployment success marker:

`SUCCESS: SALE PRICE + ELASTIC MULTI V60 DEPLOYED`

V60 is not production-confirmed until the user posts this server marker.

## Rollback anchor

Branch:

`before-sale-price-elastic-multi-v60-20260906`

Commit:

`122ac377fffadac4d91e3dd7ba9bce84bbd0a0fe`
