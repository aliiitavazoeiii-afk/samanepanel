# V103 — NATIVE FINANCE NAVIGATION

Prepared: 2026-10-01  
Branch: `v103-native-finance-nav`  
Base: production-confirmed V102 `2596e804ef0d81e4de0c204f14275ab7bc69e3ba`

## Why V103 exists

V102 deployed successfully and all business-state hashes remained identical, but the user reported that the visible Finance navigation still looked unchanged and Accounts could not be found.

The root structural problem was not accounting or routing. V102 still depended on a presentation middleware/JavaScript rewrite to transform the old expandable Finance group into a direct root link. The V102 regression also wrapped the view with that middleware, so it proved the rewrite logic rather than proving that the base template itself was correct.

V103 removes that ambiguity.

## Native source-of-truth navigation

`templates/base.html` now directly renders:

```text
مالی و ابزار -> /finance/
```

as a normal sidebar link.

The legacy expandable Finance group is removed from the template itself.

No middleware rewrite is required to make the link correct.

## Finance hub

`/finance/` remains the V102 three-card hub:

1. پرداخت‌ها
2. حساب‌ها
3. محاسبه‌گر

The Accounts card directly points to:

`/finance/accounts/`

The Accounts page still uses the exact V102 account/person sources and canonical current-account component.

## JavaScript

`static/core/number_format.js` no longer creates or relocates Finance navigation.

It only:

- recognizes the native `base-v103` Finance link;
- removes a stale duplicate legacy Finance group if one somehow exists in the DOM;
- updates the active state.

The base template loads the helper with `?v=103`.

## Middleware

`V98PresentationMiddleware` no longer rewrites Finance navigation.

It only:

- enforces no-cache headers for ERP HTML;
- injects the V103 helper only as a fallback if a page omitted it;
- reports whether the native Finance link exists.

## Regression

New command:

`python manage.py check_finance_native_v103`

This verifies before middleware:

- base.html contains the native direct Finance link;
- base.html contains no expandable Finance group;
- the direct-rendered Finance page contains the native link;
- the hub contains exactly three cards;
- the Accounts card points to `/finance/accounts/`;
- every active account/person row is visible on the Accounts page;
- JavaScript no longer constructs Finance navigation;
- middleware recognizes, rather than creates, the native nav;
- no business state changes.

Expected marker:

`SUCCESS: NATIVE FINANCE NAV V103 CHECK PASSED`

## Deployment

Use:

`bash server_finance_native_v103.sh`

Expected final marker:

`SUCCESS: NATIVE FINANCE NAV V103 DEPLOYED`

No accounting, sales, payment, inventory, material, pricing, calculator, or capital formula source changes from V102.
