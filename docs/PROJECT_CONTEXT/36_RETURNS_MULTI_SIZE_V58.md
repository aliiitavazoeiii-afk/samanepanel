# V58 — ONE-SUBMIT MULTI-SIZE RETURNS

## User problem

The V57 return-entry workflow still required selecting one size at a time. Entering a quantity for M and then navigating to L reloaded the page, so unsaved M values disappeared. The user wants to enter M/L/XL/... together and submit once.

## New entry workflow

For a new standalone return under `/returns/`:

1. choose mode: color or product code;
2. choose brand: Darma or Takvin;
3. one shared return date is shown;
4. all allowed sizes for that brand are rendered simultaneously;
5. enter quantities only where needed;
6. press one `ثبت یکجای همه سایزها` button.

Blank fields are ignored.

Darma sizes remain M, L, XL, XXL, 3XL, 4XL. Takvin remains M, L, XL, XXL.

## Atomicity

All populated sizes in one submit run inside one database transaction. If any later size is invalid, every earlier size from the same submit is rolled back. There is no partial multi-size return.

## V57 history/edit/delete compatibility

V58 deliberately keeps one existing V57 return group per populated size rather than changing the V57 audit format. This preserves the already-tested semantics:

- each size appears as its own report row;
- each row can be viewed;
- each row can be edited;
- each row can be deleted independently;
- exact InventoryAdjustment + InventoryMovement audit records remain reconstructable.

A single V58 submit can therefore create multiple V57 report rows, but all rows are created atomically together.

Existing pre-V58/V57 return groups remain readable without migration.

## Inventory/accounting semantics

No business rule changed:

- standalone returns add stock to HOME only;
- KHORSHID is never touched;
- no sale is created;
- no sale profit is changed;
- Digikala receivable/fee is untouched;
- account entries/payments are untouched;
- finished inventory/capital changes only by the returned physical stock value.

Darma valuation continues to use the centralized V55 date-effective Darma cost.

## Edit behavior

Editing an existing V57 report remains intentionally single-size because each report group is a single size. This keeps exact reversal/replacement semantics. The multi-size UI applies to new entry.

## Active source

- `core/returns_v37.py`
  - `_apply_multi_size_return()`
  - `_entries_from_multisize_post()`
  - `_multi_size_sections()`
  - new-entry branch of `return_apply()`
- `templates/core/returns_v37.html`
  - all size sections on one form
  - one shared date
  - one submit button

No model, migration or URL change is required.

## Regression

`python manage.py check_returns_multisize_v58`

Checks:

- two Darma sizes are rendered/processable together;
- one submit creates both size reports;
- exact HOME quantities are added for both sizes;
- generated V57 reports are reconstructable and safe;
- deleting the generated reports restores exact prior HOME stock;
- an intentionally invalid later size rolls back the valid earlier size;
- test data fully rolls back;
- sales/account entries remain unchanged.

Expected marker:

`SUCCESS: RETURNS MULTI-SIZE V58 CHECK PASSED`

## Deployment

Rollback branch:

`before-returns-multi-size-v58-20260906`

Base commit:

`44b2ce63f90df1297d505a547266ce94b69c210b`

Deploy script:

`server_returns_multisize_v58.sh`

The deploy is read-only with respect to business data: it backs up the DB, runs V37/V55/V56/V57/V58 regressions, recreates web, verifies existing return history, and requires the complete business snapshot to remain identical.

Expected final marker:

`SUCCESS: RETURNS MULTI-SIZE V58 DEPLOYED`

Do not call V58 production-confirmed until the actual VPS success marker is posted by the user.
