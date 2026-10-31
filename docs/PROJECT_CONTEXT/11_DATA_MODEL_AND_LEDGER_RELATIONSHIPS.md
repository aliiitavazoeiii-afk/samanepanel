# 11 — DATA MODEL AND LEDGER RELATIONSHIPS

This file explains which database models represent identity, physical stock, historical sale accounting, finance, raw-material stock and cumulative production state. It is intended to prevent debugging against the wrong layer.

Last synchronized: 2026-08-29 after confirmed V37 live deployment.

---

# PART A — CATALOG / IDENTITY

## 1. Brand

`Brand(name, active)`

`name` is unique.

Important business names:

- `دارما`
- `تکوین`
- `Novani`
- `انبارش`

Brand name carries business semantics; do not create spelling variants as new brands.

---

## 2. Size

`Size(name, sort_order)`

Name is unique.

Business-valid size sets are brand-specific even though Size table is global.

---

## 3. Color

`Color(name, code, active)`

Name is unique.

Use normalization helpers before deciding a label is a new color.

---

## 4. ProductCode

Important fields:

```text
code
brand
pack_qty
active
note
```

Unique constraint:

```text
(brand, code)
```

A code belongs to one brand.

Do not create duplicate alias product rows when a title alias should resolve to an existing canonical code.

---

## 5. ProductComposition

Fields:

```text
product
color
qty
```

Unique constraint:

```text
(product, color)
```

This defines fixed pack composition.

It is source of truth for current fixed-composition pack returns and current fixed-composition product behavior.

It is **not** authoritative for historical actual sale colors if SaleAllocation exists.

Variable-color `s3` intentionally cannot be treated as a normal fixed composition.

---

## 6. ProductSize

Fields:

```text
product
size
default_sale_price
unit_cost
active
```

Unique constraint:

```text
(product, size)
```

Many operational screens use ProductSize identity.

A SaleLine points to ProductSize, not directly to ProductCode + Size separately.

---

# PART B — FINISHED STOCK

## 7. StockLocation

Known keys:

```text
home
khorshid
```

These are globally defined physical/logical locations, but brands use them differently.

---

## 8. StockBalance

Fields:

```text
brand
size
color
location
qty
```

Unique constraint:

```text
(brand, size, color, location)
```

This is the current aggregate finished-stock quantity.

Important: StockBalance is current state, not provenance/history.

For forensic questions such as "why did this cell change?", inspect InventoryMovement / InventoryAdjustment / SaleAllocation / production ledgers as appropriate.

---

## 9. InventoryMovement

Fields:

```text
movement_type
brand
size
color
location
delta
reference
created_at
```

Movement types:

```text
purchase
sale
transfer
production
adjust
```

This is an audit trail of stock changes. `reference` ties movements to higher-level workflows.

Examples from project history include references such as:

```text
sale:<id>:recalc
material-report:<block_id>:output-sync-v35
diagnostic-reset-after-1405-06-03-v24
```

Do not dump every movement by default in diagnostics; aggregate by reference/count when history is large.

---

## 10. InventoryAdjustment

Fields:

```text
date
brand
size
color
location
delta
note
applied
```

This is the explicit adjustment object used for manual/standalone-return style stock changes.

V37 standalone returns create positive HOME InventoryAdjustment rows and call `sync_inventory_adjustment`.

Do not directly set `applied=True` or mutate StockBalance without the existing synchronization service.

---

## 11. InventoryModelCost

Fields:

```text
brand
color
size
unit_cost
```

Unique:

```text
(brand, color, size)
```

This supports finished-stock valuation by model/color/size.

Before assuming a fixed 61,000 value for every current Darma/Novani cell, inspect current valuation helper and InventoryModelCost state.

---

# PART C — SALES

## 12. SaleDay

Fields:

```text
date unique
created_at
updated_at
```

There is one SaleDay per Gregorian date representing the corresponding Jalali business day.

---

## 13. SaleLine

Fields:

```text
day
product_size
quantity
inventory_applied_quantity
sale_price
```

Unique constraint:

```text
(day, product_size)
```

This is crucial: there cannot be two normal SaleLine rows for the same day/product-size under this constraint.

When a "ghost duplicate" is suspected, inspect quantity/product identity/resolver rather than assuming duplicate rows are possible.

`quantity` is business pack/item count at ProductSize level.

`inventory_applied_quantity` tracks how much has been applied to physical stock by the sync service.

---

## 14. SaleSnapshot

One-to-one with SaleLine.

Fields:

```text
unit_cost
pack_qty
digikala_fee_unit
updated_at
```

This is historical accounting evidence.

Current report metrics prefer snapshot values.

Never rewrite old snapshots due to current price/cost/composition changes.

---

## 15. SaleAllocation

Fields:

```text
sale_line
color
location
qty
is_replacement
```

This is the authoritative record of actual physical colors/locations deducted for a sale.

Uses:

- reversal restores these exact quantities;
- daily report color breakdown uses allocations first;
- replacement colors can be identified.

For a historical sale with SaleAllocation, do not infer physical color from current ProductComposition.

---

## 16. SaleShortage

Fields:

```text
sale_line
source_color
qty
resolved
target_color
created_at
```

This records insufficient-stock situations and optional replacement resolution.

Do not hide shortage by clamping current stock or dropping the record.

---

## 17. Replacement

Older/related model with:

```text
sale_line
source_color
target_color
qty
```

Before modifying replacement logic, inspect which replacement model/path is active in current services rather than assuming both are used identically.

---

# PART D — FINANCE / RECEIVABLE

## 18. Account

Known keys include concepts such as:

```text
melat
mofid
digikala
pedram
takvin
```

`opening_balance` is separate from AccountEntry movement history.

---

## 19. AccountEntry

Fields:

```text
date
account
delta
title
reference
entry_type
note
created_at
```

This is used for ledger-style account movements, notably Digikala sale/receipt references.

`reference` should be stable/idempotent where possible.

Example:

```text
sale:<SaleLine.id>:digikala
receipt:<DigikalaSettlement.id>:digikala
```

Never delete a settlement/sale ledger entry without understanding how the aggregate receivable total is computed/rebuilt.

---

## 20. DigikalaSettlement

Fields:

```text
date
amount
note
created_at
```

This is the receipt event object.

The economic effect is not complete unless its Mellat and AccountEntry sides are synchronized.

---

## 21. ExcelManualRow

Fields include:

```text
section
title
amount
unit_price
quantity
note
sort_order
active
```

Sections:

```text
accounts
persons
inventory
materials
assets
```

Current capital uses active account/person rows and asset rows. Raw materials/finished inventory now have dedicated live systems, so legacy manual sections should not be casually mixed into current valuation without checking report code.

Examples of important manual rows include Mellat and tailor/person/supplier-account style rows.

---

## 22. ExcelManualSetting

Fields:

```text
key
label
value
```

Important current settings include concepts such as:

- Takvin debt;
- Digikala receivable base.

The Digikala editable UI may store derived base rather than the exact desired current total. See accounting doc.

---

## 23. AppSetting

String key/value configuration.

Used for current fee/rule settings and historical feature ledgers such as material-report wage-piece state.

Do not delete arbitrary versioned AppSetting keys because some are idempotency/history markers.

---

## 24. MoneyMovement

Fields:

```text
date
kind
amount
from_account
to_account
title
affects_capital
note
```

Kinds include:

```text
transfer
expense
settlement
purchase
receipt
```

V22 uses MoneyMovement for explicit prepayment/settlement ledger payloads.

Do not assume every finance movement is represented only in AccountEntry.

---

## 25. BusinessPayment

Fields:

```text
date
payee
amount
note
created_at
```

Current V22 extends semantics through helper ledgers/purchase notes rather than adding all details as columns.

`amount` is actual paid cash under V22 material-purchase semantics, which may differ from invoice/goods value.

A BusinessPayment row alone is not enough to reconstruct physical purchase unless purchase ledger/note data is available.

---

# PART E — RAW MATERIALS

## 26. RawMaterialStock

Core fields:

```text
kind        # fabric / elastic
location    # warehouse / tailor, plus depot patched for current model
material_key
variant
 title
quantity
unit_price
unit
note
active
```

`total_value = quantity * unit_price`.

Current code dynamically extends `RawMaterialStock` with:

```text
material_key
variant
DEPOT location option
```

This is current aggregate raw-material state.

For elastic, `variant` distinguishes 16 vs 25.

---

## 27. MaterialReportBlock

Fields:

```text
date
title
brand
input_data JSON
output_data JSON
delivery_wage
note
```

This is the saved form/block identity.

Saving JSON does not imply materials/output have been applied.

The applied state lives in separate ledgers/models.

---

## 28. MaterialReportConsumption

Fields:

```text
block
kind
material_key
variant
quantity
```

Unique constraint:

```text
(block, kind, material_key, variant)
```

This is the cumulative raw-material consumption ledger per block/material/variant.

It enables idempotent delta synchronization.

---

## 29. MaterialReportOutputApplied

Fields:

```text
block
model_key
size_key
quantity
```

Unique constraint:

```text
(block, model_key, size_key)
```

This is the cumulative finished-delivery applied ledger.

Current V35/V22 sync compares current entered output target to this quantity and applies only the difference in either direction.

---

## 30. Wage piece ledgers

Current material-report two-way wage synchronization stores cumulative piece basis in `AppSetting` keys rather than a dedicated relational model.

Prefixes:

```text
novani_output_wage_pieces_v35_
darma_output_wage_pieces_v35_
```

Legacy Novani repair marker prefix:

```text
novani_wage_repair_v34_block_
```

These are safety/idempotency state. Do not purge as "old settings" without migrating their meaning.

---

# PART F — TAKVIN COST

## 31. TakvinCostRule

Fields:

```text
size
effective_from
unit_cost
created_at
```

Unique constraint:

```text
(size, effective_from)
```

This supports date-effective Takvin accounting cost for sale snapshots.

The currently latest rule is not automatically the cost for every historical sale; choose rule effective on SaleDay date and freeze it in SaleSnapshot.

---

# PART G — OTHER LEGACY/SECONDARY MODELS

## 32. StockTransfer

Explicit manual transfer object with:

```text
brand/size/color/qty
from_location/to_location
applied
```

Use existing sync/operations service for apply/reverse; do not treat row creation as applied transfer by itself.

---

## 33. Older production models

`models_final.py` also contains models like:

- FabricRoll;
- ElasticBalance / ElasticMovement;
- ProductionBatch / ProductionReceipt;
- SupplierAccount / SupplierEntry;
- ReturnRecord;
- SideAsset;
- Expense / BankTransfer / older payment models.

Some belong to older/parallel architecture and are not necessarily primary active workflows.

Rule for new AI:

**Presence of a model does not mean it is the active source of truth. Check `core/urls.py` and current active view/service before using it.**

For example, active standalone return V37 uses InventoryAdjustment, not legacy `ReturnRecord`.

---

# PART H — DEBUGGING SOURCE-OF-TRUTH TABLE

## 34. If UI shows wrong sold color

Inspect in this order:

1. original Digikala title / manual product selection;
2. SaleLine product_size;
3. SaleAllocation;
4. current ProductComposition only as fallback;
5. title resolver/importer if identity was wrong.

---

## 35. If stock quantity is wrong

Inspect:

1. StockBalance current cell;
2. InventoryMovement references;
3. InventoryAdjustment applied rows;
4. SaleAllocation / sale sync history;
5. MaterialReportOutputApplied / production movements;
6. physical baseline/reconcile history.

---

## 36. If raw material display is wrong

Inspect:

1. RawMaterialStock aggregate by kind/material_key/variant/location;
2. material purchase ledger;
3. MaterialReportConsumption;
4. transfer/return movement history;
5. do not trust latest row note as sole provenance.

---

## 37. If profit is wrong

Inspect:

1. SaleLine quantity/sale_price;
2. SaleSnapshot unit_cost/pack_qty/digikala_fee_unit;
3. `sale_line_metrics`;
4. exact `digikala_fee_for_unit` settings if no frozen fee;
5. do not use current ProductSize cost to rewrite old snapshot.

---

## 38. If capital is wrong

Break into:

1. active ExcelManualRow accounts/persons;
2. finished inventory valuation;
3. raw material total;
4. Digikala receivable base + ledger;
5. asset rows;
6. Takvin debt.

Then trace only the incorrect component.
