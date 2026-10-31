# V94 — Global Jalali Date Picker + Darma Inventory Adjustment Default

Prepared: 2026-09-28
Branch: `v94-global-calendar-darma-default`
Base: V93 `dd757e635beab24fef128bd39b8ba6f865ad92c0`

## Goals

1. Every editable Jalali date field across the ERP should open the existing Jalali calendar picker on click instead of requiring manual typing.
2. Inventory → Transfer & Adjustment → Adjustment should open with **Darma** selected by default instead of whichever brand happens to be first in database order.

## Global calendar

The existing calendar endpoint and Jalali calendar data remain unchanged:

- `/calendar/picker/`
- `core.calendar_views.jalali_picker`

`templates/base.html` already loads `static/core/number_format.js` on every ERP page. V94 uses that already-global script to load `static/core/jalali_picker.js?v=94` exactly once.

The picker now recognizes editable inputs through the existing/common conventions used by the project, including:

- `.jalali-date`
- `.jalali-picker`
- `[data-jalali-date]`
- `name=date`
- `name=start` / `name=end`
- `name=effective_from` / `effective_to`
- `name=receipt_from` / `receipt_to`
- any non-hidden input whose name or id contains `date`

The chosen value remains Jalali `YYYY/MM/DD`, matching the project's existing parsers. The field is readonly for typing and opens the picker by click/Enter/Space.

A `MutationObserver` attaches the picker to date inputs inserted after initial page load, including dynamically generated receipt-filter controls.

The picker script is idempotent so pages that already explicitly include `jalali_picker.js` do not create duplicate calendars.

## Inventory adjustment default

V94 does **not** change `inventory_operations_v16.py`, StockBalance logic, InventoryMovement logic, transfer logic, or adjustment POST handlers.

The globally loaded UI script only does this on `/inventory/operations/`:

- find the existing `#adjust-brand` select;
- find the existing option whose visible name is `دارما`;
- select it;
- dispatch the same `change` event already used by the page to show the matching adjustment rows.

This is presentation-only. The user can still choose Takvin or Novani normally.

## Sale-price / dashboard safety

V94 does not modify V93 or V60 pricing code.

The V93/V60 contract remains:

- sale-price rules are date-effective per ProductSize;
- a future rule does not affect earlier sale dates;
- new sale rows use `sale_price_for(product_size, SaleDay.date)`;
- existing positive `SaleLine.sale_price` values stay frozen;
- creating or changing a price rule does not change stock quantities;
- historical dashboard sales/profit continue to use saved SaleLine prices/snapshots rather than being retroactively repriced.

## Regression

`check_global_calendar_inventory_v94` is read-only and verifies:

- the global loader is reachable from `base.html` through `number_format.js`;
- the V94 picker selector coverage and dynamic-input observer exist;
- `/calendar/picker/` still resolves to the existing calendar view and renders successfully;
- `/inventory/operations/` still resolves to the unchanged V16 inventory view and renders successfully;
- the Darma default is implemented only in the presentation layer;
- StockBalance, InventoryMovement, AppSetting, ProductSize, and SaleLine fingerprints are unchanged by the checks.

Expected marker:

`SUCCESS: GLOBAL CALENDAR + DARMA DEFAULT V94 CHECK PASSED`

## Deployment

Use:

`bash server_global_calendar_inventory_v94.sh`

The deployment must preserve all V93 pricing/business state and inventory state and recreate only the web container.

Production is confirmed only when the VPS prints:

`SUCCESS: GLOBAL CALENDAR + DARMA DEFAULT V94 DEPLOYED`
