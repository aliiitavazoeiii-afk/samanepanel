# V59 — NOVANI DATED COST RULE + TAKVIN PURCHASE STOCK FIX

Date prepared: 2026-09-06

## User-requested business behavior

### Darma

The V55 date-effective Darma cost UI remains authoritative. Registering a new rate with a future Jalali effective date must not affect today's inventory or today's sale COGS. When that date arrives:

- current Darma finished inventory is valued at the new per-short rate;
- new/existing sale-date COGS from that effective date forward uses the new rate;
- older sale dates remain frozen/unchanged except explicit scoped repairs.

The Rules page uses the existing `jalali-date` picker, so the user can enter tomorrow's date and 65,000 without changing today.

### Novani

V59 adds the same single-source model for Novani:

- implicit locked baseline: 61,000 toman from 1400/01/01;
- user rules: one `effective_from` date + one per-short cost;
- `novani_cost_for(date)` resolves the latest rule effective on/before that date;
- current Novani inventory uses `novani_cost_for(today)`;
- Novani SaleSnapshot COGS uses `novani_cost_for(sale_day)`;
- missing-snapshot finance fallback uses the same dated helper;
- current inventory page value uses the same central rate;
- legacy `InventoryModelCost` / `ProductSize.unit_cost` values are no longer accounting sources for Novani.

Material-report Novani output still creates physical HOME stock through the existing output ledger. Any legacy 61,000 `InventoryModelCost` row it may maintain is non-authoritative under V59; current capital valuation is derived from central Novani cost × current Novani quantity.

## Takvin purchase bug found

Active purchase page: `core/takvin_v5.py`.

Before V59, the Excel-style purchase save path did this:

1. create `TakvinPurchase` rows with `applied=True`;
2. increase `ExcelManualSetting(key="takvin_debt")` by invoice/net value;
3. **did not add the purchased quantity to `StockBalance`;**
4. **did not create `InventoryMovement.PURCHASE`.**

Because capital is:

`accounts + finished + raw + Digi + assets - Takvin debt`

this caused capital to fall by the new debt while the corresponding Takvin inventory asset was missing. The user observed exactly this on today's purchase: capital fell from 5,632,140,177 to 5,566,260,177 (65,880,000 decrease) and the purchase did not appear in Takvin stock.

## V59 Takvin purchase semantics

The active Takvin page continues to use `ExcelManualSetting.takvin_debt` as the liability source. V59 intentionally does **not** call legacy `final_services.sync_takvin_purchase`, because that service also creates `Account.TAKVIN` entries and would introduce a second finance representation.

Instead V59 adds a physical-only purchase stock path inside `takvin_v5.py`:

- purchase save creates rows with `applied=False`;
- each row is applied to Takvin HOME stock;
- exactly one `InventoryMovement.PURCHASE` is created with reference `takvin-purchase:<id>`;
- row becomes `applied=True`;
- debt is updated exactly once by the existing ExcelManualSetting delta logic;
- no Digikala/account/payment ledger is touched.

Editing/replacing a day's purchase now:

- reverses exact old purchase movements/stock;
- deletes/recreates that day's rows;
- applies exact new stock;
- adjusts debt by `new_total - old_total`.

Deleting a purchase day reverses both its exact stock contribution and its debt contribution.

## Scoped production repair

`repair_takvin_purchase_stock_v59` targets only the requested date (default: server/application today) and only `[excel-web]` TakvinPurchase rows.

For each row:

- exact purchase movement present and matching -> already clean, no-op;
- `applied=True` with no purchase movement -> known V59 bug signature, add only missing HOME stock + movement;
- multiple/mismatched movements -> abort; do not guess.

The repair never changes Takvin debt, account entries, sales, Digikala, or purchase invoice rows.

It is idempotent and supports dry-run/default plus `--apply`.

## Deployment invariant

The V59 deploy:

1. backs up DB;
2. runs V48/V55/V56/V57/V58 + V59 regressions;
3. dry-runs today's Takvin purchase repair;
4. applies only missing purchase stock;
5. verifies:
   - Takvin qty increase = reported repair qty;
   - finished inventory increase = qty valued using current Takvin size rules;
   - capital increase = same finished-value delta;
   - Takvin debt unchanged by the repair;
   - raw/Digi/Dia/Darma/Novani/sales/account entries unchanged;
6. projects the new V59 valuation using the new image before recreating live web;
7. requires final live snapshot to equal that projection.

Success markers:

`SUCCESS: NOVANI COST RULE + TAKVIN PURCHASE V59 DEPLOYED`

and, when today's missing Takvin stock existed:

`SUCCESS: TODAY TAKVIN PURCHASE STOCK V59 REPAIRED`

## Rollback anchor

Branch created before V59:

`before-novani-cost-takvin-purchase-fix-v59-20260906`

at commit:

`bc161dcc4071e8f8acab610e6d848bd86d057095`
