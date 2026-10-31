# V119 — Novani wholesale invoices and customers

Base: `v118-unapplied-fabric-rolls-color-weight` (3c58b33f56e253edfb1f9781d90ca3e28747ee7d). V118 sidebar behavior and all existing sales, cash, materials, and capital formulas unchanged.

## UI
- Original first six sidebar links remain in place with the same SVGs/transitions. Correct only label `خرید تکی` to `خرید تکوین`.
- Add one extra top-group SVG warehouse/wholesale link `فروش عمده`, route `/wholesale/`. It is before the existing top-group separator, no other links changed.
- Compact two-column, expandable invoice cards; separate new-person form, customer ledger, Jalali date, Novani model/color x size S/M/L/XL/XXL/3XL, quantity, one separately editable unit price per line and buyer, totals, immutable posted invoice, per-buyer price recall from last invoice, and Excel export (four tabs: Invoices/Items/Buyer balances/Receipts).

## Data and accounting
- New migration `0020_novani_wholesale` creates only new tables (WholesaleCustomer, WholesaleInvoice, WholesaleInvoiceLine, WholesaleReceipt) and seeds a unique special wholesale buyer **پدرام**. No existing records backfilled, no changes to existing column schema. The registered buyers other than Pedram use their existing `ExcelManualRow(PERSONS)` when the name matches; otherwise a new person row is created.
- Wholesale is **Novani only**, and not part of daily `SaleLine`/Digikala transactions. Items must be existing Novani inventory model/colors and sizes, present in its single HOME stock bucket, with sufficient positive available quantity. **Posting invoice** is one database transaction: post immutable invoice and frozen per-line quantities/unit prices/amounts; subtract HOME stock; create one `InventoryMovement(SALE)` with reference `novani-wholesale:<invoice-id>:<line-id>` for every line; post the receivable/account impact.
- Ordinary buyers: invoice gross is added to their shared `ExcelManualRow(PERSONS)` person account. Later receipts reduce that specific person row and increase canonical Mellat row, transactionally. No other bank account used.
- **Pedram only**: invoice gross is recorded as a named claim in its wholesale invoice ledger; the same gross is immediately offset by **subtracting** it from the pre-existing shared `خیاط` person/account row (matching the user's explicit instruction). `tailor_deducted_amount` is stored on each invoice and counts as settled by this offset, so the *remaining customer receivable* is zero for fully offset Pedram invoices. There is no extra capital-counted person row and no second bank receipt for Pedram. The gross claim/offset remains visible per invoice and in Excel.
- This financial offset follows the user's expressly requested sign convention, even though capital treatment may differ from an ordinary external invoice. Existing capital formulas are not modified. Review the Pedram balance change after first live invoice.
- No edits/deletes of posted invoices/receipts yet, by design, so history is never silently rewritten. No auto restocking, no negative inventory or foreign-brand stock mutations.
- One-use UUID request_token unique per invoice/receipt; concurrent or duplicate submissions cannot charge twice. A shortage/invalid price/duplicate color-size aborts **all** writes.
- The UI deliberately leaves legacy comprehensive monthly gross/profit formulas untouched: wholesale invoices stay in their own invoices/ledger/Excel until a separately authorized accounting/reporting integration.

## Verification and guarded deployment
- `python manage.py check_wholesale_v119`: read-only route/schema/HTML, rendered page+Pedram form, immutable invoice gross/count/movement and customer balance checks.
- `python manage.py test core.test_wholesale_v119 --noinput`: isolated transactional tests using a dedicated Django test database; **never run against production data directly**.
- `bash server_novani_wholesale_v119.sh`: guarded backup, strictly allowlisted files, local Caddyfile preserved with SHA256, check exact legacy-model import suffix only, `core/migrations/0020_novani_wholesale.py` only, `makemigrations --check`, `migrate core 0020_novani_wholesale` once, V116/V118/V119 read-only regressions, V108/V113, protected PRE/PROJECTED/FINAL data hashes. On success displays `SUCCESS: V119 NOVANI WHOLESALE DEPLOYED`.
- Never run an old V118 deploy script on V119. Do not alter Caddyfile or reset data.
