# 01 — BUSINESS RULES AND INVARIANTS

This file defines the business semantics that a new AI/chat must treat as authoritative unless the user explicitly changes a rule.

Last synchronized: 2026-08-29 after confirmed V37 live deployment.

---

## 1. Purpose of the application

DARMA General is a custom Django application that replaces the user's operational Excel workbook. It is intentionally not a generic ERP. Its purpose is to preserve the user's exact business/accounting workflow while making daily entry, inventory, production, payments and reports easier and safer.

Main domains:

- daily sales entry;
- Digikala XLSX import;
- Darma/Takvin product catalog and pricing;
- Darma HOME/KHORSHID finished stock;
- Takvin stock;
- Novani production/finished stock;
- Anbaresh manual sales backed by Darma physical inventory;
- raw fabric/elastic inventory;
- tailor/depot/warehouse material flows;
- material/production reports;
- payments, prepayments and Digikala receipts;
- capital reporting;
- standalone returns;
- pricing/profit calculator;
- Telegram inventory alerts.

---

## 2. Absolute safety invariant

Do not change an accounting or inventory rule just because a UI task seems easier if implemented that way.

For UI-only requests, the following are frozen:

- capital equation;
- sale profit equation;
- Digikala fee engine;
- sale receivable logic;
- SaleSnapshot historical values;
- finished inventory valuation;
- raw-material valuation;
- BusinessPayment behavior;
- material consumption rules;
- production output rules;
- stock transfer semantics;
- daily XLSX replacement semantics;
- brand/location ownership rules.

If a requested UI change would require changing one of these, stop and explain the dependency rather than silently changing it.

---

## 3. Brand semantics

### 3.1 Darma (`دارما`)

- Real finished-goods inventory brand.
- Physical locations: HOME and KHORSHID.
- Most daily Digikala sales come from Darma.
- Darma manual/production flows must preserve HOME/KHORSHID semantics.
- Material-report production output for Darma goes to KHORSHID.
- Darma inventory contributes to finished inventory and capital.
- Current base accounting cost for normal Darma shorts is 61,000 toman unless an active per-cell/model cost rule in the valuation system says otherwise.

### 3.2 Takvin (`تکوین`)

- Real inventory and daily-sale brand.
- Active size set: M, L, XL, XXL.
- Takvin accounting cost is date-effective for sales via `TakvinCostRule` and SaleSnapshot. Do not recalculate historical sales using a new cost rule.
- Takvin inventory contributes to capital.
- Takvin debt is a liability subtracted from capital.

### 3.3 Novani (`Novani`)

- Real production/inventory brand.
- Not a Digikala daily-sale brand in the current workflow.
- Uses one visible inventory bucket; internally HOME is used as that bucket.
- No visible HOME/KHORSHID split.
- Current material-report sizes: S, M, L, XL, XXL, 3XL.
- Material-report output applies directly to Novani inventory.
- Novani output must never touch Darma stock.
- Novani inventory contributes to finished inventory/capital.

### 3.4 Anbaresh (`انبارش`)

- SALES CHANNEL ONLY.
- Not an independent inventory asset.
- Manual Anbaresh SaleLines remain labeled brand=Anbaresh for reporting.
- Physical stock is deducted from real Darma inventory.
- Anbaresh catalog mirrors Darma for sale entry but must not create double inventory value.
- Never include Anbaresh StockBalance as an independent capital asset.
- Digikala XLSX does not target Anbaresh; manual Anbaresh lines on the same day must survive XLSX replacement.

---

## 4. Location semantics

### Darma

- HOME = home/current fulfillment stock.
- KHORSHID = warehouse stock.
- Existing sale inventory logic may auto-transfer KHORSHID -> HOME to satisfy sales.
- Internal transfer changes location only; total quantity/value/capital should not change.

### Novani

- One logical bucket, internally HOME.
- Never invent a KHORSHID split for Novani.

### Standalone returns V37

- Always add positive inventory to HOME of the selected brand.
- Do not create sale/finance/Digikala movements.

### Material-report output

- Darma -> KHORSHID.
- Novani -> Novani single HOME bucket.

---

## 5. Size contracts

### Darma finished goods / sales

- M
- L
- XL
- XXL
- 3XL
- 4XL

Darma must not accept S in sales/inventory operations.

### Takvin

- M
- L
- XL
- XXL

Takvin must not accept S/3XL/4XL in current workflow.

### Novani material-report output

- S
- M
- L
- XL
- XXL
- 3XL

This difference is intentional and must not mutate Darma size configuration.

Digikala title size aliases used by import:

- 36-38 -> M
- 38-40 -> L
- 40-42 -> XL
- 42-44 -> XXL
- 44-46 -> 3XL
- 46-48 -> 4XL

---

## 6. Sale semantics

A normal sale changes business state in two coupled directions:

1. finished inventory decreases by COGS quantity/value;
2. Digikala receivable increases by gross minus Digikala fee.

Therefore capital increases exactly by sale profit, subject to frozen sale snapshot values.

A sale must not be represented as a direct cash receipt unless an explicit Digikala settlement is later entered.

---

## 7. Historical SaleSnapshot is immutable history

`SaleSnapshot` freezes sale-time accounting inputs such as:

- pack quantity;
- accounting unit cost/COGS basis;
- Digikala fee unit;
- other sale-time values used by reporting.

If current costs, compositions or fee settings change later, old snapshots are not rewritten.

Reason: historical profit and capital movement must remain the values that actually applied at sale time.

---

## 8. Returns semantics V37

The active standalone returns workflow is `/returns/`.

Two modes only:

1. **By color** = loose shorts.
2. **By code** = complete fixed-composition packs.

Flow:

mode -> brand (Darma/Takvin) -> size -> quantities.

Effect:

- positive HOME inventory adjustment only;
- finished inventory value increases through the existing valuation engine;
- capital consequently increases by the added inventory value;
- no SaleLine;
- no SaleSnapshot;
- no Digikala fee;
- no Digikala receivable change;
- no AccountEntry;
- no raw material change;
- no bank/cash change.

For code mode, active ProductSize/ProductComposition is source of truth. A variable-color code without fixed composition must be entered by color, not guessed as a pack composition.

The old returns box inside daily sales report was explicitly retired in V37 and must not be reintroduced unless requested.

---

## 9. Raw-material business rule

Raw materials are owned assets and contribute to capital.

Fabric and elastic may exist in:

- warehouse;
- tailor;
- fabric depot where supported.

Internal movement between owned locations must not change total raw-material value/capital.

Material-report workflow deliberately separates three actions:

1. Save data.
2. Apply/synchronize raw-material consumption.
3. Apply/synchronize finished-goods delivery/output.

Do not recouple them.

---

## 10. Sewing wage rule

Current confirmed sewing-wage setting for the discussed Darma/Novani material flow:

**110,000 toman per dozen (12 delivered pieces).**

Wage is based on actual cumulative delivered pieces, not cut quantity.

For editable material-report delivery:

- increasing delivered pieces deducts only wage for the positive delivery delta;
- reducing/removing previously applied delivered pieces returns wage for the negative delta;
- cut quantity never directly generates sewing wage.

The system uses cumulative wage-piece ledgers to prevent double application.

---

## 11. Cut vs delivered semantics

Material report shows cut quantity as comparison context only.

- Cut is taken from input/raw-production data.
- Delivered is actual finished output entered by model/color and size.
- shortage = delivered < cut;
- surplus = delivered > cut.
- reverse-color models (`reverse_black`, `reverse_white`, `reverse_navy`) do **not** borrow the cut count of their base color. Their cut comparator remains zero unless an explicit dedicated cut source is later added.

This is display/business comparison and must not alter inventory by itself.

---

## 12. Daily dashboard alert rule

Current requested dashboard alert display:

- Darma only;
- HOME stock only;
- display cells with quantity < 10;
- exclude red (`قرمز`) and yellow (`زرد`) from dashboard alert display.

This is a display/query rule. It must not change Telegram production/transfer alert rules unless separately requested.

---

## 13. Telegram inventory alert rule V20

Separate from the dashboard display:

- HOME target per Darma color x size: do not remain below 30 when KHORSHID can replenish.
- If HOME < 30 and KHORSHID has stock, suggest transfer to bring HOME to 30.
- If TOTAL HOME+KHORSHID <= 60, production warning.
- automatic alert once after daily report for sale date;
- automatic daily alert once at 09:00 Asia/Tehran;
- no minutely/continuous repeated notifications;
- manual current-alert command is available in the Telegram bot;
- transfer operations must preserve total stock/capital.

Do not confuse this with the dashboard's newer `<10, no red/yellow` visual rule.

---

## 14. User interaction/implementation expectations

- User generally wants direct GitHub implementation, not tutorial-style code fragments.
- After implementation, give short copy/paste VPS commands.
- Never ask for facts already present in repo/context.
- When server output fails at a guard, diagnose the exact guard; never tell the user to bypass safeguards.
- Do not claim a deployment is live until successful server output is shown.
- The user values exact accounting over cosmetic convenience.
- Money display generally uses Persian thousands separator `٬`.
- Quantity/weight can use normal decimal representation.

---

## 15. Current UI direction

The UI is dark navy / true-glass / Vazirmatn / orange-accented. Keep it simple and operational, not enterprise-ERP-heavy.

The current comprehensive report V36 groups existing content visually while keeping calculations/forms intact.

Current standalone returns V37 belongs under `کار روزانه` in the right sidebar.
