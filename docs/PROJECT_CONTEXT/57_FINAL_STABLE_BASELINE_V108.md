# FINAL STABLE BASELINE — 2026-10-04

Canonical development branch:

`stable-final-2026-10-04`

This branch is intentionally based on V106, not V103, so the final V104/V105 Finance/Calculator/report work is part of the ancestry instead of being selectively reconstructed later.

## Locked product state

### Comprehensive report
- Uses the canonical V105/V106 `current_capital_breakdown()`.
- Account/person management stays in Finance -> Accounts.
- The old three account/receivable/debt boxes are NOT rendered in server HTML when account management is moved.
- The old account/person manual tables are NOT rendered in server HTML.
- No JavaScript is required to hide those moved finance controls.

### Finance & Tools
Exactly three cards:
1. دریافتی‌ها و پرداختی‌ها
2. حساب‌ها
3. محاسبه‌گر

The six shared read-only balances remain above the cards:
Mellat, Mofid, Digikala receivable, Dia Gallery receivable, tailor balance, Takvin debt.

### Accounts / person payments
- Active PERSONS rows appear dynamically in payment targets.
- Person payment reduces selected source account and person balance atomically.
- Edit reverses and reapplies.
- Delete restores both.
- A person row referenced by payments cannot be deleted.

### Calculator
Final V105 behavior:
- cost + target sale margin -> required selling price;
- sale price + cost -> canonical Digikala fee + net profit + sale margin + profit/cost;
- code-first Darma/Takvin profitability table with collapsed size details;
- target percentage means net profit / sale price.

### Material report
- V105 six KPI strip remains.
- Average saved Darma/base-color cut remains.
- V106 three delivery mini-boxes remain; their sum is the canonical output target.
- Five additional open-work color cards remain directly below the KPI strip:
  black, white, navy, pink, cream.
- Each color shows expected cut, actually applied delivery and pending quantity.
- Completed old sheets are excluded from the open-work cards.

### Navigation
Finance & Tools is a native direct sidebar link. JavaScript must not construct the Finance link.

## Development rule

Every future feature branch MUST be created from `stable-final-2026-10-04` after its deployment has completed with:

`SUCCESS: FINAL STABLE BASELINE V108 DEPLOYED`

Do not branch from V97/V98/V99/V100/V101/V102/V103/V104/V105/V106/V107 for new work after the stable baseline is production-confirmed.

Every future deploy must run at least:
- `check_final_baseline_v108`
- `check_finance_native_v103`
- `check_finance_calculator_v104`
- `check_margin_material_v105`
- `check_person_payments_three_delivery_v106`

and must preserve PRE / PROJECTED / FINAL business-state hashes for presentation/read-only changes.
