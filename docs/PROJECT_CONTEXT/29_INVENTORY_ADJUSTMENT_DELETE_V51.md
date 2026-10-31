# 29 — INVENTORY ADJUSTMENT DELETE V51

Status at creation: GitHub-prepared. Do not call production-live until the user posts the final deploy success marker.

V51 is a narrow follow-up to V50 for `/inventory/operations/`. It adds a guarded delete action beside manual stock-correction rows in the existing "آخرین گردش‌های موجودی" table.

## User requirement

If the user enters a wrong physical count through the V50 "اصلاح موجودی" form, they want to delete that correction directly from the movement report and return that stock cell to the quantity it had immediately before that correction.

This must not turn the movement table into a generic delete surface for sales, production, transfers, returns, or other stock history.

## Active route/source

Main page remains:

```text
/inventory/operations/
-> core.inventory_operations_v15.inventory_operations
```

V51 adds:

```text
/inventory/operations/adjustments/<adjustment_id>/delete/
-> core.inventory_operations_v15.inventory_adjustment_delete
```

The delete endpoint is login-protected and POST-only.

## Delete scope

`InventoryAdjustment` is also used by other workflows, especially standalone returns V37, so V51 must not treat every `adjust:<id>` movement as a user correction.

The current V50 inventory-correction form deliberately stores an empty note because the correction-reason field was removed. Standalone returns and historical/other structured adjustments use non-empty marker/provenance notes, for example:

```text
[standalone-return-v37] ...
```

Therefore V51 exposes delete only when all of these are true:

```text
InventoryAdjustment.applied = true
InventoryAdjustment.note = ""
movement_type = adjust
reference = adjust:<InventoryAdjustment.id>
movement brand/size/color/location/delta exactly match the adjustment
```

No delete button is shown for:

- sale movements;
- manual transfers;
- production;
- purchases;
- standalone returns V37;
- marked historical repair/reconcile adjustments;
- sale recalculation/reversal movements;
- any adjustment movement that cannot be matched exactly to a live applied blank-note inventory correction.

The backend repeats these checks even if a crafted POST bypasses the UI.

## Safe reversal semantics

V50 input remains absolute physical stock, while the stored adjustment remains a delta:

```text
current = 160
target entered = 140
stored InventoryAdjustment.delta = -20
```

Deleting that correction performs the exact inverse:

```text
current after correction = 140
reverse delta = +20
final after delete = 160
```

The reversal is atomic and locks:

- the `InventoryAdjustment`;
- its exact `InventoryMovement`;
- the affected `StockBalance`.

The `StockBalance` lock is acquired before the final newer-movement check so a concurrent sale/transfer/correction using the normal stock services cannot slip between the guard and the reversal.

Only after the stock quantity has been restored successfully are the original adjustment row and its exact `adjust:<id>` movement deleted.

No finance/account row is created to compensate for the stock change. Like the original physical correction, removing the correction naturally changes current finished-inventory value/capital back by the valuation effect of that stock quantity.

## Critical newer-movement guard

V51 refuses to delete an older correction if any later `InventoryMovement` exists for the exact same:

```text
brand + size + color + location
```

after the original `adjust:<id>` movement.

Reason: once a sale, transfer, production event, or newer physical correction has happened on that same cell, blindly deleting the old correction would cross newer history and could invalidate the latest physical truth.

Example:

```text
160 -> correction target 140
then later sale/transfer/correction changes same cell
```

The old correction is no longer directly deletable. The user must enter a new absolute physical correction instead.

This guard is intentionally conservative.

## V46 / V50 boundaries preserved

V51 does not change:

- V46 HOME-only Darma sale behavior;
- permission for HOME to become negative from sales;
- KHORSHID changing only through explicit manual transfer;
- V50 fixed KHORSHID -> HOME transfer workflow;
- V50 correction input semantics: blank = unchanged, explicit 0 = final zero, entered number = absolute physical final stock;
- internal delta calculation `target-current`;
- V50 user-facing removal of the correction-reason field;
- stock transfer combined-quantity neutrality.

## Files changed

Operational:

- `core/inventory_operations_v15.py`
- `core/urls.py`
- `templates/core/inventory_operations.html`

Regression/deploy:

- `core/management/commands/check_inventory_operations_v51.py`
- `server_inventory_adjustment_delete_v51.sh`

Context:

- `docs/PROJECT_CONTEXT/29_INVENTORY_ADJUSTMENT_DELETE_V51.md`
- `docs/PROJECT_CONTEXT/README.md`

No model or migration change is introduced.

Protected unchanged source includes:

- `core/models.py`
- `core/models_final.py`
- `core/final_services.py`
- `core/variant_sale_v12.py`
- `core/returns_v37.py`;
- finance/capital/valuation sources;
- sale/XLSX importer sources;
- material/payment sources.

## Regression contract

`check_inventory_operations_v51` runs inside rollback transactions and proves:

```text
HOME 160
absolute correction target 140 -> delta -20
safe delete -> HOME returns to 160
InventoryAdjustment and exact adjust:<id> movement are removed
```

It also proves a standalone-return-style marked adjustment is not deletable from this page:

```text
manual test adjustment note = [standalone-return-v37] ...
delete attempt -> blocked
stock/adjustment remain unchanged
```

Finally it proves the newer-movement safety guard:

```text
HOME 160 -> correction 140
later explicit transfer +1 -> HOME 141
attempt delete old correction -> blocked
HOME remains 141
adjustment/movement remain intact
```

All regression data is rolled back and persistent stock/adjustment/transfer/movement counts must match their pre-test values.

## Rollback/deployment

Pre-change rollback branch:

```text
before-inventory-adjustment-delete-v51-20260903
```

Pre-change Git commit:

```text
e8f12014976b6494575c3cecb3bcf68a06e13760
```

Deploy:

```bash
cd /opt/darma-general
git pull --ff-only
bash server_inventory_adjustment_delete_v51.sh
```

The script creates a PostgreSQL backup, checks exact source scope and migration drift, runs both V50 and V51 rollback regressions before and after live web recreation, and requires exact deployment-time business invariant equality.

Production is confirmed only after the user posts:

```text
SUCCESS: INVENTORY ADJUSTMENT DELETE V51 DEPLOYED
```
