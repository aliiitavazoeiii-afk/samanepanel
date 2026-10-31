# V22 PAYMENT HANDOFF

Date: 2026-08-27

This file documents the latest payment behavior on `main`; it is newer than the v21 payment notes.

## User-reported problems that v22 fixes

1. The `آخرین پرداخت‌ها` table became messy after inline edit rows were added.
2. Editing only the date of a fabric purchase tried to reverse the original fabric stock and failed when some fabric had already moved to the tailor.
3. Material purchase value was forced to `quantity × unit price`; user needs the actual/final paid amount to be independently editable. Example: 10kg elastic × 2,600,000 = calculated material value 26,000,000 but actual/final cash paid was 25,584,000.

## V22 rules

- Active payment routes use `core.business_tools_v22` for payments/add/edit/delete.
- Receipt add/edit/delete remain on `core.business_tools_v21`.
- Payment UI uses `templates/core/payments_v22.html` and `_payment_edit_v22.html`.
- Desktop payment rows use a fixed responsive table; mobile uses separate cards so edit forms cannot break the list layout.
- For a received material purchase, `BusinessPayment.amount` is the ACTUAL/FINAL cash paid.
- Calculated material value still comes from material quantity × entered unit price and remains the raw-material inventory valuation basis.
- If actual paid differs from calculated material value, NO supplier debt/credit row is created automatically. The difference is simply visible in the payment UI. A lower actual cash payment therefore increases current capital relative to the calculated inventory value by that difference.
- Supplier `ریزحساب` is reserved for material PREPAYMENTS where no goods/material details are entered. Example: a 50m payment with note `پارچه فروش حسینی` and no fabric details decreases Mellat 50m and creates/increases positive account row `پارچه فروش حسینی` by 50m.
- Legacy v21 prepayment ledgers remain supported and are converted safely when edited.

## Safe material-purchase edit behavior

`_purchase_signature()` compares only physical/value purchase details: material type/color/title/weight/unit price. It intentionally ignores payment date, note, and actual cash paid.

If an existing purchase is edited and the purchase signature is unchanged:

- DO NOT reverse raw-material stock;
- DO NOT require fabric to be returned from tailor;
- reverse only the old Mellat cash effect;
- update date/note/actual paid;
- refresh the purchase ledger;
- apply only the new Mellat cash effect.

Therefore a date-only edit works even after fabric has moved to tailor, and changing 26,000,000 actual paid to 25,584,000 does not touch the 10kg elastic inventory.

If weight/color/title/unit price/payee changes, v22 still uses full safe reverse/reapply. If the original material can no longer be safely reversed, the edit is blocked rather than corrupting inventory.

## Deployment

Rollback branch:

`before-payment-metadata-settlement-v22`

Safe deploy:

```bash
cd /opt/darma-general
git pull --ff-only
bash server_payment_metadata_settlement_v22.sh
```

Expected ending:

`SUCCESS: PAYMENT METADATA + SETTLEMENT V22 DEPLOYED`

The deployment itself must not change capital or Darma stock. A later user correction of an actual payment amount can intentionally change capital, because cash is being corrected while material valuation remains based on quantity × unit price.
