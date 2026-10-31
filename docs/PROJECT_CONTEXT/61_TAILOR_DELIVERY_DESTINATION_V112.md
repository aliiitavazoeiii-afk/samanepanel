# V112 — Tailor delivery: choose Home or Khorshid once per sheet sync

**Base:** `v111-product-definition-catalog-sales` at `2eb146ab287fd0d098e8c6c70aaa245e5912d202`.
V108 stable baseline, V109–V110 material UI and V111 product definition are in ancestry.

## User interaction

The existing **«همگام‌سازی تحویل و موجودی»** button in each material report now opens a native modal instead of the previous generic browser confirm.

- Darma: **خانه** or **خورشید** (one selection per submitted sheet)
- Novani: **خانه** only (unchanged brand-specific inventory policy)
- **انصراف** closes the modal without saving

After selection the **entire submitted sheet** is reconciled in one transaction:
all *newly applied differences* for all active colors/models and sizes go to the selected stock location. The three sub-boxes per size still sum to the pre-existing canonical applied target. Tailor wage reconciliation still runs automatically, only on the difference in the overall applied total.

## Historical safety and idempotency

Canonical `MaterialReportOutputApplied.quantity` per block/model/size is unchanged and remains the number already applied. New additional breakdown table:
`MaterialReportOutputLocation(applied, location, quantity)` with uniqueness on (applied, location).

Migration: `core/migrations/0019_material_output_location.py`, dependent on existing `0018_productcode_title`. No inventory or accounting rows are backfilled by migration.

When an older material sheet with an already applied total is next synced, the location breakdown is initialized for that existing total at the old brand-default destination (Darma Khorshid / Novani Home), *without generating stock movements*. This matches the previous live sync destination. The total must exactly equal the sum of allocation rows; otherwise the transaction fails closed.

New increments only change **target minus previously applied quantity**. Re-selecting another destination with an unchanged total produces zero inventory delta and zero production movements: existing pieces **never move** because of the dialog choice.

For a decrease, the system deducts only from the location(s) associated with this material sheet's previously applied pieces, preferring the selected location first. If there is insufficient real stock to reverse the tracked pieces, the transaction rolls back completely; historical stock is not silently reallocated.

Production movements are created once for each actual incremental location change, using reference `material-report:<id>:output-sync-v112`.

## Protected invariants

Unchanged:
- core material input structure and tables;
- three delivery sub-boxes per size, sums, cut difference and 5-color KPIs;
- wage accounting/rate formula and existing ledger;
- raw material consumption/apply and undo paths;
- existing home/khorshid stock model and cost formula;
- previously applied old material output rows and old production movements;
- sales, finance, calculator and product definitions.

Only added a separate *accounting of applied pieces by warehouse*, not another inventory system.

## Regression

`python manage.py check_material_output_destination_v112` verifies under database rollback:
- two different colors received together into Home;
- an additional batch of both colors received into Khorshid;
- original Home stock unchanged;
- repeated sync with another selected warehouse = zero delta/zero duplicate movement;
- controlled reduction deducts from tracked location;
- legacy no-location applied total classifies to old Khorshid without stock writes;
- no persistent database state change from regression;
- modal and destination buttons are present.

Deploy script additionally runs V108/V105/V106/V110/V111 checks and compares PRE/PROJECTED/FINAL hashes of existing business models plus the new allocation table projected/live hashes.

**Production confirmation marker:**

`SUCCESS: TAILOR DELIVERY WAREHOUSE V112 DEPLOYED`

All future new work should continue from a production-confirmed V112 descendant, not from earlier branches.
