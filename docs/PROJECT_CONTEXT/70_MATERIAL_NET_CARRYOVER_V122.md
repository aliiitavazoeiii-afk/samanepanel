# V122 — Net production delivery per color, current Jalali month and open carryover

Branch: `v122-material-net-current-open`. Based on `v121-pedram-receivable-fix` (HEAD before V122: 92a159b35192665ba26a526f3bd8eec6189db931).

## Scope and invariant: Darma only

- No changes to ERP models, database migrations, any raw-material consumption or finished-goods stock synchronization handler, balance sheet/accounting, wholesale/Pedram repair, Caddyfile or sidebar.
- Only `core/material_report_v92.py` aggregates and `templates/core/material_report_v92.html` presentation changed; read-only audits, safe install script and project handoff added. All saved production records remain intact.

## Critical correction

Previously V92 summarized `pending += max(0, cut_per_sheet - applied_output_per_sheet)` across sheets. This had **two bugs**:
1. Applied-to-inventory pieces were displayed as physically delivered when the user had saved delivery values but not synced them yet.
2. Max-clamping each individual sheet before combining prevented one roll's surplus from offsetting another roll's shortfall.

New metrics sum signed quantities first, then clamp once:
- `expected = sum(saved raw cut per sheet/color)`.
- `delivered = sum(saved output_data size totals per sheet/color)` (entered/registered delivery, NOT inventory stock application).
- `applied = sum(MaterialReportOutputApplied quantities)` independently.
- `net_delta = delivered - expected`.
- `pending = max(0, -net_delta)`.
- `surplus = max(0, net_delta)`.

Example: pink two rolls cut 750+750=1500; first received 998 (+248), second 540 (-210): **registered delivered = 1538, pending = 0, surplus = 38**. If only 1233 pieces are applied to stock, 1233 is displayed as `اعمال‌شده به موجودی`, **not** `تحویل ثبت‌شده`.

This applies to monthly operational KPIs and the five base-color delivery progress cards; V118 separately verified distinct unapplied fabric-code roll counts and lifetime weight retain their exact original semantics.

## Month and prior open sheets

- Current operation = all sheets with dates inside the **current Jalali month** plus only **unfinished** sheets from earlier months (none from future months).
- An older sheet is unfinished if ANY color has a meaningful fabric row without a positive color-specific `MaterialReportConsumption(kind=FABRIC)`, OR its saved delivered quantity is less than the corresponding cut, OR its saved delivered quantities differ from stock-applied output quantities. Compare by color and sizes, avoiding false completion when only one color of a multi-color sheet was applied.
- The page keeps such older sheets visible among current active sheets, visibly labeled `بازمانده ماه قبل`. Fully settled older sheets remain grouped under collapsed month archives and are still available for searching/inspection.
- Only values from current + carried-open sheets feed delivery progress for five colors and month KPIs. No prior closed/future date contaminates this operational delivery summary. The historical `وزن تحویلی کل` per base color remains all-time for compatibility with previous express user requirements.

## Read-only audit and diagnosis of existing pink discrepancy

Run `python manage.py check_material_net_v122` inside the web container. It does not write production data. It first verifies pure synthetic two-roll case, then checks live saved quantity equations and outputs per-sheet pink: `id`, `date`, `code`, `cut`, `registered`, `applied`, `fabric_unapplied`. This matters because user's reported **1530 expected, 1233 applied, 298 pending** could reflect saved cut quantities or old per-sheet clamp; **without the live input we cannot assume 1500 is what is actually stored**.

## Safe deployment

`bash server_material_net_open_v122.sh`. Script allows only V122 changes, protects local Caddyfile SHA256, blocks edits to financial/stock/write logic and DB schema, takes PostgreSQL SQL backup, requires prior migration 0020 and completed V121 Pedram repair (dry-run and assert gross=0, never auto-repair), checks V110/V116/V118/V119 and V122 audits, compares protected business DB table hashes PRE=PROJECTED=FINAL, and recreates only web service after checks pass. No new migration. If prior V121 financial repair is still pending, deploy **stops without modifying any data**, rather than silently applying a repair during this unrelated material report update.

Success marker: `SUCCESS: V122 NET MATERIAL DELIVERY + OPEN MONTH CARRYOVER DEPLOYED`.
