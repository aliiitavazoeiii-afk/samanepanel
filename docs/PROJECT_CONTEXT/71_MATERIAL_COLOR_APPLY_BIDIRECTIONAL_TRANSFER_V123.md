# V123 — Only current-month unapplied material reports; color-only materials application; two-way inventory transfer

Parent: V122 `v122-material-net-current-open`.

## User rules

1. **Previous Jalali months are ALWAYS collapsed archives**, even when some work remains unfinished. Clicking an archive expands the saved sheets; never push old sheets into the current section and never display "بازمانده ماه قبل".
2. Current top KPIs and five base-color progress cards count ONLY colors from **this Jalali month** whose raw fabric has not had positive color-specific `MaterialReportConsumption`. Exclude any applied-material color even when its finished-goods output is pending. Never include old/future sheets or another brand's color.
3. For a color still unapplied, sum cut and saved delivery over all rolls of that color before netting a shortfall/surplus. Saved delivery and inventory-applied are separate columns. Applied materials contribute zero to top color cut/received/rolls/weight. Legacy V118 audit helper remains read-only/unchanged.
4. A new button under the raw materials/costing table applies **just one model/color's fabric and 16/25 elastic consumption**, deducting from the tailor's raw-material stock. Other colors on the same invoice are untouched. Bulk apply remains available and updates per-color allocations. The new `MaterialReportColorUse` table stores per-color contributions so shared elastic inventory is aggregated once and reapplication is idempotent.
5. Previous bulk applies without allocation are lazily reconciled to the saved report input when the first color-only button is clicked. If saved input no longer reconciles exactly, abort atomically rather than consuming any second stock. Full-sheet apply reconciles and rewrites per-color attribution from all present inputs in one transaction. Full-sheet unapply reverses aggregated stock and clears attribution. No finished-goods output, tailor wages or balances are changed by a material-only operation.
6. Rename transfer header to **انتقال**, preserve the old directions and add a fourth field with **از انبار به خانه** (default) / **از خانه به انبار**. The existing "انبار" is StockLocation.KHORSHID (legacy "خورشید"), not RawMaterialStock.WAREHOUSE. Use the existing `StockTransfer` and `InventoryMovement` ledger both directions. Must reject insufficient physical source stock and roll back all colors on error. No self-transfer or stock creation.
7. Submitting the transfer via fetch must **not refresh the page**; retain the chosen date, brand, size and direction, clear only entered quantities, and repaint live stock counts. A real browser refresh resets the form (especially direction) to default warehouse→home. Do not use localStorage/sessionStorage or persist a direction preference between sessions. Ordinary non-JS POST may redirect.
8. Show historical transfers of both directions, edit protected by the existing V80 later-manual-adjustment guard. No alteration to unrelated sidebar, finance or wholesale formulas.

## Schemas

V123 migration `0021_material_color_use_v123`: creates ONLY one new `core_materialreportcoloruse` table for per-color raw material allocations. No modification to existing material report, stock or finance records. Current-account Caddyfile must remain identical.

## Guarded deploy

Branch `v123-material-color-apply-inventory-transfer`, script `server_material_color_transfer_v123.sh`. Requires V121 Pedram reconciliation already complete; never repairs Pedram during this material-stock feature deploy. Takes PostgreSQL backup before migration. Guards changes against exact V122 parent, protects Caddyfile SHA256 and all existing financial/physical stock data with PRE / PROJECTED / FINAL business hashes (includes MaterialReportConsumption). Applies migration 0021, runs V123 check plus legacy read-only material/fabric/wholesale/finance checks, then replaces web only. No inventory/transfers are posted during deployment.

CI workflow on GitHub uses isolated PostgreSQL test database for color-level shared elastic and bidirectional transfer regressions, plus synthetic monthly material reporting.


## Additional V123 inventory warning refinement

The same inventory page `core/inventory_v20.py` / `templates/core/inventory_v19.html` now reserves prominent bright red for **exact zero** in total and home cells; 1–9 units receives a restrained pale-red background; ten or more receives no warning. The update supersedes older 30/50/100 thresholds and earlier exempt models for visual warnings; negative physical balances are weak-red (not strong-zero). `core/management/commands/check_inventory_alert_v123.py` verifies boundary values -1,0,1,9,10,30,50,99,100 in both tables, all brands. Safe deploy pins known exact inventory Python and template blob IDs, thereby preserving stock quantity/valuation business logic.
