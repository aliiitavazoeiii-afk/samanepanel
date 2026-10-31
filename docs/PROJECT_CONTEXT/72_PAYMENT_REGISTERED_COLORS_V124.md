# V124 — Registered Darma colors in receipts/payments purchase form

Base: V123 branch `v123-material-color-apply-inventory-transfer`. New branch `v124-dynamic-payment-fabric-colors`.

## Root cause

`/payments/?section=payments` renders `templates/core/payments_v91.html`, extending `payments_v22.html` with `_payment_edit_v22.html`. Both fabric and legacy elastic color selects consume `material_colors`.

Prior `core/business_tools_v91.py` set `material_colors = list(COLOR_LABELS.items())`, only nine hard-coded original raw material colors. Registered Darma colors live in `Color` rows with `StockBalance(brand=دارما)`, accessed by `colors_for_brand('دارما')` / `darma_material_choices()`. Adding a custom color/model via the existing inventory panel creates such balances for every applicable size, including quantity zero, so they should be selectable immediately in payments.

A second blocker was `core/material_purchase_v13._label()`, which rejected any color key not in the nine static `COLOR_LABELS` keys, even when someone managed to post a custom color.

## Fix

- `core/material_payment_colors_v124.py` gives the payment forms the historic nine stable keys followed by **every additional active Darma panel color** (key `color:<id>`), de-duplicated by normalized name. Registered names are read live; no hand synchronization or new schema.
- `core/business_tools_v91.py` now calls the helper for `material_colors`. Both new fabric payment and historical payment editor use the unchanged templates and new context.
- `core/material_purchase_v13._label()` now accepts only colors in that same helper; new purchases preserve the exact `color:<id>` in the existing V14 ledger and RawMaterialStock. Legacy keys continue to work without rewriting historical payments.
- No change to prices, payment amount calculations, bank movements, inventory purchase posting/reversal, cash ledger, sidebar, warehouse or tailor reports.
- Color options are scoped to the **Darma** brand (not unrelated brands with possibly same or different colors).

## Read-only verification

`python manage.py check_payment_colors_v124` verifies all live Darma registered colors appear in the dropdown, legacy options remain, tests post parsing of a synthetic custom fabric color, and ensures templates and view/parser consistently use the same helper. Does not write any DB row. Guarded V124 deployment takes a database backup, enforces clean checkout/Caddyfile preservation, requires V123 schema `0021` to be already applied, checks snapshots of finance and stock tables, and recreates only the web container after checks pass.

## Important deployment boundary

This is **V124 on top of V123**. It does not silently run the V123 schema migration or V121 financial repair. If prior version is not installed, finish its separately approved guarded deployment before installing V124.

Success marker: `SUCCESS: V124 DYNAMIC PAYMENT FABRIC COLORS DEPLOYED`.
