# V114 — Clean icon sidebar and two-card definitions landing

**Base branch:** `v113-unit-production-cost-calculator`.

## Sidebar (presentation-only)
Nine direct sidebar destinations:
- داشبورد → dashboard
- فروش روزانه → sale_start
- گزارش جامع → report
- موجودی کالا → inventory center
- خرید تکی → existing Takvin purchase route (only the navigation label changes)
- تولید → existing material_report route (only the navigation label changes)
- دیجی‌کالا → existing Digikala center with its own internal cards
- حسابداری → existing finance center with its three cards
- تعاریف → settings_home two-card landing

Returns has moved into the Inventory center as a third card. Its existing route is unchanged. No Digikala submenus remain in the global sidebar.

Desktop sidebar is expanded with icon and label until pointer moves over main content; then it collapses to a 72px visible icon rail. Hovering the rail expands it. Mobile remains the existing modal/drawer menu. Reduced-motion CSS is included. Icons are lightweight text symbols, not downloaded assets.

## Definitions
`/settings/` now shows exactly two cards: محصولات و کدها and تنظیمات اولیه. The latter opens `/settings/initial/`, preserving the legacy settings screen and its original subpages. Only view routing/templates change; no database mutation.

## Parallel work safety
This feature is isolated to `v114-clean-icon-sidebar-navigation`; do not overwrite any contemporaneous UI branch. Before merging with work in a different chat, compare both branches and resolve any conflicting `templates/base.html` modifications deliberately.

Regression: `python manage.py check_clean_sidebar_v114`

Deployment confirmation:
`SUCCESS: CLEAN ICON SIDEBAR V114 DEPLOYED`

No schema migrations or business logic changes. Continue future work from the merged and production-confirmed descendant, not two divergent branches.
