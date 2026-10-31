# V109 — MATERIAL COLOR ROLLS + VERTICAL SHEET SUMMARY UI

Base: `stable-final-2026-10-04` at V108 stable-baseline lineage.

## Scope

Presentation/read-only summary only. No accounting, inventory, payment, material-sync, sewing-wage, or three-delivery mutation logic changes.

### Five base-color cards

Each of the five open-work cards now shows `طاقه تحویلی` above the three quantity rows.

The count is scoped to the SAME open work already represented by that color card:
- only Darma blocks;
- only blocks where saved cut > actually applied finished output;
- distinct non-empty `fabric_code` values count once;
- a positive-weight row without a fabric code counts as one uncoded roll.

The existing three numbers remain:
- باید تحویل شود
- تحویل‌شده
- مانده

Completed historical sheets remain excluded from the open-work card.

### Material-sheet collapsed summary

The existing summary items are stacked vertically:
- brand/destination
- models
- fabric codes
- material apply state
- applied delivery
- pending increase/reduction when present

Text is enlarged while pill padding is reduced, so readability improves without deliberately enlarging the badges themselves.

## Regression

`python manage.py check_material_color_rolls_ui_v109`

Required marker:
`SUCCESS: MATERIAL COLOR ROLLS + SUMMARY UI V109 CHECK PASSED`

Deployment still must pass the canonical V108 regression first.

Production marker:
`SUCCESS: MATERIAL COLOR ROLLS + SUMMARY UI V109 DEPLOYED`

## Continuation rule

V109 was created FROM the canonical stable branch. Future work must continue from the newest production-confirmed stable state, never from an older V97-V107 branch.
