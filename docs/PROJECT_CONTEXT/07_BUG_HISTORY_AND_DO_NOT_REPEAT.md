# 07 — BUG HISTORY AND DO-NOT-REPEAT LIST

This is a forensic history of important bugs, failed approaches and the safeguards added because of them. Read this before changing related subsystems.

Last synchronized: 2026-08-29 after confirmed V37 live deployment.

---

## 1. Destructive inventory reset history

Old scripts existed that rebuilt/reset inventory from historical Excel assumptions.

Do not repeat:

- never use `server_inventory_fix.sh` for routine work;
- never rerun old v11 opening snapshot as a current inventory target;
- never apply `server_fix_khorshid_negative_v15.sh` as an isolated fix.

Reason: later sales/production changed state, and the old negative KHORSHID anomaly could not be safely repaired by moving quantity without a full physical count.

---

## 2. Historical Darma negative rows were not all bugs to zero

At one historical audit, negative cells included:

```text
HOME زرد M = -4
HOME قرمز L = -37
HOME قرمز XL = -29
HOME قرمز XXL = -39
HOME قرمز 3XL = -2
KHORSHID طوسی XXL = -50
```

Do not automatically clamp negatives to zero. They may encode historical opening data/shortage/reconcile artifacts.

The correct repair was a full physical HOME + KHORSHID baseline, not individual guesses.

---

## 3. V18 physical baseline superseded the isolated -50 problem

The authoritative physical count after 3 Shahrivar sales became:

```text
HOME=4,585
KHORSHID=8,890
TOTAL=13,475
```

That baseline superseded the old isolated `طوسی/XXL/KHORSHID=-50` forensic issue.

Do not resurrect the old fix as a pending task.

---

## 4. V18 Khorshid red/cream XXL transcription error

Original V18 matrix mistakenly encoded:

```text
KHORSHID کرم XXL = 260
KHORSHID قرمز XXL = 140
```

The physical spreadsheet proved the correct values were:

```text
KHORSHID کرم XXL = 400
KHORSHID قرمز XXL = 0
```

Total quantity stayed unchanged because 140 units were misclassified between colors.

A safe correction V20 was created.

Do not use the original V18 constants without applying this correction.

---

## 5. Anbaresh inventory double-count risk

Anbaresh originally evolved through a phase where it could be misunderstood as an inventory brand.

Final rule:

- sales channel only;
- physical Darma stock;
- no independent capital inventory.

Do not display or value Anbaresh as separate owned stock.

---

## 6. Material report coupling bug history

Earlier material-report versions coupled saving, raw consumption and finished output too tightly and could cause repeated inventory/capital changes.

Final separation:

- Save = data only;
- Apply Materials = raw only;
- Apply Output = finished output + wage only.

Do not recombine them because it looks simpler in UI.

---

## 7. Darma code 06 wrong color

A code 06 source composition accidentally had red where cream should be.

Wrong:

```text
مشکی، سفید، سرمه ای، صورتی، قرمز، طوسی
```

Correct:

```text
مشکی، سفید، سرمه ای، صورتی، کرم، طوسی
```

This can create negative red stock and wrong color reports if reintroduced.

`core/product_catalog.py` source was corrected.

Do not run a broad `sync_catalog()` casually just to fix one composition because it can rewrite many catalog fields. Prefer targeted guarded correction when live data requires it.

---

## 8. Sale reversal versus auto-transfer location history

Sale reversal restores old SaleAllocation to its stored location, commonly HOME. Historical sale application may have auto-transferred KHORSHID -> HOME before deduction.

Therefore reversing later sales can restore correct total quantity but alter HOME/KHORSHID split relative to an earlier physical baseline.

This is why V24 forensic reset reversed post-baseline sales and then hard-restored the exact physical matrix.

Do not assume repeated sale reversals can reconstruct a historical warehouse split perfectly.

---

## 9. V23 Digikala status evolution

Current Digikala reports used status:

```text
اماده ارسال/تحویل
```

Older parser assumptions did not necessarily accept this exact format.

V23 accepts it while blocking negative return/cancel markers.

Do not revert to exact-string-only status logic.

---

## 10. D220 vs rah220 seller-code bug

Real row:

```text
seller_code=rah220
title model=D-220
size=46-48
qty=5
```

Old seller-code-first resolver misclassified it as `rah-220 / 4XL`.

Fix progression:

- V25 attempted title-first;
- residual/compatibility paths still caused wrong behavior;
- V27 made resolver strictly title-only and parser discards seller code entirely.

Do not pass seller code back into product resolver, even as fallback.

---

## 11. V27 brandless model 400 edge case

Strict title resolver initially required explicit brand word and would reject real rows like:

```text
شورت زنانه مدل 400 مجموعه 4 عددی | XL | ...
```

Fix: if brand word absent, resolve only when model uniquely identifies exactly one active import product across Darma/Takvin.

Do not "fix" this by reintroducing seller code.

---

## 12. V27 deployment is not retroactive to already stored SaleLine

After the title resolver was fixed and deployed, the UI could still show old wrong `rah-220 / 4XL` because deployment does not mutate historical SaleLine rows.

Correct action was to re-upload the authoritative same XLSX so replacement semantics zero/reverse the old wrong product-size and apply the corrected D220 target.

Do not interpret a stale row after a resolver deploy as proof that the resolver still fails until the data is reprocessed.

---

## 13. V26 deploy-script Gunicorn hang

A preflight used:

```bash
docker compose run --rm web ...
```

without `--entrypoint python`.

Result: temporary container started Gunicorn and appeared to hang.

Fix:

```bash
docker compose run --rm --entrypoint python web manage.py ...
```

Do not repeat this pattern.

---

## 14. Orphan bot warning is not an error

Repeated warning:

```text
Found orphan containers (darma-general-bot-1)
```

is harmless in this project context.

Do not use `--remove-orphans` unless the user explicitly wants to remove the bot.

---

## 15. V28 elastic 10/10 versus purchase 5/5

User entered elastic purchase:

```text
5 kg variant16
5 kg variant25
```

Display showed:

```text
10 kg variant16
10 kg variant25
```

Diagnostic proved:

- BusinessPayment #6 existed once;
- purchase ledger stored q16=5, q25=5;
- no identical duplicate payment;
- parser/apply code treats variants independently.

Key lesson: aggregate material stock can already contain quantity. The latest purchase note can make all aggregate quantity look like it came from the latest payment.

Do not diagnose duplicate purchasing from display note alone.

---

## 16. Payment delete correctly failed when material was no longer reversible

When user could not delete an elastic/fabric payment, active delete called guarded `_reverse_full` before deleting.

A material purchase may fail reverse if its stock has been transferred/consumed.

Do not bypass this with raw `BusinessPayment.delete()`.

---

## 17. V29 capital audit appeared frozen due to output volume

Audit printed every movement, resulting in hundreds/thousands of terminal lines.

It was not necessarily server/database hang.

Fix: grouped/aggregated diagnostics.

Do not write default diagnostics that dump all historical movements one by one.

---

## 18. Capital discrepancy narrowed correctly before editing

A Shahrivar capital investigation established:

- reported period sale profit matched user calculation exactly: `72,012,896`;
- Digikala difference was negligible (~470 in that audit);
- therefore a ~35.5m discrepancy was not fixed by changing sale profit or Digikala formula.

Lesson: isolate component before correction. Never force capital total.

---

## 19. V30 reset failed safely on fabric purchase reverse

Requested reset attempted to reverse sales/payments/receipts.

It failed while reversing a fabric purchase because ~36.89 kg from that purchase was no longer in warehouse.

Because the command was atomic, **nothing was deleted**.

Do not assume the earlier logged reverse messages persisted.

---

## 20. V30B rebase was a special forensic workaround

To rebuild sales from a known date while user stated current materials were correct, the reset semantics were changed so payment rows could be cleared/rebased while preserving current effects rather than physically reversing already-consumed material.

This is not standard delete behavior.

Never reuse V30B logic as a generic payment-delete path.

---

## 21. V31 31-Mordad inventory baseline

A user workbook for 31 Mordad was used as a historical starting point for debugging.

It contained aggregate Darma totals and even negative cells. Those values were treated as authoritative historical Excel baseline, not "cleaned".

Because the workbook did not split HOME/KHORSHID, the safe baseline preserved KHORSHID and adjusted HOME to make total each color/size equal workbook.

This baseline is historical. Do not apply it over current live inventory after later business activity.

---

## 22. V32 day-3 physical baseline

After re-entering sales through 3 Shahrivar, physical HOME/KHORSHID sheets were reapplied exactly:

```text
HOME=4,585
KHORSHID=8,890
TOTAL=13,475
```

This was an explicit end-of-day physical truth point.

Again: historical checkpoint, not a permanent current-stock target.

---

## 23. V33 Novani S-size isolation

Novani needed size S while Darma must remain M..4XL.

The change was intentionally brand-aware and backend-guarded.

Do not globally add S to all brands or let generic settings create Darma/Takvin S rows.

---

## 24. V33 deploy failed after core check because snapshot script had syntax error

Output reached:

```text
NOVANI MATERIAL V33 CHECK OK
```

then failed reading new-image invariants due a syntax error in deploy snapshot code.

Meaning:

- feature precheck could be correct;
- deployment still not confirmed live because later recreate step had not run.

Fix deploy script and rerun. Do not infer live state from a mid-script success marker.

---

## 25. V33 introduced Novani wage omission

Novani Apply Output was isolated from Darma too aggressively and sewing wage did not apply.

Real block delivered 3,630 pieces. Correct wage at 110,000/dozen:

```text
33,275,000 toman
```

V34 repaired current block and established future wage behavior.

Do not remove wage handling from Novani Apply Output.

---

## 26. Incorrect remembered delivery count 3,160 versus actual 3,630

Initial conversation stated 3,160 delivered, but the actual saved form/movements showed:

```text
710 + 660 + 750 + 700 + 810 = 3,630
```

The repair guard correctly refused expected=3160 found=3630.

Lesson: when a user-stated aggregate conflicts with the authoritative saved row-level form, show the discrepancy before mutating accounting.

---

## 27. Sewing wage rate 100k versus confirmed 110k

An interim repair assumption used 100,000/dozen, but user corrected rule to:

```text
110,000 per 12 pieces
```

Project source default already supported 110,000.

Current handoff rule: 110,000.

Do not use 100,000 in new repairs/calculations.

---

## 28. V35 editable output requirement

User needed to correct an already applied delivery cell by clearing/reducing it.

Old behavior saved the form but did not reverse already-applied stock/wage.

V35/V22 implemented two-way cumulative synchronization:

- target > applied -> add difference + wage difference;
- target < applied -> remove difference + return wage;
- insufficient stock -> atomic failure.

Do not regress to positive-only Apply Output.

---

## 29. V35 reverse-color cut display bug

UI showed cut shortages for:

- برعکس مشکی
- برعکس سفید
- برعکس سرمه‌ای

although those reverse models had no cut rows.

Cause: display mapped them to base black/white/navy cut.

Fix: reverse models map to themselves and therefore zero cut unless dedicated input exists.

Do not borrow base-color cut for reverse models.

---

## 30. V36 inline daily return UI was rejected

An initial return box was added directly into daily report. User explicitly disliked it and requested it removed as if it had never been done.

V37 retires that UI/route and moves returns to a standalone daily-work page.

Do not re-add a large returns box inside daily sales report unless user explicitly reverses this decision.

---

## 31. V36 comprehensive report grouping is UI only

Comprehensive report sections were visually grouped into compact boxes/details while preserving the same data/forms/calculations.

Do not rewrite report data logic just to achieve grouping.

---

## 32. V37 standalone returns design

Final preferred structure:

```text
Sidebar / کار روزانه / مرجوعی
  -> بر اساس رنگ OR بر اساس کد
  -> دارما OR تکوین
  -> size
  -> quantities
```

Effect HOME only; no sale/Digikala/finance side effects.

This is the current accepted design.

---

## 33. V37 calculator design

User wanted to enter new cost and receive a new sale price that preserves the current actual profit percentage for each brand separately while respecting exact Digikala fee rules.

Current V37 implementation:

- calculates current Jalali-month realized metrics per Darma/Takvin from SaleLine + `sale_line_metrics`;
- uses profit/COGS (`profit_on_cost`) as target percentage;
- binary-searches minimum sale price where exact `digikala_fee_for_unit()` leaves target profit;
- rounds suggestion upward to nearest 1,000 toman;
- does not modify fee settings or sales.

Do not convert it to a flat markup that ignores Digikala processing floor/VAT.

---

## 34. V37 confirmed live

Production deployment ended with:

```text
SUCCESS: STANDALONE RETURNS + CALCULATOR V37 DEPLOYED
```

and final invariant snapshot recorded in `08_LIVE_STATE_AND_CHECKPOINTS.md`.

This is the latest confirmed deployment before this context handoff.
