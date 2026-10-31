# V98 — FINANCE NAV + UI POLISH

## Scope

Presentation-only follow-up to V97.

- Increase only the numeric font size in the three raw-material KPI boxes; card dimensions and labels remain unchanged.
- Remove link underlines globally across the ERP UI, including material/fabric/elastic selection cards.
- Replace the old hard-coded expandable «مالی و ابزار» sidebar group with one direct «مالی و ابزار» link to `/finance/`.
- `/finance/` remains the V97 three-card hub: payments/receipts, accounts, calculator.
- Existing `/payments/`, `/finance/accounts/`, and `/calculator/` routes and their business logic remain unchanged.

## Safety

No model, migration, accounting formula, inventory flow, payment/receipt handler, calculator logic, or capital formula changes.

Regression command:

`python manage.py check_finance_nav_polish_v98`

Expected deployment marker:

`SUCCESS: FINANCE NAV + UI POLISH V98 DEPLOYED`
