# V105 — SALE-MARGIN TARGET + CODE SUMMARY + MATERIAL KPIs

Prepared: 2026-10-01  
Branch: `v105-margin-code-summary-material-kpis`  
Base: V104 `4ae2f6a65daf718f55fa968feb7c15f2585810f2`

## 1. Target-price semantics corrected

V104 interpreted target profit as:

```text
net profit / finished cost
```

The user's intended meaning is:

```text
net profit / proposed sale price
```

V105 therefore solves the minimum sale price `P` such that:

```text
(P - canonical Digikala fee(P) - finished cost) / P >= target margin
```

The canonical Digikala fee source is unchanged:

`core.finance.digikala_fee_for_unit()`

The practical recommendation is still rounded upward to the next 1,000 toman.

Concrete regression case:

- finished cost = 210,000
- target sale margin = 15%

The exact solution must have at least 15% net margin on sale, and one toman below the exact minimum must fail the 15% condition.

## 2. Calculator result ordering

Both calculator outputs now present:

1. net toman profit;
2. sale margin = net profit / sale price;
3. profit on cost = net profit / finished cost.

Sale margin is shown before profit-on-cost, matching the user's decision metric.

## 3. Profitability table grouped by product code

The large ProductSize-first table is replaced by a code-first summary.

Each active Darma/Takvin product code appears once.

Summary columns:

- code;
- active size count;
- average current sale price;
- average finished pack cost;
- average Digikala fee;
- average net profit;
- average sale margin;
- average profit on cost.

The averages are simple arithmetic means across the active sizes of that code.

Clicking the code expands a collapsed detail row with the same metrics for each individual size.

Current-price/cost sources remain unchanged:

- sale price: `sale_price_for(product_size, today)`
- Darma cost: `pack_qty * darma_cost_for(today)`
- Takvin cost: `pack_qty * takvin_cost_for(size, today)`
- fee: `digikala_fee_for_unit(current sale price, today)`

No sale, ProductSize, sale-price rule, cost rule or inventory data is modified.

## 4. Table alignment

V105 explicitly centers numeric headers and numeric values in profitability tables.

Money cells stay LTR/isolate for Persian pages, but use centered alignment rather than inheriting the global left-aligned money style.

Column order is:

```text
... net profit -> sale margin -> profit on cost
```

## 5. Material-report KPI position and typography

V92 originally mounted its five KPI cards beside the search tools.

V105 mounts the KPI strip immediately below the page title/header and before the search area.

KPI typography is split into:

- larger numeric value;
- smaller unit/meta text.

This fixes mixed number/unit sizing such as small numbers with visually oversized "طاقه" or "کیلو".

## 6. Average cut KPI

A sixth card is added:

`میانگین تعداد برش`

Scope:

- all saved MaterialReportBlock history;
- Darma only;
- only the five canonical base colors:
  - black / مشکی
  - white / سفید
  - navy / سرمه‌ای
  - pink / صورتی
  - cream / کرم
- only positive saved cut values.

Formula:

```text
average cut = sum(all positive saved base-color cuts) / count(cut entries)
```

Rounded half-up to a whole piece.

Novani and dynamically added material/model keys are excluded.

## 7. Average finished-cost KPI intentionally deferred

The project already has a canonical live material cost engine:

`core.material_cost_v23.calculate_model_cost()`

It uses:

```text
fabric kg * live fabric price
+ used elastic16 kg * live price
+ used elastic25 kg * live price
+ sewing wage
---------------------------------
cut quantity
```

The user's latest description emphasized fabric + elastic but did not explicitly confirm whether sewing wage must be included in the new all-page KPI.

V105 therefore does not introduce a new global average finished-cost KPI yet. The existing per-sheet live finished-cost calculation is untouched.

## 8. Regression

Run:

`python manage.py check_margin_material_v105`

It verifies:

- the 210,000 / 15% case uses sale-margin semantics;
- the solver is minimal;
- grouped code coverage matches every active ProductSize exactly once;
- code summary averages equal their size-detail averages;
- sale-margin column appears before profit-on-cost;
- size details are collapsed by default;
- average cut matches an independent all-history Darma/base-color calculation;
- material KPIs are mounted below the title, not beside search;
- number/unit typography markers are present;
- no business state is written.

Expected marker:

`SUCCESS: MARGIN + MATERIAL KPI V105 CHECK PASSED`

## Rollback

`before-margin-code-summary-material-kpis-v105-20261001`

## Deployment

Use:

`bash server_margin_material_v105.sh`

Expected final marker:

`SUCCESS: MARGIN + MATERIAL KPI V105 DEPLOYED`
