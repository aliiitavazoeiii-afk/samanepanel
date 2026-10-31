# V126 — Jalali history filters and cumulative totals for Payments

Parent: V125 `v125-material-archive-month-report`, parent SHA `1a80b084848353948cb1c5b7be5f84effe88fa2b`.
New branch: `v126-payment-history-filters`.

## Exact user requirement
Match the filters already present on the **دریافتی‌ها** page in the **پرداختی‌ها** section. Provide start and end Jalali dates, apply/clear, filtered actual-cash sum, and **all-time total unconditionally visible even with a filter**. The payment ledger and payment-entry form must not change.

## Semantics
- Existing `BusinessPayment` records only, using `amount` (cash actually paid) rather than invoice purchase value, weighted raw-material stock value, tailor/account balances, or sales volume.
- Inclusive Gregorian dates parsed from operator-entered Jalali `payment_from` and `payment_to`; blank means unbounded. Reversed/invalid Jalali range causes a visible error, 0 rows and a 0 filtered sum without losing the full-history total.
- `all_total` and `all_count` are computed over the **complete** `BusinessPayment` queryset each time and are NEVER restricted by the chosen dates or current page. Payments made from Mellat and Mofid are included. Deletes/edits automatically recalculate the live history.
- `filtered_total` and `filtered_count` are calculated on the entire range. Output is date/ID descending and displayed in pages of 100 with preserved filter query strings. The old `_payment_rows` default last-100 limit remains when called without a queryset; V126 explicitly passes a page to the existing V60/V62 annotation logic for label, actual paid amount, purchase/prepayment explanation, person-payee description and source account. No separate posting business rules.
- The view renders `core/payments_v126.html`, which extends the **unchanged** receipts filter template `payments_v91.html` and adds only the payments-specific header replacement. Existing mobile and desktop payment cards, edit/delete forms and receipt filter logic remain intact.
- On payment landing page the current-month totals remain unchanged and do not follow the date filter. No old bank/ledger/history values are recomputed or written.
- Search pagination: `?section=payments&payment_from=1405/07/01&payment_to=1405/07/30&payment_page=2`.

## Read-only tests
1. Unit tests `core.test_payment_filters_v126` on isolated Postgres CI data include 105 synthetic payments across Mehr/Shahrivar/Aban from both banks, proving total is calculated from all 105, both boundaries inclusive, filtered counts/totals independent of 100-row pagination, 0 matches, one-sided dates and malformed/reversed ranges.
2. Production read-only command `python manage.py check_payment_filters_v126` compares live ORM sums/counts and first/last date scope, page two if relevant, validates V91 receipt totals, renders V126 template and verifies no payment/receipt/account-entry row counts changed.
3. `check_receipt_filters_v91`, `check_payment_colors_v124`, `check_material_archive_month_v125`, production V123 material/stock tests, and all existing guarded finance/inventory regressions run in safe deploy.

## Deployment
`bash server_payment_history_filters_v126.sh` from branch `v126-payment-history-filters` in `/opt/darma-general`. Requires running app and completed V121/V123 prerequisites from previous releases. Guarded read-only release checks exact SHA-approved read-side Python files, no migrations or change to financial posting, checks local Caddyfile intact, backs up PostgreSQL, compares the existing protected ERP table hashes PRE=PROJECTED=FINAL, rebuilds web with the approved Docker Hub / two registry fallback process, restarts web only. The previous V125 report archive and V124 payment color changes remain included.

Success: `SUCCESS: V126 PAYMENT HISTORY FILTERS DEPLOYED`. No production runtime executed by GitHub Actions; the operator must run this command on their own server.
