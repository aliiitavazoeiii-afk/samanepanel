# 02 — ACCOUNTING FORMULAS AND LEDGER SEMANTICS

This file is the accounting reference for DARMA General. Do not change any formula here unless the user explicitly changes the business rule.

Last synchronized: 2026-08-29 after confirmed V37 live deployment.

---

## 1. Capital equation

The comprehensive-report capital equation is:

```text
capital = accounts/persons
        + finished inventory
        + raw materials
        + Digikala receivable
        + assets
        - Takvin debt
```

In current `core/report_v9.py`, the equivalent implementation is:

```python
accounts_total = sum(accounts rows) + sum(person rows)
assets_total = sum(asset rows)
finished_inventory_total = finished_inventory_value_v17()
raw = _raw_material_context()
inventory_total = finished_inventory_total + raw["materials_total"]
capital_total = accounts_total + inventory_total + digikala_receivable - takvin_debt + assets_total
```

Important consequences:

- cash is part of `accounts/persons` through rows such as Mellat;
- supplier prepayments can be represented as owned account assets;
- finished inventory and raw materials are capital assets;
- Digikala receivable is an asset;
- Takvin debt is a liability and subtracts from capital;
- moving value between owned assets should normally preserve capital.

---

## 2. Sale accounting equation

For each normal sale line:

```text
gross = quantity_of_packs * sale_price_per_pack
Digikala fee = quantity_of_packs * frozen_or_current_fee_per_pack
shorts = quantity_of_packs * pack_qty
COGS = shorts * frozen_or_current_accounting_unit_cost
profit = gross - Digikala fee - COGS
```

Capital movement of a correctly applied sale:

```text
Finished inventory   -= COGS
Digikala receivable  += gross - Digikala fee
----------------------------------------------
Capital delta         = gross - fee - COGS = profit
```

This is why sale profit and capital movement should reconcile when no unrelated inventory/accounting adjustment occurs.

---

## 3. Digikala fee engine

The canonical fee function is `core.finance.digikala_fee_for_unit(sale_price)`.

Do not duplicate/reimplement it in another feature if the exact fee behavior is needed. Call the existing function.

Current configurable/default components:

```text
commission_rate          = setting digikala_commission_percent (default 24%)
processing_rate          = setting digikala_processing_percent (default 7%)
processing_floor         = setting digikala_processing_floor (default 36,000 toman)
VAT rate                 = setting digikala_vat_percent (default 10%)
floor_taxable_part       = setting digikala_floor_taxable_part (default 18,000 toman)
```

Computation:

```text
commission = sale_price * commission_rate
raw_processing = sale_price * processing_rate

if raw_processing < processing_floor:
    processing = processing_floor
    taxable_processing = floor_taxable_part
else:
    processing = raw_processing
    taxable_processing = processing / 2

VAT = (commission + taxable_processing) * VAT_rate
fee = round_toman(commission + processing + VAT)
```

This is the exact engine used by current sales reporting and by V37 target-price calculator.

Do not replace it with a simple `31% + VAT` approximation.

---

## 4. SaleSnapshot semantics

Historical SaleSnapshot values must remain frozen.

`sale_line_metrics()` prefers snapshot values when available:

- snapshot pack quantity;
- snapshot Digikala fee unit;
- snapshot accounting unit cost.

Only if a snapshot field is absent does it fall back to current product/configuration values.

Reason:

- a later fee change must not rewrite old profit;
- a later Takvin cost rule must not rewrite old COGS;
- a later product composition/pack change must not rewrite the historical accounting basis of a completed sale.

Never run a bulk rewrite of historical SaleSnapshot solely because current settings changed.

---

## 5. Digikala receivable ledger

Canonical helpers live in `core/finance_excel_v9.py`.

Conceptually:

```text
Digikala total receivable = base receivable + sale/receipt ledger total
```

Each sale line should have a receivable AccountEntry keyed by a stable reference such as:

```text
sale:<sale_line_id>:digikala
```

Expected amount is:

```text
gross - Digikala fee
```

The daily import flow can delete/rebuild a sale's receivable entry during replacement, but the outer atomic flow must finish with every active sale line synchronized.

### Important report edit nuance

The comprehensive report's editable Digikala field is a **desired current total**, not a raw base opening number.

When user sets desired current receivable:

```text
base_value_to_store = desired_current_total - current_ledger_total
```

Then later:

```text
current_receivable = stored_base + current_ledger
```

This distinction previously caused confusion when a historical base was entered as if the field were a base-only field. Do not alter this semantic without explicit user instruction.

---

## 6. Digikala receipt accounting

A Digikala receipt is a transfer between owned assets:

```text
Digikala receivable -= X
Mellat               += X
Capital               unchanged
```

Receipt creation and deletion must be atomic and two-sided.

Active routes use `business_tools_v21` for receipt add/edit/delete.

Deletion must:

- reduce Mellat by the receipt amount;
- delete/reverse the exact Digikala AccountEntry ledger;
- restore receivable by the same amount;
- abort if the expected ledger cannot be found.

Never delete only the settlement row.

---

## 7. Finished inventory valuation

Canonical finished-goods valuation helper:

`core.inventory_valuation_v17.finished_inventory_value_v17()`

High-level brand semantics:

- Darma: real inventory, included.
- Takvin: real inventory, included.
- Novani: real inventory, included.
- Anbaresh: sales-only physical proxy for Darma, excluded as independent asset.

Darma normally uses the system's current accounting unit/value basis per stock/cost model. Historical baseline discussions often use 61,000 per short, but a new AI must inspect the current valuation code before assuming every cell is permanently 61,000.

Takvin inventory valuation is distinct from sale-time dated Takvin COGS rules; inspect current valuation helper before changing either.

Novani is a real inventory asset and therefore increases capital when stock is added.

---

## 8. Standalone return accounting V37

Standalone returns create positive HOME stock adjustments only.

No direct financial/account entry is created.

Therefore:

```text
Finished inventory value += value of returned shorts
Capital                  += same value
```

The increase is not a sale profit, not Digikala revenue and not cash.

V37 explicitly verifies:

- HOME quantity increases;
- finished inventory value increases;
- Digikala receivable is unchanged;
- AccountEntry count is unchanged;
- SaleLine count is unchanged.

---

## 9. Internal inventory transfer accounting

HOME <-> KHORSHID is an internal location move.

Correct invariant:

```text
HOME - X
KHORSHID + X
Total quantity unchanged
Total finished value unchanged
Capital unchanged
```

Any transfer feature that changes total stock/value is a bug unless explicitly performing an adjustment/reconcile instead of a transfer.

---

## 10. Raw-material purchase accounting

There are two materially different cases in V22:

### 10.1 Goods received

A material purchase with physical purchase details can have:

- invoice/goods value calculated from quantities * unit prices;
- actual paid cash entered separately.

For goods received:

```text
Mellat -= actual_paid
Raw material inventory += invoice/goods value
```

The resulting capital delta is:

```text
capital_delta = goods_value - actual_paid
```

This can legitimately be non-zero if actual paid differs from invoice value.

Current business rule intentionally permits this. Do **not** force actual paid to equal invoice value.

Example from payment #6 during the 2026-08-29 elastic debugging:

```text
Elastic 16: 5 kg * 2,600,000 = 13,000,000
Elastic 25: 5 kg * 2,600,000 = 13,000,000
Goods value = 26,000,000
Actual paid = 25,584,000
Capital delta = +416,000
```

This difference was intentional under V22 semantics.

### 10.2 Material prepayment, no goods received

When paying a fabric/elastic supplier without physical purchase details:

```text
Mellat -= X
Supplier prepayment account asset += X
Capital unchanged
```

V22 stores an explicit settlement/prepayment MoneyMovement ledger to make reversal deterministic.

---

## 11. BusinessPayment V22 full apply/reverse semantics

Active payment add/edit/delete routes use `core.business_tools_v22`.

### Material purchase with goods

Apply:

1. Mellat decreases by `payment.amount` = actual paid.
2. Raw material stock is added from purchase data.
3. Purchase ledger is created.

Reverse/delete:

1. Verify purchase data/ledger.
2. Reverse the exact purchase stock.
3. Delete purchase ledger.
4. Restore Mellat by actual paid.
5. Delete payment row.

If purchased stock is no longer available in the expected form/location, reverse may deliberately fail rather than corrupt inventory.

### Material prepayment

Apply:

1. Mellat decreases.
2. Supplier account row increases.
3. settlement/prepayment ledger created.

Reverse:

1. Find current or legacy prepayment ledger, never both.
2. Reduce exact supplier account.
3. delete ledger.
4. restore Mellat.

### Non-material payments

Delegate to V21 payment effect helpers. Typical examples:

- tailor payment changes Mellat and tailor account in opposite directions;
- Takvin payment reduces Mellat and Takvin debt according to active payment semantics.

Never raw-delete BusinessPayment without using the guarded reverse path.

---

## 12. Elastic purchase model

Elastic purchase stores 16 and 25 variants separately:

```text
q16 / p16
q25 / p25
```

They must never be summed into each variant.

Raw material aggregate stock is keyed by material identity + variant. Adding a purchase to an existing aggregate row increases that row's quantity.

A previous diagnostic demonstrated why notes can be misleading: an aggregate row can contain prior stock plus a new purchase while its note is overwritten to mention the latest payment. Therefore never infer provenance solely from the row note.

Use purchase ledger and movement history for forensic accounting.

---

## 13. Material-report raw consumption accounting

`Apply Materials` only synchronizes raw-material consumption.

It must not create finished stock.

Consumption is intended to be delta/idempotent: if target consumption changes from A to B, only B-A should be applied, and decreasing target should restore material when supported by the active sync/reverse logic.

Raw material internal moves and consumption must use explicit stock/consumption ledgers, not notes as the sole source of truth.

---

## 14. Material-report production/output accounting

`Apply Output` / current V35/V22 sync changes cumulative delivered finished goods and sewing wage.

### Darma output

Destination: KHORSHID.

The existing costed production path must be used for both positive and negative output deltas so finished-goods accounting value is added/reversed consistently.

### Novani output

Destination: Novani single HOME bucket.

Must never change Darma.

### Wage

Let:

```text
rate = 110,000 toman / 12 pieces
wage_for_pieces(n) = project helper's rounded wage for n cumulative delivered pieces
```

When cumulative delivered changes from `old` to `new`:

```text
wage_change = wage_for_pieces(new) - wage_for_pieces(old)
```

Then:

- positive wage_change -> tailor balance decreases by that wage;
- negative wage_change -> tailor balance increases/returns by abs(wage_change).

Wage ledger stores cumulative piece basis to prevent double application.

Cut quantity is not wage basis.

---

## 15. Physical stock reconciliation accounting

A physical baseline/reconcile is not a normal transfer/sale. It can legitimately change capital because it corrects the owned inventory quantity/value to physical truth.

For a physical reconcile:

1. compute exact per-cell before/target/delta;
2. compute total value/capital effect before apply;
3. back up DB;
4. apply explicit adjustment movements;
5. verify exact matrix and totals;
6. never silently offset the capital effect using an unrelated account merely to preserve an old number.

Examples:

- V18/V32 physical Darma target after 3 Shahrivar = 13,475 shorts.
- Historical audit before physical correction had 13,467, so correction was +8 * 61,000 = +488,000 at that valuation.

---

## 16. Why capital may not equal opening capital + sales profit

Opening capital + cumulative sale profit is valid only if there were no other capital-changing events.

Other legitimate capital deltas can include:

- physical inventory adjustments;
- returned goods added to owned stock;
- purchase invoice value different from actual cash paid;
- manual account/asset adjustments;
- cost-basis changes to currently valued inventory if the valuation model uses current costs;
- write-offs or corrections.

Therefore audits must build a bridge by component instead of force-setting total capital.

---

## 17. Capital audit discipline

When a reported total is wrong:

Do not begin by editing `capital_total`.

Break it down into:

```text
accounts/persons
finished inventory
raw materials
Digikala receivable
assets
Takvin debt
```

Then isolate the incorrect component and trace its ledger/stock basis.

Read-only audits are preferred before any correction.

---

## 18. Confirmed V37 deployment invariant snapshot

At the successful V37 production deployment, final business values were:

```text
CAPITAL=5,441,972,371
FINISHED=1,115,731,500
RAW=1,994,448,050
DIGI=812,517,154
DARMA=12,072
TAKVIN=1,195
NOVANI=3,630
SALES=202
ACCOUNT_ENTRIES=206
```

These are a **deployment checkpoint**, not a forever target. Subsequent legitimate business operations will change them.

Do not reset production back to these numbers just because they are documented here.
