# V120 — Novani color-first six-size wholesale invoice entry

Parent: `v119-novani-wholesale` at `fe3f105737ccd8ae0aff3ef26c6b92a6b8f1a90c`.

## User requirement
Keep V119 navigation, accounting, inventory deduction, customer/Pedram ledger, Excel exports and half-width historical invoice cards **exactly as they are**. Replace only the *new invoice* entry interaction:
1. Enter Jalali invoice date and buyer as before.
2. Choose a Novani model/color from the complete list of defined Novani inventory colors. Selecting it adds one compact **color card**. Additional colors add additional cards; selecting a duplicate focuses its existing card rather than duplicating it. Users may remove a chosen color.
3. Each color card has **one unit price shared by that color's sizes**, with the previous price recalled where available, plus a horizontal, responsive quantity table for all six currently defined Novani sizes **S, M, L, XL, XXL, 3XL**.
4. Fill counts for each size in that color. Blank/zero means no sale for that size. Available stock per size is shown, with inline overstock warning.
5. Automatically calculate per-color piece totals and money, plus aggregate invoice pieces and money. On submit, include *only nonzero quantity cells* in a list of matching `color_id`, `size_id`, `quantity`, `unit_price` hidden form inputs. All sizes of a color share its single entered price. Server V119 `parse_items/post_invoice` are unchanged, preserving transactional short-stock rejection and existing Novani HOME inventory and buyer/Pedram bookkeeping.
6. All color cards post together under **one** date, buyer, request UUID and invoice. No repetitive row-by-row Add Model workflow.

## Scope
- Edited: `templates/core/wholesale_v119.html`, V119 read-only UI check `core/management/commands/check_wholesale_v119.py`, isolated `core/test_wholesale_v119.py` to test a multi-color, multi-size invoice; project handoff docs; new V120 deploy script.
- **Not edited:** sidebar; core models/migrations; `core/wholesale_logic_v119.py` and every V119 finance/stock ledger; prior V118 fabric and report logic.
- Existing Novani ERP size configuration is S through 3XL. Do not silently create 4XL/5XL/6XL size/inventory rows; if future requirements extend the canonical Novani size range, separately plan schema/inventory support.
- V120 new invoice matrix is JavaScript-enhanced; only a nonempty invoice is posted; monetary values are recalculated independently server-side.

## Guarded deployment
Branch: `v120-wholesale-color-size-matrix`.
Command: `bash server_novani_color_matrix_v120.sh`.
Based on the V119 guarded deploy, preserves local modified `Caddyfile`, performs database backup and expected-data hash comparison, idempotently checks/applies only existing approved new-table migration 0020 when not already installed, and runs inherited V108/V113/V116/V118/V119 checks. New tests remain isolated in Django test DB.
Marker: `SUCCESS: V120 NOVANI COLOR SIZE MATRIX DEPLOYED` plus `PRE = PROJECTED = FINAL`.

Do not run previous V119 deploy script while checked out on the V120 branch; script explicitly checks its own branch.
