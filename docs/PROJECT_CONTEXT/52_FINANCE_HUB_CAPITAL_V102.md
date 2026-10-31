# V102 — FINANCE HUB CONSOLIDATION + CANONICAL CURRENT CAPITAL

Prepared: 2026-10-01  
Branch: `v102-finance-hub-consolidated`  
Base: V100 `775d598b5449c2ef9752a9a6724297c396a5309e`

## User intent

Finance & Tools is one primary destination, not an expandable sidebar group.

Opening `/finance/` must show exactly three cards:

1. **پرداخت‌ها** → the existing payments/receipts workflow, unchanged.
2. **حساب‌ها** → the account-management UI historically located in Comprehensive Report.
3. **محاسبه‌گر** → the current calculator, unchanged for now.

The Finance hub itself must not repeat account balances below the cards.

## Branch-lineage conflict resolved

V100 and V101 were sibling branches from V99, not a linear continuation.

- V100 had the desired direct Finance root and account visibility work.
- V101 restored an expandable Finance submenu, which conflicts with the user's explicit final UX.
- V102 therefore continues from V100 and intentionally does **not** merge the V101 submenu behavior.

V102 is the authoritative continuation for this Finance restructuring.

## Accounts source of truth

No account data is copied or migrated.

`/finance/accounts/` continues to read:

- `ExcelManualRow.ACCOUNTS`
- `ExcelManualRow.PERSONS`
- `ExcelManualSetting(digikala_receivable)`
- `ExcelManualSetting(takvin_debt)`
- the existing Digikala account ledger
- the existing Dia Gallery receivable ledger

Mutations still route through `report_v10.manual_report_action()`, preserving:

- desired Digikala total -> stored base conversion;
- protected system-managed «خودم» tracking row;
- existing manual account/person validation.

Payments/receipts routes and their accounting semantics are unchanged.

## Comprehensive Report separation

V102 stops treating the account move as a JavaScript-only visual hide.

When `report_v10` renders Comprehensive Report:

- account/person rows are no longer fetched for the report UI;
- editable Digikala receivable and Takvin debt forms are not rendered there;
- the report keeps read-only capital summary values;
- account/person editing lives only in `/finance/accounts/`;
- asset management remains in Comprehensive Report because the user only moved the Accounts domain.

The existing V97 presentation cleanup may still remove the legacy Accounts domain wrapper, but the sensitive account forms/rows are already absent from the server-rendered HTML.

## Canonical current-capital calculation

The economic formula is unchanged:

```text
capital =
    accounts/persons + Dia receivable
  + finished inventory
  + raw materials
  + Digikala receivable
  - Takvin debt
  + assets
```

V102 removes the duplicate implementation of this current-capital formula from `report_v10.py`.

The single canonical current calculator is now:

`core.capital_history_v87.current_capital_breakdown()`

It explicitly exposes:

```text
inventory_total = finished_inventory_total + materials_total
capital_total =
    accounts_total
  + inventory_total
  + digikala_receivable
  - takvin_debt
  + assets_total
```

`report_v10` consumes these canonical values instead of independently recomputing them.

This is a structural consistency fix only. No business formula, valuation rule, fee rule, stock rule, payment rule, or ledger rule is changed.

## Historical-capital boundary

V87 historical capital remains ledger reconstruction, not a guaranteed full historical snapshot where old values were overwritten without history.

V102 does not invent missing historical cost/revaluation data. The historical-warning behavior remains in place.

## Finance navigation

The global sidebar continues to replace the old Finance accordion with one direct link:

`/finance/`

V102 cache-busts the shared presentation helper and disables ERP HTML caching as in V100 so a stale pre-deploy Finance menu cannot survive.

## Regression

Run:

```bash
python manage.py check_finance_hub_v102
```

The check is read-only and verifies:

- `/finance/` is exactly a three-card hub;
- no account preview is rendered on the hub;
- the sidebar Finance entry is a direct root link, not an accordion;
- `/finance/accounts/` renders every active account/person row from the DB;
- payments and calculator routes remain unchanged;
- every canonical current-capital component equals an independent recomputation from the same authoritative DB sources;
- the final capital equation balances exactly;
- no business state is written.

Expected marker:

`SUCCESS: FINANCE HUB + CAPITAL V102 CHECK PASSED`

## Deployment

Use:

`bash server_finance_hub_v102.sh`

Expected production marker:

`SUCCESS: FINANCE HUB + CAPITAL V102 DEPLOYED`

GitHub state alone is not production confirmation.
