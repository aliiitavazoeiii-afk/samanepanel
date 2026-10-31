# 28 — INVENTORY OPERATIONS V50

Status at creation: GitHub-prepared. Do not call production-live until the user posts the final deploy success marker.

This is a narrow follow-up to V49 for `/inventory/operations/` and preserves all existing accounting, sale, valuation, model and stock-service semantics.

## User-requested UI layout

The two operation cards are now compact and designed to sit side-by-side on desktop:

```text
[ انتقال از خورشید به خانه ] [ اصلاح موجودی ]
```

Both remain responsive and stack on smaller screens.

## Transfer workflow

V49 transfer behavior remains unchanged:

```text
date | brand | size
all Darma colors with quantity inputs
```

Direction remains fixed in backend code:

```text
KHORSHID -> HOME
```

Blank/zero transfer fields are ignored. Every entered color creates a normal `StockTransfer`; the entire batch is atomic and existing KHORSHID availability guards remain active.

## Bulk absolute correction workflow

The V49 single-color absolute correction is replaced by a multi-color absolute physical-count form:

```text
date | brand | size | location
all colors for selected brand
[ثبت اصلاح موجودی]
```

The correction-reason input is removed.

The selected brand controls which color group is shown in the page. Backend validation independently reads only `colors_for_brand(selected_brand)`, so hidden/stale fields from another brand cannot be applied.

For each visible color:

- blank input = do not change that color;
- explicit `0` = final counted stock is zero;
- any non-negative number = exact final stock for that brand/size/color/location cell.

Example:

```text
HOME M pink currently = 160
entered counted pink = 140
final HOME M pink = 140
internal InventoryAdjustment.delta = -20
```

Multiple entered colors are processed inside one outer transaction. If any target is invalid, the whole correction submit fails.

## Existing total-stock rule remains unchanged

The correction only changes the selected physical location cell(s). The normal inventory page continues to derive combined stock from the existing location balances.

For Darma:

```text
combined = HOME + KHORSHID
```

Therefore if HOME is physically recounted and KHORSHID is unchanged, the displayed combined quantity naturally becomes the new HOME quantity plus the existing KHORSHID quantity.

There is no separate forced total reconcile and no compensating finance entry.

## Audit/model compatibility

No model or migration changes are introduced.

`InventoryAdjustment` remains delta-based internally. V50 uses the existing `_set_inventory_target()` logic for each entered color:

```text
delta = target_qty - locked_current_qty
```

Then the existing `sync_inventory_adjustment()` service applies the delta and records the normal movement ledger.

Reason/note is intentionally blank because the user removed the correction-reason field.

## Files changed

Operational:

- `core/inventory_operations_v15.py`
- `templates/core/inventory_operations.html`

Regression/deploy:

- `core/management/commands/check_inventory_operations_v50.py`
- `server_inventory_operations_v50.sh`

Context:

- `docs/PROJECT_CONTEXT/28_INVENTORY_OPERATIONS_V50.md`
- `docs/PROJECT_CONTEXT/README.md`

No changes to:

- `core/models.py`
- `core/models_final.py`
- migrations
- `core/final_services.py`
- sales/import logic
- accounting formulas
- capital formulas
- inventory valuation formulas

## Regression contract

`check_inventory_operations_v50` proves inside rollback transactions:

```text
multi-color absolute correction:
  color A HOME 160 -> target 140 => delta -20
  color B HOME 20  -> target 35  => delta +15

explicit zero:
  target 0 => final stock 0

bulk transfer:
  two colors x120 KHORSHID -> HOME
  combined quantity unchanged by transfer
```

It also verifies the template:

- compiles;
- has two compact desktop cards;
- has brand-specific multi-color correction fields;
- has no correction reason field;
- has no old single-color correction selector;
- has no transfer from/to selectors.

All test data is rolled back and post-test ledger counts must equal pre-test counts.

## Safety

Rollback branch:

```text
before-inventory-operations-v50-20260903
```

Deploy:

```bash
cd /opt/darma-general
git pull --ff-only
bash server_inventory_operations_v50.sh
```

The deploy script creates a full PostgreSQL backup, checks source scope and migration drift, runs the rollback regression before and after web recreation, and requires exact business snapshot equality across deployment.

Production is confirmed only after the user posts:

```text
SUCCESS: INVENTORY OPERATIONS V50 DEPLOYED
```
