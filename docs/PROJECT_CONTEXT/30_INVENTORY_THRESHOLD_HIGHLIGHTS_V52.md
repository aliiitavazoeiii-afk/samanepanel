# 30 — INVENTORY THRESHOLD HIGHLIGHTS V52

Status at creation: GitHub-prepared. Do not call production-live until the user posts the final deploy success marker.

V52 is a presentation-only inventory-table alert change on the active `/inventory/` page.

## User requirement

In the HOME inventory table:

- for every color × size cell, if quantity is below 30, make the cell red;
- exclude these colors/models from all low-stock highlighting:
  - زرد
  - قرمز
  - خرسی
  - مشکی کبریتی / کبریتی مشکی
  - راه راه سرمه ای / راه راه سرمه‌ای
  - پلنگی

In the TOTAL inventory table:

- for every non-exempt color × size cell below 100, highlight it;
- below 50 = red;
- 50 through 99 = orange;
- 100 or more = normal.

The row-level final "کل" column is not threshold-colored because the rule is per color × size cell.

The KHORSHID table is unchanged.

## Active source

Route:

```text
/inventory/
-> core.inventory_v20.inventory
```

Template:

```text
templates/core/inventory_v19.html
```

## Exemption normalization

V52 uses the existing `brand_colors.norm()` helper so Persian spacing/ZWNJ variants do not create false alerts.

It also treats these naming variants as equivalent exemptions:

```text
مشکی کبریتی / کبریتی مشکی
راه راه سرمه ای / راه راه سرمه‌ای
طرح خرسی / خرسی
طرح پلنگی / پلنگی
```

The helper is deliberately presentation-only. It does not alter Color rows, stock identity, stock totals or catalog data.

## Threshold flags

`core.inventory_v20` adds display-only fields per rendered size cell:

```text
home_alert
total_alert
```

HOME:

```text
qty < 30  -> red
qty >= 30 -> normal
```

TOTAL:

```text
qty < 50        -> red
50 <= qty < 100 -> orange
qty >= 100      -> normal
```

Exempt color/model rows always return no alert class regardless of quantity.

## Frozen business boundary

V52 must not change:

- `StockBalance` quantities;
- HOME/KHORSHID calculation;
- combined stock calculation `HOME + KHORSHID`;
- inventory valuation or `InventoryModelCost`;
- capital;
- V46 HOME-only sale behavior;
- V49/V50 transfer/correction semantics;
- V51 adjustment deletion/reversal;
- sales/import/SaleSnapshot/SaleAllocation;
- Digikala fee or receivable;
- materials/production/payments/returns;
- models or migrations.

No database write occurs merely by opening the inventory page.

## Files changed

Operational presentation:

- `core/inventory_v20.py`
- `templates/core/inventory_v19.html`

Regression/deploy:

- `core/management/commands/check_inventory_highlights_v52.py`
- `server_inventory_highlights_v52.sh`

Context:

- `docs/PROJECT_CONTEXT/30_INVENTORY_THRESHOLD_HIGHLIGHTS_V52.md`
- `docs/PROJECT_CONTEXT/README.md`

## Regression contract

`check_inventory_highlights_v52` is read-only and proves:

```text
HOME 29 -> red
HOME 30 -> normal
TOTAL 49 -> red
TOTAL 50 -> orange
TOTAL 99 -> orange
TOTAL 100 -> normal
```

It also verifies all requested exemption naming variants and compiles the active inventory template.

## Rollback / deployment

Rollback branch:

```text
before-inventory-threshold-highlights-v52-20260903
```

Pre-change commit:

```text
e31cd5430a73ad4c022ad293cd144d8c5f44b6e2
```

Deploy:

```bash
cd /opt/darma-general
git pull --ff-only
bash server_inventory_highlights_v52.sh
```

The deploy script creates a PostgreSQL backup, validates exact V52 source scope, rejects migration drift, runs the read-only threshold regression, recreates web, and requires exact business/inventory/ledger snapshot equality before versus after deployment.

Production is confirmed only after the user posts:

```text
SUCCESS: INVENTORY THRESHOLD HIGHLIGHTS V52 DEPLOYED
```
