# UI SAFETY V38

V38 is a presentation-only modernization pass and is now **confirmed live on production**.

## User requirement

The site may become cleaner, more modern, more attractive and more responsive, but **no accounting, inventory, sales, Digikala, COGS, material, production, payment, receivable, return, snapshot or ledger formula/behavior may change**.

## V38 operational scope

The only application presentation asset intentionally changed in V38 is:

```text
static/core/ui-polish.css
```

No V38 application change was made in:

- `core/*.py`
- models or migrations
- `core/urls.py`
- active templates
- JavaScript business/workflow code
- database rows
- accounting settings

The existing DOM, forms, URLs, POST targets, context values and calculations are retained.

The confirmed deployment output explicitly stated:

```text
V38 application change: static/core/ui-polish.css only
Routes/Python/templates/models/migrations/workflow JS: unchanged
Accounting/inventory/sales/material/payment/return/calculator semantics: unchanged
All protected economic invariants: unchanged
```

## Visual changes

V38 adds a global visual layer for:

- darker and more restrained navy background;
- clearer true-glass cards;
- improved sidebar and active navigation states;
- refined sticky top bar;
- stronger typography hierarchy;
- cleaner KPI cards;
- modern inputs, buttons, badges and alerts;
- cleaner table headers/rows and scroll containers;
- improved report/capital/material visual surfaces;
- improved responsive/mobile spacing;
- reduced-motion support.

## Protected business boundary

The V38 deploy verifies that the following source families are unchanged from the pre-V38 main baseline:

- sales/import/allocation/snapshot code;
- finance and Digikala fee code;
- capital/report calculation code;
- finished/raw inventory code;
- material consumption/output/wage code;
- payments/purchases/prepayments code;
- Digikala receipts code;
- returns V37 code;
- calculator V37 code;
- routes and active templates.

## Economic invariant check

The deploy captures and compares before/preflight/after values for:

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

Every value must be byte-for-byte identical across a V38 cosmetic deploy. Any difference is a deployment failure and must not be normalized or manually balanced.

Confirmed successful V38 final snapshot:

```text
CAPITAL=5430972371
FINISHED=1115731500
RAW=1994448050
DIGI=812517154
DARMA=12072
TAKVIN=1195
NOVANI=3630
SALES=202
ACCOUNT_ENTRIES=206
```

Backup:

```text
backups/before-ui-modernization-v38-20260829-223111.sql
```

## Git safety

Pre-V38 rollback branch:

```text
before-ui-modernization-v38-20260829
```

Pre-V38 main commit:

```text
b488fee9701e1a4b4c266dd92aa371db5d159e99
```

First V38 UI commit:

```text
ead072e8c994f449674f339bc6cb47c634d3cf89
```

The rollback branch is a Git/code anchor only. It is not a database rollback.

## Live-state rule

V38 is confirmed live because the VPS printed:

```text
SUCCESS: UI MODERNIZATION V38 DEPLOYED
```

and the final economic snapshot matched the starting live snapshot exactly.

The latest authoritative live checkpoint is maintained in `docs/PROJECT_CONTEXT/08_LIVE_STATE_AND_CHECKPOINTS.md`.

Standing rule: future important changes must update the context pack; future confirmed deployments must also update the live checkpoint using actual server output.
