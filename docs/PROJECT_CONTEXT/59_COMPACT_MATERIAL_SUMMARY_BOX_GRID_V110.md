# V110 — COMPACT MATERIAL SUMMARY BOX GRID

Base: `v109-material-color-rolls-summary-ui` on top of the V108 stable baseline.

## User-visible change

The collapsed header of each saved material sheet returns to a compact, low-height layout.

Desktop uses exactly five horizontal summary boxes:
1. brand -> destination
2. models
3. fabric codes
4. material apply state
5. applied delivery

Pending delivery increase/reduction remains inside box 5 as smaller subtext, so it does not create a second summary row.

The boxes are intentionally rectangular/compact rather than vertically stacked pills.

## Preserved behavior

Unchanged:
- V109 five color cards and per-color roll counts;
- V106 three delivery mini-inputs and canonical summed target;
- material sync, consumption, stock, wage and cost formulas;
- V108 finance/report/calculator baseline;
- all accounting and inventory state.

## Regression

`python manage.py check_material_summary_box_grid_v110`

Required marker:

`SUCCESS: COMPACT MATERIAL SUMMARY BOX GRID V110 CHECK PASSED`

Production marker:

`SUCCESS: COMPACT MATERIAL SUMMARY BOX GRID V110 DEPLOYED`

After production confirmation, future feature branches should continue from V110 or a later confirmed descendant.
