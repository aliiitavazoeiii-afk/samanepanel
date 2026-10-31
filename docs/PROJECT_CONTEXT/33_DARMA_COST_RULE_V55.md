# V55 — CENTRALIZED DATE-EFFECTIVE DARMA COST + SHAHRIVAR REPAIR

## User rule

Darma has one accounting cost per short. It is not color-dependent and not size-dependent.

The user needs one authoritative place to enter a new cost with an effective date, for example:

```text
through 1405/06/14: 61,000 toman per short
from    1405/06/15: 67,000 toman per short
```

From the effective date forward, every Darma-backed accounting path must use that rate. Historical completed sales before the date remain frozen by their SaleSnapshot.

## Root cause of the 18,549 return discrepancy

Before V55, two separate Darma accounting bases existed:

- generic/default Darma cost around 61,000;
- `InventoryModelCost` values per Darma color + size.

`core/inventory_valuation_v17.py` valued current Darma stock from `InventoryModelCost`, while `core/cost_accounting_v14.py` also averaged the actual allocated Darma colors into new SaleSnapshots. Therefore a 3-pack return of pack5 / M (15 shorts) could add 933,549 to finished inventory instead of the intended:

```text
15 * 61,000 = 915,000
```

The difference was 18,549 toman. This was not a fee; it was the difference between the five M color-specific model costs and the single real Darma cost.

## V55 source of truth

New module:

`core/darma_cost_v55.py`

Date-effective rules are stored as controlled `AppSetting` rows with keys:

`darma_cost_rule_YYYY-MM-DD`

This avoids a schema migration while still giving a date-effective rule history. The old `darma_accounting_unit_cost` remains only as a safe fallback for a database that has no dated rule. The dedicated settings UI hides that legacy key so there is only one user-facing Darma cost control.

Confirmed baseline:

```text
1400/01/01 -> 61,000 toman per short
```

`darma_cost_for(on_date)` selects the newest rule with `effective_from <= on_date`.

The baseline rule itself is protected from deletion. To change Darma cost, add a newer effective-date rule rather than removing the historical base.

## Active accounting paths changed

### SaleSnapshot / COGS

`core/cost_accounting_v14.py`

- Darma -> `darma_cost_for(line.day.date)`
- Anbaresh -> same Darma rule because Anbaresh is Darma-backed
- Takvin remains on its own `takvin_cost_for()` system
- no Darma color/size `InventoryModelCost` averaging remains in the snapshot path

### Missing-Snapshot fallback

`core/finance.py`

If a Darma or Anbaresh SaleLine has no usable SaleSnapshot, `sale_line_metrics()` falls back to `darma_cost_for(line.day.date)` instead of `ProductSize.unit_cost`.

This prevents an incomplete/legacy row from reintroducing a second Darma cost source.

### Current finished inventory / capital

`core/inventory_valuation_v17.py`

All current Darma `StockBalance` quantity, across HOME and KHORSHID, is valued at one current effective Darma rate.

Therefore a new rule that becomes effective today intentionally revalues the entire currently owned Darma inventory and changes `finished inventory` and `capital` by:

```text
current Darma total qty * (new rate - previous rate)
```

This is an inventory revaluation, not sales profit and not cash movement.

`InventoryModelCost` remains available for other brands/internal data but is no longer the accounting value source for Darma.

### Legacy helper convergence

`core/final_services.py` still had an older `inventory_unit_cost()` / `finished_inventory_value()` path used by legacy dashboard/view helpers. V55 now routes Darma `inventory_unit_cost()` to `darma_cost_for()` and delegates `finished_inventory_value()` to `finished_inventory_value_v17()`.

This prevents a later 67,000 effective rule from showing 67,000 in the modern reports but stale 61,000 in an older helper-backed page. The V55 deploy script verifies both helpers resolve to the same central source before and after live recreate.

### Standalone returns and physical corrections

Standalone returns still only create positive HOME inventory adjustments. They create no sale, Digikala receivable or cash entry.

Because finished Darma inventory is now valued from the central rate, a return of N Darma shorts increases current inventory/capital by exactly:

```text
N * current effective Darma cost
```

Thus 15 returned shorts at 61,000 increase finished inventory/capital by exactly 915,000.

### Dia Gallery

`core/dia_gallery_v45.py`

A new Dia sale freezes `darma_cost_for(line.day.date)` into `DiaGallerySale.unit_cost` when its unit cost is first established. Existing nonzero historical Dia unit costs stay frozen unless explicitly repriced by a user-entered effective-date rule or the targeted repair.

### s3

Variable-color `s3` is still a Darma SaleLine, so its SaleSnapshot now freezes the same date-effective Darma cost. Its selected colors affect physical quantity allocation only, not accounting cost per short.

### Darma product setup / group pricing

The product edit form no longer exposes a Darma accounting unit-cost field as an independent source. Darma accounting cost is managed only from Settings -> Rules and base prices.

`core/darma_pricing.py` also uses the central current Darma cost when it needs to maintain legacy `ProductSize.unit_cost` compatibility data, so even non-authoritative compatibility values do not retain a hardcoded 61,000 after a later rule.

## Settings UI

Existing route/page:

Settings -> Rules and base prices (`settings_rules_v17`)

New Darma card contains:

- effective Jalali date
- one cost per Darma short
- current effective rate
- rule history
- guarded delete action

When a new rule is saved, existing Darma-backed SaleSnapshots and Dia rows on/after its effective date are repriced to the rule effective on each row's date; pre-effective historical snapshots remain unchanged. Deleting a non-baseline rule similarly recalculates affected later rows from the remaining dated rules.

Deleting a currently effective non-baseline rule may revalue current Darma inventory by falling back to the previous effective rule, so the UI confirmation states this.

## Targeted repair — only 12 and 14 Shahrivar 1405

New command:

`repair_darma_cost_shahrivar_v55`

It is dry-run by default. `--apply` changes only:

- `SaleSnapshot.unit_cost` for active Darma/Anbaresh-backed SaleLines on 1405/06/12 and 1405/06/14;
- `DiaGallerySale.unit_cost` for active Dia rows on those two dates.

It does NOT change:

- sale quantity;
- sale price;
- Digikala fee;
- Digikala receivable;
- Dia receivable;
- StockBalance quantity;
- AccountEntry;
- payments;
- transfers;
- inventory adjustments;
- any other date.

If an affected normal SaleLine unexpectedly has no SaleSnapshot, the repair creates the snapshot using the line's existing pack quantity and the canonical existing Digikala fee, then freezes only the correct Darma cost.

## Regression

New command:

`check_darma_cost_rule_v55`

Transactional rollback checks verify:

- date-effective rule resolution;
- Darma snapshots use the sale-date central cost;
- Anbaresh snapshots use the same Darma cost;
- missing-Snapshot Darma report fallback uses the same central cost;
- a newly saved effective-date rule reprices existing rows on/after that date only;
- pre-effective historical snapshots stay frozen;
- Dia freezes/reprices by effective date;
- current Darma inventory revalues by exact total-qty * rate-delta;
- a Darma return/adjustment changes finished value by exact returned qty * central current rate;
- all regression test data rolls back.

The deployment script separately verifies legacy `final_services` helpers also resolve to the same central source.

Expected marker:

`SUCCESS: DARMA COST RULE V55 CHECK PASSED`

## Deployment / revaluation safety

Rollback branch before V55:

`before-darma-cost-rule-v55-20260905`

Base commit:

`f97f157f7206bcec0340789d822ca17e05888980`

Deploy script:

`server_darma_cost_rule_v55.sh`

The script:

1. takes pg_dump backup;
2. captures pre-V55 business state;
3. computes old Darma color/size model value and the expected 61,000 central value;
4. runs V37/V48/V50/V51/V52/V53/V54/V55 regressions plus legacy-helper centralization check;
5. seeds the 61,000 baseline;
6. dry-runs and then applies only the 12+14 Shahrivar repair;
7. verifies repair did not move physical/financial ledgers;
8. recreates web;
9. verifies final FINISHED and CAPITAL changed by exactly the expected Darma revaluation delta;
10. requires all other quantities/receivables/ledger counts to stay unchanged.

Expected final markers:

`SUCCESS: DARMA COST RULE V55 DEPLOYED`

`SUCCESS: DARMA COST SHAHRIVAR V55 REPAIR APPLIED`

Production status must not be called confirmed until the user posts those actual VPS success markers.
