# 16 — UI MODERNIZATION V38

This file records the first meaningful project change after the exhaustive V37 handoff pack.

Status: **CONFIRMED LIVE on production**.

Confirmed deployment date: 2026-08-29.

---

## 1. User requirement

The user requested a site-wide visual cleanup and modernization with an absolute constraint:

> improve visual defects and make the site more attractive/current without making the slightest change to formulas or calculations.

Therefore V38 is classified as **UI-only / presentation-only**.

No business-rule change was authorized or made.

---

## 2. Pre-change safety state

Pre-V38 `main` commit:

```text
b488fee9701e1a4b4c266dd92aa371db5d159e99
```

A rollback branch was created before the UI modification:

```text
before-ui-modernization-v38-20260829
```

This branch points to the pre-V38 Git state only. It is not a database rollback.

---

## 3. V38 application-code scope

The only application presentation file intentionally modified in V38 is:

```text
static/core/ui-polish.css
```

First V38 UI commit:

```text
ead072e8c994f449674f339bc6cb47c634d3cf89
```

No V38 business implementation change was made to:

- `core/*.py`;
- `core/urls.py`;
- models;
- migrations;
- templates;
- workflow JavaScript;
- database data;
- accounting settings.

The confirmed production deployment output also explicitly stated:

```text
V38 application change: static/core/ui-polish.css only
Routes/Python/templates/models/migrations/workflow JS: unchanged
Accounting/inventory/sales/material/payment/return/calculator semantics: unchanged
All protected economic invariants: unchanged
```

Existing routes, forms, POST targets, view contexts and calculations therefore remain the V37 operational baseline.

---

## 4. Visual changes now live

The V38 global UI layer modernizes the existing DOM rather than rebuilding workflows.

It includes:

- a darker, cleaner navy background with more restrained ambient gradients;
- refined true-glass cards and panel hierarchy;
- improved sidebar spacing, active states and visual hierarchy;
- refined sticky top bar;
- stronger page-title/KPI typography;
- cleaner buttons and focus states;
- modern form controls;
- cleaner tables, scroll containers and hover states;
- updated badges, alerts and status treatments;
- improved comprehensive-report/capital visual surfaces;
- improved material-report surfaces without changing material semantics;
- tablet/mobile spacing refinements;
- reduced-motion accessibility support.

The existing Vazirmatn + orange-accent + dark-navy design contract remains in force.

---

## 5. Business invariants explicitly frozen in V38

V38 did not change any behavior in:

- capital equation;
- finished inventory valuation;
- raw-material valuation;
- Digikala canonical fee;
- Digikala receivable;
- SaleSnapshot;
- SaleAllocation;
- normal/manual/Digikala sale inventory flow;
- daily XLSX replacement/idempotency;
- title resolver;
- material Save / Apply Materials / Apply Output separation;
- Darma/Novani output destinations;
- sewing wage;
- payments/material purchase/prepayment reversal;
- Digikala receipts;
- inventory adjustments/transfers;
- standalone returns V37;
- calculator V37;
- dashboard alert query semantics.

A cosmetic change that changes any economic value remains a bug.

---

## 6. V38 deployment guard

Purpose-specific deploy script:

```text
server_ui_modernization_v38.sh
```

The script:

1. starts/checks PostgreSQL;
2. takes a full `pg_dump` backup;
3. captures the current live economic snapshot;
4. checks Git diff scope against the exact pre-V38 main commit;
5. rejects changes to Python, routes, templates, migrations or workflow JavaScript;
6. builds the latest web image;
7. runs `makemigrations --check --dry-run`;
8. runs Django `check`;
9. runs the current V37 returns/calculator regression check;
10. verifies the V38 CSS marker/basic source safety;
11. compares new-image economic values with live values before recreating web;
12. recreates web and restarts Caddy only after preflight succeeds;
13. reruns live checks;
14. compares final economic values byte-for-byte with the starting snapshot.

Protected snapshot fields:

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

Any difference fails deployment.

Confirmed success marker:

```text
SUCCESS: UI MODERNIZATION V38 DEPLOYED
```

---

## 7. Confirmed live checkpoint

Final production snapshot posted by the user:

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

Deployment backup:

```text
backups/before-ui-modernization-v38-20260829-223111.sql
```

The older confirmed V37 capital checkpoint was:

```text
5441972371
```

The V38 deployment boundary shows:

```text
5430972371
```

Difference:

```text
-11000000
```

This difference must **not** be attributed to V38. The V38 deploy succeeded only because its starting live snapshot and final snapshot matched exactly. Therefore the 11,000,000 difference occurred before V38 deployment, through intervening production/business activity. The specific event was not identified in the provided output, so future debugging must not invent a cause.

`08_LIVE_STATE_AND_CHECKPOINTS.md` is authoritative for this current live checkpoint.

---

## 8. Continuation rule

For any follow-up visual refinement after V38:

- keep the change in presentation layers where possible;
- inspect the exact active page/template before changing page-specific layout;
- do not modify Python merely to make a visual number look different unless the user explicitly requests a semantic change;
- preserve forms, field names, URL names, HTMX targets and POST behavior;
- run the same economic invariant comparison on deployment;
- after successful deployment, update this context pack and the live checkpoint again.
