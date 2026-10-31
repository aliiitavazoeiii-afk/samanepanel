# 12 — VERSION TIMELINE V18 TO V37

This timeline captures why each major version exists, what it changed, and whether its meaning is still active. It is not a substitute for current route inspection.

Last synchronized: 2026-08-29 after confirmed V37 live deployment.

---

## V18 — Darma full physical baseline

Problem:

- historical stock had location/cell integrity issues including negative KHORSHID;
- isolated fixes were unsafe.

Solution:

- user supplied full physical HOME and KHORSHID count after 3 Shahrivar sales;
- reconcile exact matrix;
- total physical = 13,475;
- historical audited = 13,467;
- quantity correction +8;
- at 61,000, value/capital correction +488,000.

Important:

- end-of-day 3 Shahrivar baseline;
- day-3 sales not reapplied afterward.

Rollback branch:

```text
before-darma-physical-baseline-v18
```

---

## V19 — Anbaresh sales-only + Novani inventory/material brand

Major semantic split:

### Anbaresh

- manual sales/reporting brand only;
- physical stock comes from Darma;
- no independent inventory/capital asset.

### Novani

- real inventory/production brand;
- one inventory bucket;
- real capital asset.

### Material reports

- became brand-aware Darma/Novani;
- Darma output -> KHORSHID;
- Novani output -> own bucket.

This superseded older assumptions that Anbaresh was a normal inventory brand or every material output belonged to Darma.

---

## V20 — corrected Khorshid cream/red XXL + Telegram alerts/inventory evolution

Physical spreadsheet correction:

```text
KH cream XXL 260 -> 400
KH red XXL   140 -> 0
```

Net total unchanged.

Telegram inventory alert rules also stabilized around:

- HOME target 30;
- total production warning <=60;
- after-report + daily 09:00 Tehran;
- no continuous spam.

---

## V21 — daily report edits and finance/prepayment evolution

Daily report actions:

- safe sale-price update without inventory reapplication;
- sale-line delete/reversal path.

Prepayment/finance logic evolved toward more explicit guarded ledgers.

---

## V22 — payment metadata / actual paid / settlement semantics

Key improvement:

- actual paid can differ from material invoice value;
- physical purchase details have their own signature;
- metadata/actual-paid edits can avoid unnecessary stock reapply;
- material prepayment becomes owned supplier-account asset;
- full apply/reverse guarded.

Payment #6 elastic example later validated this semantics.

Active payment add/edit/delete remains V22 at current handoff.

---

## V23 — Digikala delivery status parser

Added support for current delivery status forms including:

```text
اماده ارسال/تحویل
```

while blocking return/cancel/failure markers.

Current daily_order_views_v8 imports V23 apply engine.

---

## V24 — forensic reset after 3 Shahrivar

Context:

- wrong code06 composition/red inventory;
- grey 4XL anomaly;
- cream3XL mismatch;
- later daily reports needed removal/re-entry.

V24 semantics:

- preserve 3 Shahrivar;
- reverse/delete SaleDays strictly after it;
- clear related receivable entries;
- fix code06 source issue;
- hard-restore exact corrected physical day-3 Darma matrix.

Reason hard baseline was needed:

- sale reversal alone may not reconstruct HOME/KH split because of auto-transfer history.

This is a forensic command, not routine.

---

## V25 — title precedence attempt

Problem:

Digikala row with seller code rah220 but title D-220 was being counted as rah-220.

V25 moved toward title precedence, but compatibility/generic resolver behavior still allowed wrong state or existing data remained stale.

Lesson: partial precedence changes were not strong enough.

---

## V26 — daily report drilldown UI

Added:

- Darma/Takvin brand cards;
- size chips;
- model/code/colors;
- allocation-first color display;
- desktop/mobile detail layout.

Deployment script initially hung because one-off container started Gunicorn. Script later fixed with `--entrypoint python`.

Daily report source remains `daily_report_v8`; V37 uses `daily_report_v21.html` presentation without inline returns.

---

## V27 — strict title-only resolver

Permanent fix for product identity:

- seller-code column discarded at parse time;
- model identity from title only;
- D220 cannot become rah220 because seller metadata says rah220;
- Takvin 1-654 -> 654-1;
- brandless model 400 accepted only when unique;
- unknown/ambiguous titles fail closed.

Also corrected source code06 composition red -> cream.

Confirmed V27 deployment output was posted at the time.

Important non-retroactive point:

- existing wrong SaleLine required reimport to be replaced/reversed.

---

## V28 — elastic purchase diagnostic/repair tooling

User observed 5kg+5kg purchase but aggregate showed 10kg+10kg.

Diagnostic proved:

- purchase ledger = 5/5;
- no duplicate BusinessPayment;
- variants parsed/applied separately.

Also exposed that aggregate row note is not reliable provenance.

A targeted repair command was created for the stated case, with dry-run and strict warning that resetting to payment ledger quantity would erase legitimate prior stock if any existed.

---

## V29 — capital audit

Goal:

Reconcile opening 31 Mordad capital + Shahrivar profit versus current site.

Findings during audit:

- sale profit exactly matched `72,012,896`;
- Digikala discrepancy negligible relative to total issue;
- purchase differences/adjustments needed component bridge.

First audit printed too many movement rows and appeared stuck; later compact approach grouped adjustments.

Lesson: capital debugging is component bridge, not force-set total.

---

## V30 / V30B — Shahrivar workflow reset

V30 attempted atomic reversal/removal of sales, payments, Digikala receipts.

Failed safely on a fabric purchase because part of the purchased fabric was no longer in warehouse.

Because transaction rolled back, nothing changed.

V30B introduced special rebase/preserve semantics for payments where user explicitly wanted correct material/cash effects retained as starting baseline while clearing UI/history rows for forensic rebuild.

Special-purpose only.

---

## V31 — 31 Mordad Darma baseline

User provided end-of-31-Mordad workbook.

Totals:

```text
14,864 Darma shorts
```

Workbook aggregate included negative historical cells.

Because it lacked location split, V31 preserved KHORSHID and adjusted HOME to match aggregate each cell.

Used only to rebuild day-by-day sales during bug hunt.

---

## V32 — day-3 physical stock reconcile

After user re-entered sales through 3 Shahrivar, exact physical day-3 HOME/KH sheets were re-applied:

```text
HOME 4,585
KH 8,890
TOTAL 13,475
```

This restored a clean physical start for subsequent day-by-day debugging.

---

## V33 — Novani material sizes/isolation

Requirement:

- Novani sizes S..3XL;
- Darma unchanged M..4XL;
- Novani output only to Novani.

Backend guard ensured S did not leak to Darma/Takvin.

First deploy attempt reached feature check but failed later due snapshot-script syntax error; rerun required to confirm live deployment.

---

## V34 — Novani missing wage repair

V33 had accidentally omitted tailor sewing wage from Novani Apply Output.

Actual current block was 3,630 pieces, not initial remembered 3,160.

Confirmed wage rate:

```text
110,000 / 12
```

Correct total wage:

```text
33,275,000
```

V34 repaired historical missing wage and added marker to prevent double repair.

---

## V35 / V35B — two-way editable delivered output for both brands

Requirement expanded from Novani to Darma too.

Current semantics:

- edit cumulative delivered cells;
- clear/reduce allowed;
- sync delta in either direction;
- stock reduced from correct destination on negative delta;
- wage returned on negative delta;
- Darma cost/value reversal uses existing costed production path;
- insufficient stock aborts atomically.

Also changed UI to show cut and shortage/surplus, grand delivered total.

---

## V35C — reverse-color cut display fix

Bug:

reverse black/white/navy showed cut values copied from base colors.

Fix:

reverse models use their own cut source key and remain zero unless a dedicated cut row exists.

---

## V36 — UI simplification + first return workflow

UI phase hard rule:

- formulas/system frozen;
- dashboard alerts simplified;
- comprehensive report visually grouped;
- initial return workflow added inside daily report.

The user later rejected the inline return UX.

The comprehensive report grouping remains useful/active; inline return does not.

Operational roundtrip checks were added to protect payments/receipts during UI work.

---

## V37 — standalone returns + current-margin calculator

User explicitly requested:

- remove inline daily-report return completely;
- create standalone Returns under daily work;
- mode color/code;
- brand Darma/Takvin;
- size before entries;
- HOME-only inventory effect;
- no sale/Digikala/finance side effect;
- add calculator that preserves each brand's current realized profit percentage when cost changes using exact Digikala rules.

V37 implementation:

- old daily return route removed;
- standalone `/returns/` + `/returns/apply/`;
- daily report back to v21 template;
- calculator routes to `calculator_v37`;
- source-scope guard protects core formulas;
- regression tests rollback real stock test;
- deployment compares economic invariants before/after.

Confirmed production output:

```text
SUCCESS: STANDALONE RETURNS + CALCULATOR V37 DEPLOYED
```

Final snapshot:

```text
CAPITAL=5441972371
FINISHED=1115731500
RAW=1994448050
DIGI=812517154
DARMA=12072
TAKVIN=1195
NOVANI=3630
SALES=202
ACCOUNT_ENTRIES=206
```

This is the latest confirmed live version at handoff.

---

## General timeline lesson

Version numbers are history, not architecture.

A newer version may:

- wrap an older base helper;
- keep an older route for one action;
- retire only part of a previous feature;
- leave historical files in repo.

Always use current `core/urls.py` + current imports to determine active code.
