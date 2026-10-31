# V115 — Stable Sidebar + Comprehensive Report UI

Parent: `v114-clean-icon-sidebar-navigation`. UI/report read-only changes only; no migrations.

## Sidebar
- Main HTML starts with `sidebar-collapsed` on desktop, eliminating expanded-then-collapsed flash on each new page.
- Sidebar rail (72px) stays present, with all nine icons and hover-to-expand.
- No animated sidebar width or main-content margin on desktop, to remove the unpleasant bouncing effect.
- Pointer on main content collapses rail; clicking nav collapses it before page navigation.
- Logout shows full «خروج از پنل» expanded, power glyph only collapsed.
- Mobile retains existing drawer controls.
- Full-page reload remains a normal server-rendered navigation; deliberately no artificial transitions that flash content.

## Comprehensive Report
- Sales top metric tiles are aligned and centered into a responsive 4-column desktop, 2-column narrow layout. Existing totals and logic remain intact.
- The canonical six read-only shared Finance KPIs are rendered inside the report using `finance_kpis()` and `_finance_kpis_v104.html`; no separate balances or account-management form.
- Darma price monitoring is moved from dashboard to comprehensive report, using the exact existing `dashboard_pricing_context(date.today())` and `_pricing_monitor_dashboard_v89.html` source.
- Dashboard no longer queries or shows that pricing block; its other KPI and charts are preserved.

## Safety and parallel UI work
Only:
`templates/base.html`, `static/core/sidebar-v115.css`,
`templates/core/report_excel_v3.html`, `core/report_v10.py`,
`templates/core/dashboard_excel_v89.html`, `core/excel_dashboard_v89.py`,
regression, docs and deploy script.

Do not overwrite another UI chat's branch. If both touch `templates/base.html`, merge with explicit conflict resolution and preserve both changes.

Regression: `python manage.py check_stable_sidebar_report_v115`.
Production marker: `SUCCESS: STABLE SIDEBAR + COMPREHENSIVE REPORT V115 DEPLOYED`.
