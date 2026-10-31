# V97 — MATERIAL UI + FINANCE CENTER

## Purpose

Refine the V96 inventory/material move based on live UX feedback, and move account management out of the comprehensive report into a single Finance & Tools center.

## Raw materials UX

`/inventory/materials/` is now hierarchical:

1. Root cards: `پارچه` / `کش`
2. Fabric locations: `انبار` / `نزد خیاط` / `دپو`
3. Elastic locations: `انبار` / `نزد خیاط`
4. Only the selected location table is rendered as the primary working table.

Tables use fixed, centered numeric columns so quantities, average prices and values line up under the correct headers.

### Fabric aggregation

Warehouse fabric remains lot-based in `RawMaterialStock` for purchase/reversal provenance. V97 does not merge storage rows or migrate data.

The visible table groups same physical color/material identity into one row and shows:

- total quantity
- weighted average price for display
- total value
- edit icon
- delete icon

The old visible `ردیف داخلی` details/table is removed. Edit opens a modal only when needed; underlying purchase rows remain intact.

### Transfers

Fabric transfer to tailor is available from both the warehouse screen and the tailor screen. It consumes warehouse lots safely across the selected color group using the existing `transfer_fabric_to_tailor()` function per source lot.

Elastic transfer to tailor is available from both elastic warehouse and elastic tailor screens and continues to use `transfer_elastic_to_tailor()` unchanged.

Direct fabric entry remains allowed for warehouse/depot only, matching pre-V97 semantics. Tailor inventory is populated through transfer so source provenance is preserved.

## Finance & Tools

`/finance/` is the single Finance & Tools landing page with exactly three cards:

- `دریافتی‌ها و پرداختی‌ها` -> existing `/payments/` V91 page
- `حساب‌ها` -> new `/finance/accounts/`
- `محاسبه‌گر` -> existing `/calculator/`

Payments/receipts logic and calculator logic are not changed in V97.

Global sidebar presentation is changed by `static/core/number_format.js`: the previous expandable Finance & Tools submenu is replaced at DOM load by one direct `/finance/` link. `/finance/`, `/payments/`, and `/calculator/` all mark that single link active.

## Accounts move

The new Finance Accounts page contains the account-management UI that previously lived in the comprehensive report:

- bank/person account total
- Digikala receivable desired-total control
- Dia Gallery receivable
- Takvin debt
- manual account rows
- person rows

Account mutation semantics are not duplicated. `finance_center_v97.accounts_action()` calls the existing `report_v10.manual_report_action()` so the Digikala base/ledger rule and the protected system-managed `خودم` row remain exactly the same; only the redirect changes back to Finance Accounts.

## Comprehensive report

`report_v10.report()` still computes all account, inventory, raw-material and capital values exactly as before. It now renders `report_excel_v97.html`.

`report_excel_v97.html` removes only the visible V76 `حساب‌ها` management domain after the existing V96 inventory-domain removal. Capital formula/context remain unchanged.

## Safety / invariants

No model or migration changes.

Protected logic unchanged:

- `core/models.py`
- `core/models_final.py`
- `core/material_flow.py`
- `core/report_v5.py`
- inventory valuation
- payment/receipt flows
- calculator formulas
- sale/import/cost logic

V97 regression command:

`python manage.py check_material_finance_center_v97`

Expected final marker:

`SUCCESS: MATERIAL + FINANCE CENTER V97 CHECK PASSED`

Deploy:

`bash server_material_finance_center_v97.sh`

Expected deploy marker:

`SUCCESS: MATERIAL + FINANCE CENTER V97 DEPLOYED`

GitHub state is not proof of production deployment. Production is confirmed only after the VPS deployment passes PRE / PROJECTED / FINAL state equality and the final marker is printed.
