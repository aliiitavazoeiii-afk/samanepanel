# 23 — DIA GALLERY DAILY SALES V45

V45 adds a new daily-sales channel requested by the user: **Dia Gallery**.

Status at creation: **prepared on GitHub; not production-confirmed until successful V45 server output is posted**.

## User rule

Inside the existing daily-sales date screen, add a separate `Dia Gallery` box without changing the existing Darma/Takvin/Anbaresh/Digikala workflows.

Dia Gallery rules:

- physical goods are Darma goods;
- entry is directly by Darma color and Darma size;
- each entered quantity is one physical short;
- fixed sale price is **71,000 toman per short**;
- no Digikala fee applies;
- sold quantity is deducted from Darma finished stock;
- a dedicated receivable called `فروش Dia Gallery` increases by gross sale value;
- that receivable is shown under accounts / ریز حساب‌ها;
- the receivable is an owned account asset and therefore participates in capital;
- capital delta of a Dia sale is `gross - Darma inventory cost`, because stock value falls while Dia receivable rises.

## New data model

`DiaGallerySale` is deliberately separate from `SaleLine` so Digikala XLSX authoritative replacement cannot overwrite Dia Gallery sales.

Fields:

```text
day
size
color
quantity
inventory_applied_quantity
unit_price
unit_cost
```

Unique identity:

```text
(day, size, color)
```

`unit_price` is fixed to 71,000 by backend logic. `unit_cost` is captured from the current Darma `InventoryModelCost` on first positive application and then kept as the historical COGS basis for that daily color/size row.

Migration:

```text
core/migrations/0015_dia_gallery_sale.py
```

## Physical inventory semantics

The Dia Gallery sync uses the existing Darma HOME/KHORSHID stock primitives.

For a positive quantity delta:

1. use the existing Darma auto-transfer logic to replenish HOME from KHORSHID where available;
2. deduct the physical color/size units from HOME;
3. record inventory movement with reference `dia-gallery:<id>`.

For a negative/edit delta:

- restore the reversed quantity to Darma HOME;
- update `inventory_applied_quantity` to the new target.

No separate Dia Gallery inventory asset exists. Dia Gallery is a sales channel consuming Darma physical stock.

## Receivable semantics

Dedicated account key:

```text
dia_gallery
```

Display title:

```text
فروش Dia Gallery
```

Each active Dia line has an idempotent AccountEntry:

```text
reference = dia-gallery:<id>:receivable
entry_type = dia_gallery_sale
delta = quantity * 71000
```

Editing the quantity replaces that line's receivable entry rather than stacking duplicates.

Current Dia receivable is account opening balance + account-entry deltas.

No receipt/settlement flow was requested in V45; V45 only establishes sales receivable. A later settlement feature must move value from Dia receivable to the destination bank/account without changing capital.

## Capital/reporting semantics

Comprehensive report now adds Dia receivable to the existing `accounts_total` component:

```text
accounts_total = manual account/person rows + Dia Gallery receivable
```

The existing capital equation remains structurally the same:

```text
capital = accounts/persons + finished inventory + raw materials + Digikala receivable + assets - Takvin debt
```

Dia therefore enters through the accounts component, not by inventing a second capital formula.

Dia sales are included in:

- daily sales total/gross/profit/COGS;
- comprehensive sales report;
- dashboard today/month totals;
- 14-day sales/profit chart;
- Darma color-sales counts, because the physical goods are Darma colors.

Dia is not added to Darma product-code profitability because the workflow has no Darma pack/product-code identity; it is a direct color sale.

## UI

New route:

```text
/sales/<day_id>/dia-gallery/
```

Daily sale landing adds a separate Dia Gallery box.

The Dia page shows:

- fixed 71,000 unit price;
- current day quantity and gross;
- current total Dia receivable;
- Darma colors as rows;
- Darma sizes M, L, XL, XXL, 3XL, 4XL as columns.

Comprehensive report injects an automatic read-only row named `فروش Dia Gallery` into `ریز حساب‌ها` with the current receivable.

## Isolation / do-not-change rules

V45 does not alter:

- Digikala fee engine;
- Digikala receivable;
- Digikala XLSX parser/replacement semantics;
- normal SaleLine snapshot/allocation semantics;
- payment/material/production workflows;
- standalone return V37;
- Takvin rules;
- Novani rules.

Dia sales live in their own model and cannot be touched by the Darma/Takvin XLSX replacement union.

## Regression / deployment

Regression command:

```text
python manage.py check_dia_gallery_v45
```

It performs a transaction-rollback test proving:

- qty 1 reduces Darma total stock by 1;
- Dia receivable rises by 71,000;
- capital component delta equals `71,000 - frozen unit cost`;
- increasing to qty 2 is delta/idempotent;
- resetting to zero restores total Darma quantity and receivable;
- the entire test rolls back with no persistent data.

Rollback code branch:

```text
before-dia-gallery-v45-20260831
```

Pre-Dia commit:

```text
663ad61339a97dfcd0cc910a82f855dd63dcb7c5
```

Deploy script:

```text
server_dia_gallery_v45.sh
```

Expected success marker:

```text
SUCCESS: DIA GALLERY V45 DEPLOYED
```

Do not advance the production live checkpoint until the user posts the actual successful deploy output and final invariant block.
