# UI / BUSINESS SAFETY V45 — DIA GALLERY

V45 is not cosmetic-only: it adds one explicit new sales channel requested by the user. Existing sales/accounting/inventory semantics outside this channel remain frozen.

## Allowed V45 business effects

Only when the user submits Dia Gallery quantities:

- Darma physical stock decreases by the entered color/size quantity;
- Dia Gallery receivable increases by `quantity × 71,000 toman`;
- Dia sale COGS uses the frozen Darma InventoryModelCost captured for that Dia row;
- capital changes by sale profit (`gross - COGS`), with no Digikala fee;
- dashboard/daily/comprehensive sales totals include the Dia sale.

## Forbidden side effects

Dia Gallery must never:

- change Digikala receivable;
- create a Digikala fee;
- be imported/replaced by Digikala XLSX;
- create an independent finished-inventory brand/value;
- mutate Takvin or Novani stock;
- change raw materials, payments, production or standalone returns;
- alter existing SaleLine/SaleSnapshot/SaleAllocation history.

## UI contract

- Add a separate `Dia Gallery` box to the existing daily-sales date page.
- The entry page uses Darma colors and Darma sizes.
- Fixed price is visible as 71,000 toman per short and cannot be changed by the normal UI.
- `فروش Dia Gallery` is shown as an automatic/read-only receivable under accounts / ریز حساب‌ها.
- Existing Darma/Takvin/Anbaresh boxes remain intact.

## Deployment safety

- Code rollback anchor: `before-dia-gallery-v45-20260831`.
- Database backup required before migration/deploy.
- `0015_dia_gallery_sale` is additive only.
- `check_dia_gallery_v45` must pass its transaction rollback accounting test.
- Pre/post deployment business invariants must match exactly because deployment itself does not register a real sale.
- GitHub code is not production-live until the user posts the successful deploy output.
