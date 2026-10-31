# 09 — UI AND USER WORKFLOW CONTRACT

This file captures the user's accepted interaction model and visual constraints. UI work must not change business semantics.

Last synchronized: 2026-08-29 after V39 logo/typography implementation was prepared on GitHub; latest confirmed production remains V38 until successful V39 deployment output.

---

## 1. Visual direction

The accepted interface direction is:

- dark navy background;
- transparent/true-glass cards;
- blur/saturation effects;
- Vazirmatn font;
- orange accent;
- clean operational layout rather than dense ERP styling;
- responsive/mobile support;
- sticky columns/horizontal scrolling for wide operational tables;
- money values displayed with Persian thousands separator `٬`;
- quantities/weights remain practical numeric inputs.

V38 is the confirmed-live global presentation layer and further refines this direction with:

- darker, quieter navy surfaces;
- cleaner glass hierarchy;
- improved sidebar/topbar spacing and active states;
- stronger page/KPI typography;
- cleaner buttons, inputs, tables, badges and alerts;
- improved tablet/mobile spacing;
- reduced-motion accessibility support.

V39 adds the user's Darma logo and establishes a less crowded Persian typography direction. Keep Vazirmatn, but avoid aggressive letter-spacing and unusual synthetic font weights in Persian prose/navigation/tables. Prefer standard weights (400/500/600/700/800), normal Persian spacing and practical line-height. Numeric KPI values may remain stronger and tabular.

Do not regress to opaque old cards, default bootstrap-looking administration screens or Tahoma-heavy legacy styling.

Relevant global files now include:

- `templates/base.html`
- `templates/core/_mobile_shell.html`
- `static/core/ui-polish.css` — V38 global theme;
- `static/core/ui-v39.css` — V39 logo/typography refinement;
- `static/core/darma-logo-v39.webp` — user's Darma logo asset;
- `static/core/number_format.js` — existing formatter/navigation UI + V39 stylesheet loader;
- `static/core/jalali_picker.js`.

---

## 2. Sidebar structure

Current important sidebar intent:

### کار روزانه

Includes operational pages such as:

- dashboard;
- daily sales;
- comprehensive report;
- inventory;
- Takvin purchase;
- material report;
- **standalone returns**.

V37 injects standalone Returns under daily-work navigation using `static/core/number_format.js` without modifying the accounting logic. V38 changes its presentation styling. V39 does not change the navigation structure; it only loads the new presentation stylesheet and displays the Darma logo on the existing home/brand link.

### مالی و ابزار

Includes:

- payments;
- calculator.

### definitions/settings

Product/settings pages remain separate.

---

## 3. Dashboard alert display

User requested dashboard warnings to be visually simplified.

Current display rule:

- Darma only;
- HOME only;
- quantity less than 10;
- exclude red and yellow.

Do not merge this with Telegram alert thresholds. Telegram has different operational rules.

This dashboard change is presentation/query filtering only.

---

## 4. Daily sales report

Current accepted daily report:

- no large inline returns box;
- Darma/Takvin drilldown remains;
- actual allocation colors shown where possible;
- existing price edit/delete actions preserved;
- report remains focused on sales.

The V36 inline return section was explicitly rejected and retired in V37.

Do not place the standalone returns workflow back into the daily sales report unless user explicitly asks.

---

## 5. Standalone returns page V37

User specifically wanted Returns as its own entry under daily work.

First screen should have only two conceptual choices:

- بر اساس رنگ
- بر اساس کد

Then:

- select Darma or Takvin;
- select size;
- enter quantities.

### By color

Show colors belonging to the selected brand and allow loose-short quantities.

### By code

Do not dump all codes across all sizes together.

The user wants size selection first, then all active codes of that brand/size.

For example:

```text
Darma -> M -> all active Darma M codes
```

Each entered number in code mode means complete packs of that code.

### Result

Anything entered adds only to HOME stock of that brand and increases capital through existing inventory valuation.

No other economic flow is created.

---

## 6. Comprehensive report layout V36

User requested a simpler information architecture without rewriting report logic.

Accepted high-level order:

1. existing date/range controls remain in place;
2. top metrics show:
   - total sales;
   - total profit;
   - total shorts;
   - Digikala fee;
3. operational capital/current inventory/accounts section remains visible in its existing form;
4. remaining large sections become compact clickable boxes.

Compact sections:

### گزارش

Contains existing reporting details such as:

- Takvin sales by size;
- Darma sales by size;
- Anbaresh reporting;
- Darma product profitability;
- Darma color sales;
- existing related sales report details.

### حساب‌ها

Contains existing financial/account/person rows. User wanted the name "حساب‌ها" rather than a generic financial-tools label.

### مواد اولیه و موجودی

Contains existing raw fabric/elastic inventory UI and forms.

### کالای سرمایه‌ای

Contains existing asset rows/forms.

Important implementation principle used in V36 and preserved by V38/V39:

- move/reparent or style existing rendered elements visually;
- keep forms/routes/calculation contexts intact;
- avoid rebuilding finance/material logic just for grouping or cosmetics.

---

## 7. Material-report table UI

Current accepted output table behavior for both Darma and Novani:

- no delivery-date column;
- sizes appropriate to brand;
- show model/color;
- show delivered quantities;
- show row total;
- show cut quantity;
- show difference versus cut;
- shortage displayed red;
- surplus displayed green;
- grand delivered total displayed below section.

The user must be able to edit/clear a previously applied delivery cell and then synchronize it so stock/wage reverse appropriately.

Do not make the cell visually editable while backend remains positive-only.

V38/V39 may improve table typography/surface visually but must not change these semantics.

---

## 8. Novani/Darma material-report UI separation

When brand=Novani:

- size columns S through 3XL;
- output adds to Novani only.

When brand=Darma:

- size columns M through 4XL;
- existing Darma production semantics remain.

The UI must reflect brand-specific size sets without modifying the other brand's backend sizes.

---

## 9. Calculator V37

The existing calculator still supports direct:

```text
sale price + cost -> fee/profit/margins
```

V37 adds a second use case:

```text
brand + new cost -> sale price needed to preserve current realized margin
```

Brand choices:

- Darma;
- Takvin.

The result should clearly show:

- current realized profit percentage basis;
- new cost;
- mathematical minimum sale price;
- suggested rounded sale price;
- exact Digikala fee at suggested price;
- resulting net profit;
- resulting profit-on-cost and profit-on-sale.

Do not hide the fee or present a gross markup-only number.

V38/V39 change appearance only; calculator formulas remain V37.

---

## 10. User prefers direct operational outputs

When implementation is done, give commands like:

```bash
cd /opt/darma-general
git pull --ff-only
bash server_<feature>.sh
```

Do not make the user manually edit Python files on the VPS if GitHub editing is available.

When a command fails, interpret the exact output and give the next exact command.

---

## 11. Avoid unnecessary confirmation loops

If the repo/context already contains the required business fact, use it.

Examples:

- sewing wage is 110,000/dozen;
- Novani sizes are known;
- Darma/Takvin size sets are known;
- V37 return structure is known;
- capital equation is known.

Ask only when a genuinely new business decision is needed.

---

## 12. Do not overcomplicate one-product workflows

The application exists because the user wants faster operational entry than Excel, not more steps than Excel.

Prefer:

- clear progressive choice screens;
- compact cards;
- visible totals;
- safe bulk entry;
- few clicks;
- backend guards hidden from the user unless something is wrong.

Avoid:

- giant all-code tables before selecting brand/size;
- generic ERP terminology where the user's own labels exist;
- exposing internal IDs/ledger concepts in normal UI.

---

## 13. Jalali dates

Business workflows use Jalali dates. Do not replace date entry with Gregorian-only UI.

Global date picker behavior and existing formats should be preserved unless explicitly redesigned.

---

## 14. Mobile behavior

Mobile shell includes bottom nav and responsive styling.

Any new large table must:

- allow horizontal scroll;
- preserve readable input sizes;
- avoid forcing body-level horizontal overflow;
- keep action buttons reachable;
- use existing mobile shell rather than creating a second mobile navigation system.

V38 responsive refinements remain the live baseline; V39 only adjusts typography and sidebar branding responsively.

---

## 15. UI-only work safety test

Before deploying a cosmetic/reorganization change, compare business invariants before and after:

```text
capital
finished inventory
raw materials
Digikala receivable
Darma/Takvin/Novani qty
SaleLine count
AccountEntry count
```

If a cosmetic deployment changes one of these, treat it as a bug.

V38 confirmed this discipline in production. V39 uses the same exact invariant discipline.

---

## 16. Standing documentation rule

After every important UI/workflow change, update the relevant context-pack files.

After every successful deployment confirmed by server output, also update `08_LIVE_STATE_AND_CHECKPOINTS.md` using the actual final production snapshot. Never copy an older checkpoint forward merely because the code change was cosmetic.

---

## 17. V39 logo + typography contract

The user's Darma logo is now the preferred site-brand artwork for the sidebar brand/home link. Do not revert to the old orange `D` visual unless the user explicitly requests it.

For Persian text, the user's accepted direction is now: modern Vazirmatn, but **not visually crowded**. Avoid excessive negative/positive letter-spacing, synthetic intermediate weights such as 650/750, and unnecessary 900-weight prose. Keep headings clear, normal text calmer, tables readable, and numeric KPIs strong but not blurry.

This contract is presentation-only and must never be used as justification to alter a value, formula, data source, route or business workflow.
