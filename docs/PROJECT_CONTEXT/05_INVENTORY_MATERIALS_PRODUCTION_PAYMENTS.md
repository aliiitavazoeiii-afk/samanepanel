# 05 — INVENTORY, MATERIALS, PRODUCTION AND PAYMENTS

This file explains the operational state transitions for finished inventory, raw materials, material reports, sewing wage and payments.

Last synchronized: 2026-08-29 after confirmed V37 live deployment.

---

# PART A — FINISHED INVENTORY

## 1. StockBalance and StockLocation

Finished goods are represented by brand/color/size/location stock balances.

The two important physical location keys are conceptually:

- HOME
- KHORSHID

Brand rules differ:

- Darma uses HOME + KHORSHID.
- Novani uses one logical inventory bucket represented internally by HOME.
- Takvin follows its current inventory implementation; inspect `inventory_v20.py` before assuming Darma-only transfer behavior applies.
- Anbaresh must not own independent inventory value.

---

## 2. InventoryMovement and InventoryAdjustment

There are two important audit concepts:

### InventoryAdjustment

Explicit adjustment object used by features such as standalone return and manual stock corrections. Application must go through the existing synchronization service rather than directly mutating StockBalance.

### InventoryMovement

Audit ledger of inventory changes, including production/adjust/reconcile references.

Do not use note strings as the only authoritative provenance if a structured ledger/model exists.

---

## 3. Darma HOME/KHORSHID transfer

Darma transfer is internal asset movement.

Correct invariant:

```text
HOME delta + KHORSHID delta = 0
brand total unchanged
finished value unchanged
capital unchanged
```

Current sale inventory logic may transfer KHORSHID -> HOME automatically before deducting a sale.

A physical reconcile is different from transfer: it can intentionally change total stock/value.

---

## 4. Exact physical baseline versus historical sales

When the user declares a physical end-of-day count authoritative, that physical matrix wins for future inventory state even if it reveals historical accounting discrepancies.

Do not reapply sales that occurred before/end-of-day baseline.

A physical baseline command should:

- be dry-run by default;
- show exact cell changes;
- use transaction;
- create explicit adjustment/movement references;
- verify totals/cells after apply;
- report capital/value delta;
- not compensate with a fake finance row.

---

# PART B — RAW MATERIALS

## 5. RawMaterialStock model concept

Raw material inventory includes at least:

- fabric;
- elastic.

Logical locations include:

- warehouse;
- tailor;
- depot for fabric where supported.

Raw materials are owned assets and contribute to capital.

---

## 6. Aggregate-row semantics

Raw-material rows can be aggregates keyed by material identity/variant/location.

Important consequence from the elastic investigation:

A purchase does not necessarily create a new independent display row. It can add to an existing aggregate row. The row note may be updated to mention the latest purchase, even though part of the quantity came from an earlier state.

Therefore:

- row note != exact provenance;
- use purchase ledger / movement history for forensic attribution.

---

## 7. Elastic variant semantics

Elastic has distinct variants:

- 16
- 25

Purchase payload stores them separately:

```text
q16 / p16
q25 / p25
```

Example:

```text
5 kg elastic16 + 5 kg elastic25
```

must add exactly:

```text
variant16 +5
variant25 +5
```

not `+10` to each.

`material_purchase_v13.build_purchase_from_post` parses each quantity independently and `material_purchase_v14.apply_purchase_stock` applies each independently.

---

## 8. Elastic payment #6 forensic case

A real diagnostic on 2026-08-29 showed:

```text
payment_id=6
actual paid=25,584,000
material key=gray
q16=5
q25=5
p16=2,600,000
p25=2,600,000
```

Goods value:

```text
5 * 2,600,000 + 5 * 2,600,000 = 26,000,000
```

Current aggregate rows temporarily showed:

```text
variant16 qty=10
variant25 qty=10
```

with no duplicate BusinessPayment. This demonstrated that extra aggregate stock was not caused by parser summing variants or a duplicate payment row.

A V28 diagnostic/repair flow was created. The core lesson:

- diagnose ledger versus aggregate stock before deleting/reversing;
- payment reverse can correctly refuse if purchased material is no longer present in the expected quantity/location;
- never force-delete a payment row while leaving its physical/cash effects behind unless performing an explicitly designed rebase operation.

---

# PART C — MATERIAL REPORT / PRODUCTION

## 9. Brand-aware MaterialReportBlock

Material reports are currently for:

- Darma
- Novani

Each block stores a brand.

Once production has been applied, changing historical brand should be blocked/guarded because it would silently move production between inventory brands.

---

## 10. Three independent actions

This separation is critical and came from earlier bugs.

### 10.1 Save

Stores form data only.

Must not:

- consume raw material;
- add finished stock;
- change sewing wage.

### 10.2 Apply Materials

Synchronizes raw-material consumption only.

Must not add/modify finished shorts.

### 10.3 Apply Output / current sync

Synchronizes cumulative delivered finished quantities and sewing wage.

Must not re-consume raw material.

Do not merge these buttons/operations into a single implicit save.

---

## 11. Current material-report active route implementation

Page/save/apply materials/apply output:

`core/material_report_v22.py`

Base helpers + unapply/delete:

`core/material_report_v20.py`

Current template:

`templates/core/material_report_v35.html`

Current output editing is two-way for Darma and Novani.

---

## 12. Novani size isolation V33+

Novani output size set:

```text
S, M, L, XL, XXL, 3XL
```

Darma remains:

```text
M, L, XL, XXL, 3XL, 4XL
```

Adding `S` for Novani must not create/enable S for Darma or Takvin.

Backend guards must enforce this, not merely hide options in UI.

---

## 13. Novani output destination

Novani output adds only to Novani's own inventory bucket.

It must not:

- add Darma stock;
- change Takvin;
- create a Darma KHORSHID row;
- change raw materials when only Apply Output is pressed.

Novani is a real inventory asset, so output increases finished inventory/capital by the valuation of produced goods.

---

## 14. Darma output destination and costing

Darma material-report output goes to KHORSHID.

The existing costed production helper must be used so stock quantity and accounting value remain synchronized.

When delivered quantity is reduced/cleared later, the reduction must reverse the same production value path, not simply decrement quantity with an unrelated fixed cost.

---

## 15. Editable cumulative delivery V35/V22

User can correct an already saved/applied delivered quantity.

Current algorithm concept:

For each model/color x size:

```text
target = current entered cumulative delivered quantity
done = MaterialReportOutputApplied.quantity
delta = target - done
```

Then:

- delta > 0: add only the new difference;
- delta = 0: no-op;
- delta < 0: remove exactly the reduction if enough destination stock exists.

Every affected row is prevalidated/locked before stock/wage writes. If a required reduction exceeds available stock, entire atomic operation stops.

---

## 16. Applied-table idempotency

`MaterialReportOutputApplied` is the cumulative output ledger per block/model/size.

Do not determine already-applied output by comparing notes or by summing all production movements without considering current ledger semantics.

The applied table is designed to make repeated Apply Output idempotent.

---

## 17. Sewing wage

Confirmed rate:

```text
110,000 toman per 12 delivered pieces
```

Wage basis is actual delivered output, not cut.

Current V22/V35 logic tracks cumulative delivered piece basis in `AppSetting` wage ledger keys:

- Novani prefix `novani_output_wage_pieces_v35_`
- Darma prefix `darma_output_wage_pieces_v35_`

For a block:

```text
applied_total_before = cumulative already applied pieces
target_total = cumulative entered delivered pieces
wage_before = wage_for_pieces(applied_total_before)
wage_after = wage_for_pieces(target_total)
wage_change = wage_after - wage_before
```

Then tailor balance adjustment is `-wage_change`:

- more delivered -> tailor balance decreases;
- delivery correction downward -> wage is returned to tailor balance.

The block's saved `delivery_wage` is updated to cumulative wage after sync.

---

## 18. V33/V34 Novani wage bug history

V33 initially isolated Novani Apply Output too aggressively: it stopped touching Darma correctly, but also stopped applying the required sewing wage.

A real Novani block had delivered totals:

```text
مشکی 710
سفید 660
سرمه‌ای 750
صورتی 700
کرم 810
--------------
TOTAL 3,630 pieces
```

At 110,000 per dozen:

```text
3,630 / 12 = 302.5 dozen
302.5 * 110,000 = 33,275,000 toman
```

A repair V34 marker was introduced for pre-two-way-wage Novani blocks. Current `_lock_or_initialize_wage_ledger` refuses to seed a legacy positive Novani block without the repair marker, preventing accidental double/missing wage accounting.

Do not remove this migration/legacy guard without understanding historical block state.

---

## 19. Cut versus delivered UI

Current requested material-report table behavior:

- no delivery-date column;
- show cut column;
- show shortage/surplus versus cut;
- shortage in red;
- surplus in green;
- show grand total delivered below section.

Cut value comes from input data source mapping.

Important mapping fix:

```text
reverse_black -> reverse_black
reverse_white -> reverse_white
reverse_navy -> reverse_navy
```

They do not inherit black/white/navy cut values.

If there is no dedicated reverse-model cut row, comparator is zero.

---

# PART D — PAYMENTS

## 20. Active payment UI/routes

Active payment add/edit/delete are V22:

- `core/business_tools_v22.py`
- `templates/core/payments_v22.html`

Digikala receipts and Mellat-set are routed to V21.

Do not mix old v14 implementation into active payment writes.

---

## 21. Payment types

Known payees include concepts such as:

- pedram;
- tailor;
- fabric;
- elastic;
- takvin.

Material payees are fabric/elastic.

V22 distinguishes:

1. material purchase with goods details;
2. material prepayment without goods details;
3. normal non-material payment.

---

## 22. Material purchase: actual paid versus invoice value

Purchase form can contain physical goods details plus a separate actual paid amount.

If actual paid field is > 0, it becomes payment.amount.

If actual paid is omitted/zero, V22 defaults actual paid to invoice value.

This is intentional.

Do not force equality after save.

---

## 23. Material purchase signature

V22 uses a physical purchase signature that intentionally excludes:

- date;
- note;
- actual cash paid.

It includes physical/material identity and quantities/prices.

For elastic signature includes both q16/p16 and q25/p25 separately.

This distinction allows safe metadata/actual-paid edits without necessarily reapplying stock if physical purchase details did not change.

---

## 24. Payment update semantics

V22 is designed so edits can be classified:

- metadata/actual-paid-only change -> finance-only reverse/apply where safe, preserve physical stock;
- physical purchase detail change -> full reverse old physical purchase and apply new physical purchase.

Before editing `payment_update`, inspect the current complete implementation; do not simplify this into delete-and-recreate without preserving stock provenance.

---

## 25. Payment deletion safety

Payment delete uses `_reverse_full(payment)` inside a database transaction before deleting the row.

Therefore delete may intentionally fail if:

- purchase ledger is missing/corrupt;
- required stock is no longer present to reverse;
- both current and legacy prepayment ledgers exist;
- expected supplier account cannot be found;
- other invariant mismatch occurs.

This is preferable to one-sided deletion.

Do not bypass the guard with raw SQL/ORM delete merely because UI delete fails.

---

## 26. Why a fabric payment could not be reset

During a Shahrivar workflow reset, reversing a fabric purchase failed with an error equivalent to:

```text
Cannot delete fabric purchase; 36.89 kg from that purchase is no longer in warehouse. If transferred to tailor, return it to warehouse first.
```

Because the reset was atomic, all prior reversals in that reset were rolled back and no sales/payment data changed.

Lesson:

- raw material purchase reversal must respect current physical material location/consumption;
- a reset that needs to clear history may require rebase semantics rather than pretending consumed material is still untouched.

---

## 27. V30B rebase concept

A later reset strategy for rebuilding Shahrivar sales intentionally separated historical UI rows from already-correct material/account baseline:

- sales after date: reverse/remove;
- Digikala receipts after date: reverse/remove;
- payment rows: remove/rebase while preserving current effects when user explicitly wants current material/cash state retained as baseline.

This was a special forensic/reset workflow, not normal payment deletion semantics.

Do not generalize it into standard payment behavior.

---

# PART E — WHAT TO READ BEFORE EDITING

## 28. Inventory change

Read:

- `core/models.py`
- `core/inventory_v20.py`
- `core/inventory_operations_v15.py`
- `core/final_services.py`
- `core/inventory_valuation_v17.py`
- relevant movement/adjustment management commands

## 29. Material/production change

Read:

- `core/material_report_v22.py`
- `core/material_report_v20.py`
- `core/material_flow.py`
- `core/material_cost_v13.py`
- `core/models.py` MaterialReport* models
- `templates/core/material_report_v35.html`

## 30. Payment change

Read:

- `core/business_tools_v22.py`
- `core/business_tools_v21.py`
- `core/material_purchase_v13.py`
- `core/material_purchase_v14.py`
- `core/material_flow.py`
- `templates/core/payments_v22.html`

Never modify a displayed total without tracing which ledger/stock object is actually authoritative.
