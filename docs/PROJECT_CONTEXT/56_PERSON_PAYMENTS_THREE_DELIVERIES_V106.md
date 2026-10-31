# V106 — PERSON ACCOUNT PAYMENTS + THREE-PART TAILOR DELIVERIES ON THE V105 LINE

## Critical lineage correction

V106 is based on the authoritative V105 line:

`v105-margin-code-summary-material-kpis` @ `3ba8e9084052fac484ee9757b869b1e4bb795fa9`.

A sibling branch named `v102-person-payments-three-deliveries` was accidentally created from the obsolete V101 submenu line. That branch is **not authoritative** and must never be used as a base or deployment target. It reintroduced the Finance submenu that V102/V103 had explicitly superseded.

V106 preserves all V105 behavior, including:
- native direct `مالی و ابزار` sidebar link from V103;
- exactly three Finance hub cards: Payments, Accounts, Calculator;
- V104 Finance KPI source and rebuilt calculator;
- V105 sale-margin semantics, code-level profitability summary, and material-report KPI layout/average-cut KPI.

## Person accounts in Payments

Every active `ExcelManualRow` with section `PERSONS` is offered as a dynamic `پرداخت به` choice.

Semantics:
- selected payment source (Mellat/Mofid) decreases through the existing V62 source-account flow;
- selected person balance decreases by the same amount;
- balance may not go below zero;
- edit reverses the complete old effect first, then applies the edited payment atomically;
- delete restores both source account and person balance atomically;
- a person row referenced by a BusinessPayment cannot be deleted from Finance/Accounts, preserving historical reversibility;
- existing material, tailor, Takvin, self-payment and receipts behavior remains unchanged.

## Three delivery boxes

Only the cells in **محصول تحویلی از خیاط** change.

Each existing size cell contains three small inputs, while the outer table dimensions and columns stay unchanged.

Persistence remains inside existing `MaterialReportBlock.output_data` JSON:
- `_delivery_parts[size]` stores the three values;
- the existing size key stores their SUM;
- all existing target/pending/wage/stock-sync logic continues to use that summed size key;
- no migration is required;
- existing historical single-value sheets render their saved value in box 1 and boxes 2/3 empty.

Cumulative example:
- box1 = 50 -> target 50 -> sync +50;
- then box2 = 70 -> target 120 -> sync only +70;
- then box3 = 50 -> target 170 -> sync only +50.

## Regression

`python manage.py check_person_payments_three_delivery_v106`

Validates transactionally and rolls back:
- person accounts appear in payment choices;
- payment decreases selected bank source and person balance;
- payment edit reverse/reapply works;
- reverse restores both sides;
- 50+70+50 = 170;
- legacy single value maps to box 1;
- sync output adds the summed quantity to finished inventory;
- no persistent business-state write remains.

## Deployment

`bash server_person_payments_three_deliveries_v106.sh`

Expected final marker:

`SUCCESS: V105 RESTORED + PERSON PAYMENTS + THREE DELIVERIES V106 DEPLOYED`

Production is not confirmed from GitHub alone; require PRE = PROJECTED = FINAL and the final marker.
