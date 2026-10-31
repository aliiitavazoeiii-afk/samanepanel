# V56 — DARMA INVENTORY PAGE USES THE CENTRAL COST

## Incident

After V55, the accounting/capital path correctly valued current Darma inventory from the single date-effective Darma cost, but the active `/inventory/` page still calculated Darma row/size/grand values from legacy `InventoryModelCost` color×size rows.

Observed live example after V55:

```text
Darma qty: 10,874
central Darma cost: 61,000
correct Darma value: 663,314,000
inventory page still showed: 665,549,521
```

This was a UI/service-path inconsistency, not a new capital movement. The page was still using the pre-V55 valuation source.

## Root cause

Active route `/inventory/` resolves to `core.inventory_v20.inventory`.

Before V56, `core/inventory_v20.py` built this map for the selected brand:

```text
InventoryModelCost(brand, color, size) -> unit_cost
```

and for every non-Takvin brand it used that map to calculate `capital = total * unit_cost`. That meant Darma still escaped the V55 single-source rule on this page.

The same page's “add color/model” form also asked for and wrote a separate per-color/per-size Darma cost, which violated the single-source rule even though V55 accounting no longer used those rows.

## V56 rule

For Darma, every current-inventory display/value path must use:

```text
darma_cost_for(today)
```

No Darma `InventoryModelCost` row may affect:

- cell tooltip cost;
- per-color value;
- per-size value;
- Darma page grand value.

Therefore:

```text
Darma inventory page value = all displayed Darma shorts × current effective Darma cost
```

At 10,874 shorts and 61,000 toman:

```text
10,874 × 61,000 = 663,314,000 toman
```

## Files changed

### `core/inventory_v20.py`

- imports `darma_cost_for`;
- adds `_inventory_unit_cost()` as the page valuation selector;
- Darma always returns the central current rate;
- Darma does not build/use the `InventoryModelCost` map;
- `grand_value` and size totals therefore use the same rate as V55 capital accounting;
- adding a new Darma color no longer requires or writes a user-entered `InventoryModelCost` cost.

Takvin and Novani behavior remains unchanged.

### `templates/core/inventory_v19.html`

For Darma:

- removes the separate editable “price per item” field from the add-color form;
- shows the current central Darma rate read-only;
- links cost changes to Settings -> Rules;
- explicitly states that inventory value is quantity × current central cost.

### Regression

`check_inventory_darma_cost_v56`

Checks:

- every Darma inventory cell resolves to `darma_cost_for()`;
- page quantity equals all Darma stock quantity;
- page value equals `qty × central rate` exactly;
- changing a legacy Darma `InventoryModelCost` inside a rollback transaction cannot change the Darma page unit cost;
- inventory template compiles and contains the central-cost UI markers.

Expected live example at the incident quantity/rate:

```text
DARMA_QTY=10874
DARMA_UNIT_COST=61000
DARMA_INVENTORY_PAGE_VALUE=663314000
SUCCESS: DARMA INVENTORY PAGE COST V56 CHECK PASSED
```

## Safety

V56 is not an accounting/data repair and must change no business data. It changes only the active inventory valuation/display path and future add-color behavior for Darma.

Rollback branch:

`before-inventory-page-darma-cost-fix-v55-20260906`

Rollback/base commit:

`f355c243f3c63f976bf82c8744971acad972bb7d`

Production must not be called V56-confirmed until the VPS prints:

`SUCCESS: DARMA INVENTORY PAGE COST V56 DEPLOYED`
