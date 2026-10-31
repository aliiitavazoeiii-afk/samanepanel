# V100 — FINANCE ACCOUNTS VISIBLE

## Goal

Make the existing account rows impossible to lose visually after moving account management out of Comprehensive Report.

## Source of truth

No account data is copied or migrated. Both `/finance/` and `/finance/accounts/` read the same active `ExcelManualRow` sources that the comprehensive report historically used:

- `ExcelManualRow.ACCOUNTS`
- `ExcelManualRow.PERSONS`
- existing `ExcelManualSetting` rows for Digikala receivable / Takvin debt
- existing Dia Gallery and Digikala ledger helpers

## V100 UI behavior

`/finance/` keeps the three requested main cards:

1. دریافتی‌ها و پرداختی‌ها
2. حساب‌ها
3. محاسبه‌گر

Below those cards it now also shows the live current account rows and person rows with their balances. The حساب‌ها card still opens `/finance/accounts/` for the complete editable tables.

## Cache protection

ERP HTML responses receive `Cache-Control: no-store, no-cache, must-revalidate, max-age=0` plus a V100 static helper URL. This prevents a stale Finance hub from surviving a deployment.

## Regression

The finance regression now reads the actual active account/person rows from the database and verifies:

- the Finance hub contains exactly the same number of account rows;
- every account row ID is rendered on the hub;
- every person row ID is rendered on the hub;
- every account/person row is present in the full `/finance/accounts/` editable table;
- the old Finance submenu is absent;
- the direct Finance link and all three hub cards exist;
- no business state changes occur.

Expected marker:

`SUCCESS: FINANCE ACCOUNTS VISIBLE V100 CHECK PASSED`
