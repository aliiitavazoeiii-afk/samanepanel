# V91 — RECEIPT DATE / SOURCE FILTERS

Prepared: 2026-09-27

## Scope

V91 is read-only for financial state. It adds reporting controls to the existing `مالی و ابزار → دریافتی‌ها` page.

It does **not** change receipt creation, editing, deletion, Mellat balance mutation, Digikala receivable mutation, Dia Gallery receivable mutation, ledger rules, or capital formulas.

The active page route becomes:

- `/payments/` -> `core.business_tools_v91.payments`

Mutation routes remain unchanged:

- payment add/edit/delete -> V62
- receipt add/edit/delete -> V64

## User-visible behavior

The existing `آخرین دریافتی‌ها` card header now contains:

- Jalali `از تاریخ` filter;
- Jalali `تا تاریخ` filter;
- source filter:
  - `همه دریافتی‌ها`
  - `دیجی‌کالا`
  - `Dia Gallery`
- `اعمال فیلتر` and `پاک کردن` controls;
- total amount for the current filtered result;
- count of matching receipt rows.

When no filter is selected, the header shows the total/count of all recorded receipts, ordered newest first.

When a date/source filter is selected, both the displayed rows and the header total/count use exactly the same queryset.

Example:

- from `1405/06/01`
- to `1405/06/31`
- source `دیجی‌کالا`

shows only matching Digikala receipts and displays the exact sum of those matching rows in the same header.

## Date behavior

Dates use the existing `parse_jalali_date()` parser.

It accepts Persian/Arabic or Latin digits and `/`, `-`, or `.` separators, then converts to Gregorian dates only for database filtering.

An invalid date or a start date after the end date does not query a misleading range. The page shows an error and the filtered result is empty/zero until the input is fixed.

## Financial safety

V91 does not call any apply/reverse receipt functions.

The following existing mutation code remains authoritative and unchanged:

- `core/business_receipts_v64.py`
- `core/business_tools_v62.py` payment mutations

V91 only reads `DigikalaSettlement` rows and computes `Sum("amount")` / count for reporting.

## Regression

Run:

```bash
python manage.py check_receipt_filters_v91
```

Expected marker:

```text
SUCCESS: RECEIPT FILTERS V91 CHECK PASSED
```

The regression checks:

- `/payments/` resolves to the V91 GET view;
- template compiles and renders;
- all-receipts total/count equals direct ORM aggregation;
- Jalali date-range filtering equals direct ORM filtering;
- source filtering equals direct ORM filtering;
- invalid reversed date range is rejected;
- receipt/payment/account-entry row counts are unchanged.

## Deployment

No migration is required.

Use:

```bash
bash server_receipt_filters_v91.sh
```

Expected final marker:

```text
SUCCESS: RECEIPT FILTERS V91 DEPLOYED
```

Do not call V91 production-confirmed until the actual VPS marker is observed.
