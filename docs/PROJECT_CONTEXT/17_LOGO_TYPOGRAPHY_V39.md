# 17 — LOGO + TYPOGRAPHY V39

This file records the V39 presentation refinement after confirmed-live V38.

Status at creation: **committed to GitHub, NOT YET CONFIRMED LIVE**.

The latest confirmed production version remains V38 until the user posts successful VPS deployment output from `server_logo_typography_v39.sh`.

---

## 1. User requirement

The user supplied the Darma logo and requested:

- add the logo to the site;
- keep the newer font direction;
- fix the typography because the Persian text had become visually crowded/overweighted;
- do not change any formula or calculation.

V39 is therefore classified as **presentation-only / UI-only**.

---

## 2. Pre-change safety state

Pre-V39 `main` commit:

```text
33e96888fc000a346f1fd0abdcbf8f982d3bdc01
```

Rollback branch:

```text
before-logo-typography-v39-20260829
```

This branch is only a Git/code anchor and is not a database rollback.

---

## 3. Application scope

V39 intentionally adds/changes only:

```text
static/core/darma-logo-v39.webp
static/core/ui-v39.css
static/core/number_format.js
```

The existing V38 stylesheet remains unchanged.

`number_format.js` retains its existing:

- Persian thousands separator behavior;
- money-input binding;
- standalone Returns sidebar injection;
- Payments/Calculator sidebar injection.

V39 only adds a small global stylesheet loader for:

```text
/static/core/ui-v39.css?v=39
```

No routes, templates, models, migrations or Python business files are changed.

---

## 4. Logo implementation

The user-provided square Darma artwork was prepared as a small WebP static asset with the checkerboard preview background removed:

```text
static/core/darma-logo-v39.webp
```

The artwork is shown on the existing `.erp-brand` home link. The link destination and navigation workflow are unchanged.

Because the original DARMA lettering is dark, the logo is placed on a restrained light/frosted plaque inside the dark sidebar rather than recoloring the user's artwork.

---

## 5. Typography implementation

V39 keeps Vazirmatn and specifically reduces visual crowding by:

- removing aggressive `letter-spacing` from Persian prose/headings/navigation;
- avoiding unusual synthetic weights such as 650/750/900 for normal text;
- using standard weights primarily 400/500/600/700/800;
- increasing practical Persian line-height;
- reducing over-bold navigation/table/label text;
- keeping KPI/numeric data strong but cleaner;
- preserving tabular numeric rendering for money/quantity values.

This changes only how text is rendered, never which values are displayed or how they are calculated.

---

## 6. Frozen business boundary

V39 must not change:

- capital equation;
- finished/raw inventory valuation;
- Digikala fee or receivable;
- SaleSnapshot or SaleAllocation;
- sales/import/returns;
- inventory movement logic;
- material Save / Apply Materials / Apply Output;
- production cost or sewing wage;
- payments/purchases/prepayments;
- Digikala receipts;
- calculator V37;
- dashboard alert semantics;
- any current route or POST target.

---

## 7. Deployment

Purpose-specific deployment script:

```text
server_logo_typography_v39.sh
```

The script:

1. starts/checks PostgreSQL;
2. takes a full `pg_dump`;
3. captures live business invariants;
4. enforces V39 source scope from the exact pre-V39 commit;
5. builds the web image;
6. runs migration drift + Django checks;
7. runs the current V37 return/calculator regression;
8. checks V39 logo/CSS/loader source presence;
9. verifies new-image business values equal live values;
10. recreates web/restarts Caddy;
11. reruns live checks;
12. requires the final business snapshot to equal the starting snapshot exactly.

Protected values:

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

Success marker:

```text
SUCCESS: LOGO + TYPOGRAPHY V39 DEPLOYED
```

Do not record V39 as live until the user posts that server output.

---

## 8. Continuation rule

For future visual tweaks:

- preserve this cleaner Persian typography baseline unless the user requests another direction;
- use the Darma logo asset rather than recreating the old orange `D` brand mark;
- keep changes presentation-only unless the user explicitly requests a business-rule change;
- after successful deployment, update `08_LIVE_STATE_AND_CHECKPOINTS.md` with the actual final server snapshot, not copied historical numbers.
