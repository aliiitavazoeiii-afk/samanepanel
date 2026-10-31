# UI SAFETY V39

V39 is a presentation-only refinement on top of confirmed-live V38.

## User requirement

- add the user's Darma logo to the site;
- keep the newer Vazirmatn direction;
- make Persian typography less crowded/overweighted;
- do not change the slightest formula, calculation or business workflow.

## Allowed V39 application scope

Only these presentation assets are intentionally changed/added:

```text
static/core/darma-logo-v39.webp
static/core/ui-v39.css
static/core/number_format.js
```

`number_format.js` keeps all existing number-formatting and sidebar-navigation semantics; V39 only adds a small loader for `/static/core/ui-v39.css?v=39`.

No V39 business change is authorized in:

- `core/*.py`;
- models/migrations;
- `core/urls.py`;
- templates;
- V38 `ui-polish.css`;
- sale/import/allocation/snapshot logic;
- finance/capital/inventory/material/payment/receipt/return/calculator logic.

## Typography boundary

V39 keeps Vazirmatn but removes aggressive Persian letter-spacing and synthetic unusual weights. It uses normal Persian spacing and standard real weights (primarily 400/500/600/700/800), while keeping numeric KPI content tabular.

This is presentation only. No displayed value source is changed.

## Logo boundary

The user-provided Darma artwork is stored as:

```text
static/core/darma-logo-v39.webp
```

The checkerboard preview background was removed during asset preparation; the logo artwork itself remains the user's supplied design. It is displayed through CSS on the existing `.erp-brand` link, so navigation destination and DOM workflow remain unchanged.

## Rollback

Pre-V39 Git rollback branch:

```text
before-logo-typography-v39-20260829
```

Pre-V39 main commit:

```text
33e96888fc000a346f1fd0abdcbf8f982d3bdc01
```

This is a code rollback anchor only, not a database rollback.

## Deploy guard

Use:

```text
server_logo_typography_v39.sh
```

It must compare before/preflight/after values for:

```text
CAPITAL
FINISHED
RAW
DIGI
DARMA
TAKVIN
NOVANI
SALES
ACCOUNT_ENTRIES
```

All values must be identical across this cosmetic deployment.

Explicit success marker:

```text
SUCCESS: LOGO + TYPOGRAPHY V39 DEPLOYED
```

Until that marker and final snapshot are posted by the user, V38 remains the latest confirmed live version.
