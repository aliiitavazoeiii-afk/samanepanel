# V96 — INVENTORY + RAW MATERIAL CENTER

## Purpose

Move raw-material management out of the comprehensive report and make `/inventory/` the single inventory entry point, without changing raw-material accounting, inventory valuation, production consumption, or capital formulas.

## Inventory information architecture

`/inventory/` is now a two-card center:

- **موجودی کالا** → `/inventory/stock/`
- **مواد اولیه** → `/inventory/materials/`

The finished-goods inventory remains the existing V20 implementation. Its brand selection, Darma/Takvin/Novani quantities, HOME/KHORSHID semantics, valuation rules, and transfer/adjustment links are unchanged.

## Raw materials moved from comprehensive report

The new `/inventory/materials/` page manages the exact same `RawMaterialStock` source used by the comprehensive report and capital calculations. It includes:

- fabric in warehouse;
- fabric at tailor;
- fabric in depot;
- elastic in warehouse;
- elastic at tailor;
- fabric add / transfer / edit / delete;
- elastic add / transfer / edit / delete.

All mutations reuse the existing functions in `core/material_flow.py`. V96 does not replace their accounting or stock semantics.

## Fabric duplicate-row presentation fix

Warehouse fabric is intentionally stored lot-by-lot. `add_warehouse_stock()` creates a new `RawMaterialStock` row for each fabric purchase so unit price and reversal provenance remain available.

V96 therefore does **not** merge or rewrite historical DB rows. Instead it groups fabric for display by canonical material identity inside each location:

- current rows use `material_key`;
- legacy blank-key rows are mapped by normalized Persian title to the same canonical key when possible;
- each visible color row shows the sum of kilograms;
- each visible color row shows the exact sum of value;
- displayed price is weighted average = total value / total quantity;
- internal purchase lots remain expandable for transfer/edit/delete.

Example: an old white lot of 100 kg plus a new white lot of 252 kg displays as one **سفید / 352 kg** row while both source lots remain in the database.

This fixes the visible duplicate white/navy rows without destroying accounting provenance.

## Comprehensive report

The detailed `موجودی و مواد اولیه` management domain is removed from the visible comprehensive-report UI.

The report backend still calculates:

- `finished_inventory_total = finished_inventory_value_v17()`
- `raw = _raw_material_context()`
- `inventory_total = finished_inventory_total + raw["materials_total"]`
- current capital using the same inventory/material total as before.

Therefore moving the UI does not change capital, raw-material valuation, sales metrics, or historical capital reconstruction.

For compatibility, the old report POST handler is not destructively removed; the normal visible raw-material entry point is now the Inventory center.

## No migration / no data rewrite

V96 introduces no model or migration and does not merge existing `RawMaterialStock` records. Deployment is expected to be state-neutral.

## Regression

`python manage.py check_inventory_material_center_v96`

Checks include:

- `/inventory/` routes to the new center;
- `/inventory/stock/` preserves V20 finished inventory;
- `/inventory/materials/` renders the raw-material center;
- legacy/current white fabric resolve to one display key;
- same-color lots aggregate quantity/value correctly;
- actual production raw-material rows preserve exact total quantity/value after grouping;
- source-lot provenance remains visible;
- comprehensive-report capital formula markers remain unchanged;
- new raw-material actions reuse existing `material_flow` functions;
- GET/regression performs no raw-material, inventory, movement, setting, or account writes.

## Deployment

`bash server_inventory_material_center_v96.sh`

Expected final marker:

`SUCCESS: INVENTORY + MATERIAL CENTER V96 DEPLOYED`

GitHub state is not proof of production deployment. Production is confirmed only after the actual VPS deployment passes regressions and PRE / PROJECTED / FINAL state invariants match.
