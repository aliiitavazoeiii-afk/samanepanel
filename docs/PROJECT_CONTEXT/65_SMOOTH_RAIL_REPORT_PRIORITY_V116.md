# V116 — Smooth SVG navigation + first-screen Comprehensive Report
Parent: `v115-stable-sidebar-report-dashboard` at `f6424fe0be725833e8f54247c5cc45c0d40b3634`.

## Absolute boundary
This is a presentation / read-only query cleanup only. No models, migrations,
sale/accounting/material/stock/business operation, snapshots, price settings,
account balances, or capital formula may change. Existing real production data
must hash identically before, projected, and after deployment.

## Sidebar
- Nine existing direct URLs and labels remain unchanged.
- Replace ambiguous font/glyph characters with nine **self-hosted inline SVGs**.
- Desktop remains a stable 72px icon rail. Hover or keyboard focus expands
  the sidebar visually to 246px **as an overlay**, not by moving/reflowing
  the entire main content. Desktop interaction uses CSS, not JS mouseenter.
- Reduced-motion preference supported. Mobile drawer behavior remains intact.
- Logout uses an actual SVG power icon and text revealed with the rail.
- Older `sidebar-v114.css` and `sidebar-v115.css` remain in the source for
  historical compatibility; `sidebar-v116.css` is loaded last and overrides
  their collapsed/expanded styles deliberately.

## Comprehensive report
First-screen server-side structure:
1. Six shared V104 Finance KPIs (Mellat, Mofid, Digikala, Dia, tailor, Takvin).
2. Compact sales summary for the existing selected date/period:
   total sales, total net profit, sold shorts, Digikala fees, net sale margin.
3. Existing `capital-hero` showing the original historical/current capital
   number plus finished inventory and material balances.

Preserves selected period, historical capital warnings, and original calculations.
The V76 browser-only report folding remains, while the long analytical tables
are CSS-hidden from the top before its DOM rearrangement to avoid pushing capital
below the fold during initial paint.

Pricing monitoring is **not** calculated or rendered inside Comprehensive Report
anymore. A single linked card titled «پایش قیمت‌گذاری دارما» is placed next
to «گزارش‌های تحلیلی» and «کالای سرمایه‌ای» using the existing V76 fold grid.
The original `/pricing-monitor/` and `/pricing-monitor/export/xlsx/` routes
are unchanged, including their business-date comparison and XLSX export.

## Description cleanup
Remove disposable page taglines, Dashboard chart-summary prose and dashboard
quick-card descriptions; remove Definitions and Inventory landing descriptions.
Presentation-only subtitle classes are suppressed globally. Never hide required
financial details, form labels, validation errors, historical-capital warnings
or operational instructions.

## Safe deployment
Branch: `v116-smooth-rail-report-priority`
Script: `bash server_ui_rail_report_v116.sh`
Regression: `python manage.py check_ui_rail_report_v116`
Expected success marker:
`SUCCESS: V116 SMOOTH RAIL + REPORT PRIORITY DEPLOYED`

The old V115 `check_stable_sidebar_report_v115` deliberately expects the
now-retired embedded pricing table and four-column sales summary; for V116 use
the new version-specific regression plus V108/V113 baseline checks.
Do not claim production is live until the user posts successful deployment output.
