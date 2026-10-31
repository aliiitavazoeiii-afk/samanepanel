# 27 — INVENTORY OPERATIONS V49

Status at creation: GitHub-prepared. Do not call production-live until the user posts the final deploy success marker.

This change is intentionally narrow and follows an explicit user workflow request for `/inventory/operations/`.

## User-requested adjustment semantics

The old form asked for a delta such as `-3` or `+5`.

V49 changes the operator input to **absolute counted stock**:

```text
site currently shows: 160
physical count entered: 140
final stock after submit: 140
internal adjustment delta: -20
```

Important: the existing `InventoryAdjustment.delta` model and `sync_inventory_adjustment()` service are NOT redesigned. The backend reads the locked current `StockBalance`, computes:

```text
delta = target_qty - current_qty
```

then records the existing adjustment object and applies it through the existing synchronization service. This preserves movement/audit history while giving the user absolute-count input.

If entered target already equals current quantity, no adjustment row or movement is created.

The physical target input is non-negative.

## User-requested transfer workflow

The previous transfer form required one color at a time plus explicit:

- from location;
- to location;
- quantity;
- note.

V49 replaces that entry workflow with:

```text
date | brand | size
all Darma colors with quantity inputs
[ثبت انتقال]
```

Direction is fixed and explicit in backend code:

```text
KHORSHID -> HOME
```

Blank and zero color fields are ignored.

Each entered color still creates its own normal `StockTransfer` row and is applied by the unchanged `sync_stock_transfer()` service. The whole multi-color submit is wrapped in one transaction so it is all-or-nothing.

Existing availability safety remains: if any requested color exceeds KHORSHID stock, the entire batch fails and no color from that submit is transferred.

## Brand/location scope intentionally unchanged

V49 does NOT broaden physical two-location semantics to Novani/Takvin.

Current rule remains:

- Darma: HOME + KHORSHID, manual transfer allowed;
- Novani: one logical inventory bucket represented by HOME;
- transfer route remains Darma-only.

This preserves the user's instruction not to change anything outside the requested entry workflow.

## Files changed

Operational files:

- `core/inventory_operations_v15.py`
- `templates/core/inventory_operations.html`

Regression/deploy:

- `core/management/commands/check_inventory_operations_v49.py`
- `server_inventory_operations_v49.sh`

No changes to:

- `core/models.py`
- `core/models_final.py`
- migrations
- `core/final_services.py`
- sale/import logic
- accounting formulas
- capital formulas
- valuation formulas

## Regression contract

`check_inventory_operations_v49` runs real service calls inside an atomic rollback test and proves:

```text
absolute correction: 160 -> target 140 -> stored adjustment delta -20
bulk transfer: two colors x120, KHORSHID decreases and HOME increases
combined transfer quantity unchanged
all test InventoryAdjustment / StockTransfer / InventoryMovement rows rolled back
```

It also compiles the template and checks that old `from_location` / `to_location` transfer fields are gone.

## Deployment safety

Rollback code branch:

```text
before-inventory-operations-v49-20260903
```

Deploy:

```bash
cd /opt/darma-general
git pull --ff-only
bash server_inventory_operations_v49.sh
```

The script:

1. starts/checks PostgreSQL;
2. creates a full pg_dump;
3. captures economic/inventory/ledger counts;
4. verifies exact V49 source scope;
5. protects models, formulas, sales/import and existing stock service source;
6. builds the web image;
7. rejects migration drift;
8. compiles the inventory operations template;
9. runs rollback regression preflight;
10. verifies preflight left persistent state unchanged;
11. recreates live web;
12. reruns regression;
13. requires exact before/after business snapshot equality.

Production is confirmed only after the user posts:

```text
SUCCESS: INVENTORY OPERATIONS V49 DEPLOYED
```
