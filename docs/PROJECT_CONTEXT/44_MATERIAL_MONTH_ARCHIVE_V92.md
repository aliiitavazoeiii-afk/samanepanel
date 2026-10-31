# V92 — MATERIAL REPORT MONTH ARCHIVE + CURRENT MONTH KPIs

Date: 2026-09-27
Branch: `v92-material-month-archive-kpis`
Base: V91 `3d0a996633d944b87539de796f281dbe83d97f85`

## User intent

The material report page had all sheets in one long chronological list. After the Jalali month changes, all prior-month sheets should collapse into one monthly row such as `صورت شهریور ۱۴۰۵`; opening that row reveals every sheet from that month.

The page header should also be cleaner and show current-month operational totals next to search.

## Active route

`/material-report/` now uses:

`core.material_report_v92.material_report`

Mutation routes remain unchanged:

- save → `material_report_v23.material_block_save`
- add model → `material_report_v23.material_block_add_model`
- apply materials → `material_report_v23.material_block_apply_materials`
- apply output → `material_report_v23.material_block_apply_output`
- unapply/delete remain their previous handlers

V92 POST sheet creation delegates directly to V23 creation semantics.

## Current-month KPIs

The Jalali month is derived from the same server date convention already used by the project.

Five KPIs are shown next to the search box:

1. `پارچه تحویلی این ماه`
   - unique non-empty `fabric_code` values count as rolls;
   - a positive-weight row with no code still counts as one uncoded roll.

2. `وزن تحویلی این ماه`
   - sum of positive `weight` values in current-month material sheets.

3. `حداقل تعداد تحویلی`
   - sum of positive `cut` values in current-month sheets.

4. `تعداد تحویل‌شده`
   - sum of `MaterialReportOutputApplied.quantity` for current-month sheets;
   - typed but not yet applied output does NOT count.

5. `مانده تحویل`
   - per sheet: `max(sheet cut total - applied delivered total, 0)`;
   - then summed across current-month sheets;
   - surplus in one sheet cannot hide shortage in another.

All KPIs are read-only and are attributed by the material sheet date.

## Monthly archive behavior

`templates/core/material_report_v92.html` extends the existing V36 material template and keeps all V23 forms/actions intact.

- Current Jalali month sheets stay as normal individual rows.
- Completed/past Jalali months collapse client-side into one expandable monthly row.
- Example: `صورت شهریور ۱۴۰۵ · ۶ صورت`.
- Clicking the monthly row reveals every sheet from that month.
- V92 renders all material sheets, not only the former first 40, so an older month is not partially hidden.
- Direct anchors such as `#block-123` automatically open their containing monthly archive.
- Search still works inside archived sheets; matching archives open automatically.

## Header cleanup

The old explanatory paragraph under `گزارش مواد اولیه` and the green live-cost explanatory note are removed from the visible V92 page. The main title and the new-sheet form remain.

## Safety

No accounting, inventory, material-consumption or production mutation formula was changed.

Read-only regression:

`python manage.py check_material_month_archive_v92`

It verifies:

- active route;
- Jalali current-month boundaries;
- roll/weight totals;
- cut/applied/pending totals;
- all material sheets are rendered;
- archive/KPI UI markers;
- no material/inventory row-count changes.

Safe deploy:

`bash server_material_month_archive_v92.sh`

The deploy script:

- backs up PostgreSQL;
- snapshots business and material invariants;
- has Docker Hub → `mirror.gcr.io` fallback inherited from V91;
- runs V90, V91 and V92 regressions;
- checks PRE == PROJECTED == FINAL;
- recreates only `web` after checks pass.

Success marker:

`SUCCESS: MATERIAL MONTH ARCHIVE V92 DEPLOYED`

GitHub branch state is not proof of production deployment. Production is confirmed only after the VPS prints the success marker and invariant snapshots remain equal.
