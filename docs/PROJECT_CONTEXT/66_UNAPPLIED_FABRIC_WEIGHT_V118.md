# V118 — Unapplied coded fabric rolls + all-time delivered weight by color

Base: `v117-unified-ui-fabric-count`, which includes the Oct 14 `v116-fabric-roll-count-audit` plus prior sidebar and Comprehensive Report UI changes.

**User clarification supersedes V116/V117 roll-count semantics.**

## Five-color cards on `/material-report/`

- `roll_count`: For each of the five Darma colors, count distinct nonempty `input_data[color].fabric_code` values from saved `MaterialReportBlock` rows **only if that same color has no positive `MaterialReportConsumption` row** for that sheet with `kind=FABRIC` and `material_key=color`. Duplicate eligible codes count only once. Sheets with blank codes never invent rolls. Applied fabric consumption is the sole authoritative filter; a finished-goods/output delivery is not a raw-material consumption, and other colors in the same multi-color sheet are independent.
- `total_weight` and `total_weight_display`: Sum the nonnegative, stored `input_data[color].weight` for **all saved Darma sheets**, including already-applied rows and rows missing a fabric code, exactly once per sheet/color. Unit kg. This is the **all-time recorded delivered weight**, not current warehouse/tailor stock, not the count or weight of only unapplied rolls, and not the monthly six-KPI `weight_display`.
- `expected/delivered/pending`: Preserved from existing report output logic, independent of these roll and weight figures. The monthly six-KPI summary is unchanged.
- If a fabric consumption record is reversed through existing workflows, its coded roll can become eligible again. No automatic fabric stocks, inventory transfers, material applications, migrations, or business data writes.

## Regression
`python manage.py check_fabric_roll_count_v116`: read-only synthetic white/pink cases for material-vs-sewing applications, duplicate codes, uncoded rows, partially applied other-color rows, and overall kg totals; also prints live per-color `eligible_codes`, `applied_excluded_codes`, `uncoded_sheet_ids`, and summed weight. No real data modifications.

`python manage.py check_material_summary_box_grid_v110`: read-only compact grid and V118 roll/weight aggregate cross-check.

`python manage.py check_ui_rail_report_v116`: preserves V117 sidebar/Comprehensive Report presentation.

## Guarded deployment
Branch: `v118-unapplied-fabric-rolls-color-weight`
Script: `bash server_unapplied_fabric_v118.sh`
Expected marker: `SUCCESS: V118 UNAPPLIED FABRIC ROLLS + COLOR WEIGHT DEPLOYED` with `PRE = PROJECTED = FINAL`.

The user did **not** run V117 deployment. Switch directly from their currently deployed branch to this V118 branch using the safe instructions. Do not run older V116 or V117 installation scripts afterwards.
