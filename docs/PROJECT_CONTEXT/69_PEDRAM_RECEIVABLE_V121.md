# V121 — Correct Pedram signed receivable, repair posted invoices exactly once, and group numbers

Parent: `v120-wholesale-color-size-matrix` at `980e0a65ee538fc5a986e770da44403c2a70589a`.

## Critical accounting clarification from owner, 14 Oct 2026

The existing **خیاط** `ExcelManualRow(PERSONS)` is signed:
- Negative amount = **we owe Pedram**, a liability.
- Positive amount = **Pedram owes us**, our receivable.
- Registering a Novani wholesale invoice to Pedram adds **+invoice gross** to that same signed tailor account (first paying down any older negative balance, then creating positive claim).
- Applying output/delivery from Material Report keeps its existing `_adjust_tailor_balance(-wage_change)`: sewing wage reduces our receivable or increases our debt. **DO NOT CHANGE** material report code.
- No separate capital-counted Pedram person account and no automatic bank cash receipt at sale time. Existing capital formula includes the signed tailor row.
- Previous V119/V120 bug did `tailor.amount -= gross` and incorrectly saved `invoice.tailor_deducted_amount=gross`, falsely marking the sale settled. New invoice now saves `tailor_deducted_amount=0` and **adds** gross to tailor amount.
- Pedram customer card shows the real shared signed tailor account from `_tailor_row(create=False)`, not just gross wholesale sales (so past debts, advances and later production wages all affect the displayed balance).
- Other customers, stock movements, bank receipts, invoice line prices and all existing business formulas remain untouched.

## Existing production invoice correction
Reported at least one invoice of **144,384,000 toman** already posted under wrong-sign logic. If its old `tailor_deducted_amount=144384000` and old tailor debited 144384000:
- Correct current account balance by **+288,768,000 toman** (reverse earlier -144384000; post correct +144384000). This is **not** a new sale and does not alter Novani physical inventory.
- Mark the affected invoice offset from old gross to **zero**, so customer receivable display is not incorrectly settled.
- `python manage.py repair_pedram_wholesale_v121`: dry-run preview IDs, amount and resulting signed tailor balance. `--apply --expected-gross 144384000`: applies only when exactly the requested old affected invoices total 144384000. If actual gross is different, abort before mutation; review first.
- The repair locks the Pedram customer, old posted invoices and tailor row under one transaction. An affected invoice is identified exclusively by customer.is_pedram and positive `tailor_deducted_amount` identical to `total_amount`. It resets marker to 0 only upon the successful adjustment. Repeated runs see no remaining old offset and apply **zero** adjustment.
- The guarded install verifies protected inventory/table hashes remain unchanged and signed tailor row increased by exactly twice the recovered sum.

## UI
- On wholesale page only, all monetary and quantity entry inputs visually group three digits with Persian thousands separator `٬` as the user types: each color's shared price, each size quantity, and ordinary buyer receipt amount. Source strings are converted back to valid integers in JS on invoice POST, and backend `positive` already recognizes commas and Persian digit forms.
- All financial/quantity readouts on wholesale page now use existing `groupnum` template filter. Signed values remain signed and grouped.
- Dates, phone numbers, IDs are not grouped.
- Existing V120 selectable color matrix, six Novani sizes, all sidebar links/animations and invoice cards otherwise unchanged.

## Deployment
Branch: `v121-pedram-receivable-fix`. Deploy script `server_pedram_receivable_v121.sh`; it preserves local `Caddyfile`, DB backup before mutation, V119 migration 0020 if not installed,  V121 preview and **exactly** checked one-time repair, V108/V113/V116/V118/V119 static/data checks, and PRE/PROJECTED/FINAL hashes of legacy inventory data. This is an **explicit authorized financial data correction** and therefore signed tailor account is intentionally changed by expected +2*old incorrect gross. Never run a stale V120 script after switching to V121.
