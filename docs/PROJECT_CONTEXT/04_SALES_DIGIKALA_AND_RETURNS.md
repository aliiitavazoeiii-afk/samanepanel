# 04 — SALES, DIGIKALA IMPORT AND RETURNS

This file records the current sales/import/returns behavior and the exact bug history that shaped it.

Last synchronized: 2026-08-29 after confirmed V37 live deployment.

---

## 1. Daily sales architecture

A SaleDay represents a business date. SaleLine rows represent product-size quantities sold on that date.

Main entry paths:

- manual brand/size sale entry;
- Digikala XLSX authoritative replacement for Darma/Takvin lines;
- manual Anbaresh sales on same date;
- later price edit/delete from daily report.

Daily report must show the actual physical colors allocated when available, not blindly recompute from today's product composition.

---

## 2. Manual Darma/Takvin sales

Active manual save route:

```text
/sales/save/ -> core.excel_sales.sale_line_save
```

Inventory sync relies on current sale inventory services and must be atomic.

For a normal fixed-composition product:

- SaleLine quantity is packs/items at product-code level;
- physical shorts = quantity * pack_qty;
- inventory allocation stores the actual color/location quantities deducted;
- snapshot freezes accounting basis;
- Digikala receivable is synchronized from sale economics.

Do not bypass the existing inventory sync by directly decrementing StockBalance from UI code.

---

## 3. Anbaresh manual sales coexist with Digikala

Anbaresh is manual sales only and physically consumes Darma stock.

Critical same-day rule:

A date can contain both:

- Digikala Darma/Takvin XLSX lines;
- manual Anbaresh SaleLines.

When an XLSX is uploaded/re-uploaded, it is authoritative only for Darma/Takvin. Existing Anbaresh lines on the same SaleDay must remain untouched.

Current V23 import does this by filtering existing replacement lines to the import brands only.

Never broaden XLSX replacement to all SaleLines on the day.

---

## 4. Digikala XLSX web wrapper

Active web route:

```text
/sales/<day_id>/import-xlsx/ -> core.daily_order_views_v8.import_daily_orders
```

The wrapper:

1. requires XLSX;
2. captures Darma/Takvin stock totals before;
3. captures already-applied sold shorts for the day before;
4. calls V23 `apply_delivery_report`;
5. captures stock/applied totals after;
6. verifies actual brand stock delta exactly equals old-applied minus new-applied;
7. synchronizes receivable for every day SaleLine;
8. entire request is atomic; any mismatch rolls back.

This brand-total invariant is a key guard against silent wrong inventory application.

---

## 5. V23 Digikala parser

Active parser/apply module:

`core/daily_order_import_v23.py`

It uses the first XLSX worksheet via the production ZIP/XML reader inherited from older importer code. It does not rely on pandas/openpyxl in the production request path.

Required columns include:

- `عنوان`
- `تعداد ارسالی`

The current common Digikala delivery report also has:

- `کد تنوع`
- `کد فروشنده`
- `وضعیت`
- other quantity/status columns.

### Seller code is intentionally discarded

V23 explicitly sets parsed `seller_code=""`.

This is a critical post-bug rule: **product identity must come from title text, not Digikala seller-code metadata**.

Do not reintroduce seller-code precedence.

---

## 6. Delivery-status acceptance

V23 normalizes status text and rejects negative/return/cancel markers first.

Negative markers include compact forms of:

- مرجوع
- برگشت
- لغو
- کنسل
- عدم تحویل
- عدم ارسال
- ناموفق
- رد شده

Accepted positive cases include:

- blank legacy status;
- status containing `دریافت`;
- status containing `ارسال/تحویل`;
- current Digikala status containing all of `اماده`, `ارسال`, `تحویل`, e.g. `اماده ارسال/تحویل`.

A negative marker wins even if other positive words appear.

---

## 7. Blocked known return file

Historical file:

```text
packageDeliveryReport_17851669002377.xlsx
```

is known to be a return-only report and must never be imported as daily sales.

The importer has a blocked-return filename mechanism. Do not remove it casually.

---

## 8. Strict title-first resolver V27

Canonical product identity resolver:

`core/title_product_resolver_v27.py`

Rule:

- Digikala seller code must not participate.
- Extract model text from the title after `مدل` and before `مجموعه` or `|`.
- If title explicitly names Darma/Takvin, resolve only within that brand.
- If title omits the brand word, accept only a unique active model match across Darma/Takvin.
- Unknown/ambiguous model fails closed.

### Darma title aliases

Important aliases include:

```text
d110 -> D 110
d220 -> D 220
d330 -> D 330
d440 -> D 440
d550 -> D 550
d660 -> D 660
110 -> D 110
220 -> D 220
...
pack5 / pack05 -> pack 5
rah110 -> rah-110
rah220 -> rah-220
op / opbnw -> op
06 / 6 / pack6 -> 06
770 / 880 / 990 / 400 / p12 / pgw / s3 -> canonical same code
```

### Takvin title alias

Digikala model text:

```text
1-654
```

compacts to `1654` and maps to canonical internal:

```text
654-1
```

### Brandless model 400

Real Digikala titles can say:

```text
شورت زنانه مدل 400 مجموعه 4 عددی | XL | ...
```

without `دارما` in the title. Resolver accepts it only because `400` uniquely identifies one active import product across Darma/Takvin.

Do not solve brandless rows using seller code.

---

## 9. D-220 versus rah-220 bug history

This is one of the most important import bugs not to repeat.

A real Digikala XLSX row had:

```text
seller code: rah220
title: شورت زنانه دارما مدل D-220 مجموعه 3 عددی | 46-48 | ...
quantity sent: 5
status: اماده ارسال/تحویل
```

Old resolver used seller code first and incorrectly mapped this row to:

```text
rah-220 / 4XL
```

That caused 5 packs = 15 physical shorts to hit the wrong composition/colors.

Correct title meaning:

```text
D 220 / 4XL / quantity 5 packs
```

D 220 composition:

- سفید x1
- صورتی x1
- کرم x1

Expected physical allocation for qty 5:

- سفید +/sold 5
- صورتی 5
- کرم 5

`rah-220` composition is different:

- راه راه طوسی x1
- سفید x1
- طوسی x1

Therefore confusing these products visibly corrupts color inventory.

V27 permanently made title authoritative and discarded seller code at parse time.

---

## 10. Current audited example delivery file

The file used during the D220 investigation was:

```text
packageDeliveryReport_17879799790955.xlsx
```

Properties observed at that time:

- first sheet A1:G69;
- 68 data rows;
- total sent quantity = 175;
- all positive statuses `اماده ارسال/تحویل`.

Specific expected rows:

### pack 5 / 4XL

Total target packs = 4 from two title rows:

- explicit 4XL qty2;
- 46-48 qty2.

### D220 / 4XL

Target packs = 5 from the contradictory seller-code/title row described above.

### legitimate rah220

Only:

- 3XL qty2
- M qty1
- XL qty1

There was no legitimate rah220 4XL title row.

After correct re-import, a ghost old rah220 4XL SaleLine must be zeroed/reversed by authoritative replacement semantics.

---

## 11. XLSX replacement semantics

For Darma/Takvin, the uploaded file is authoritative for that SaleDay.

V23 builds target quantity by ProductSize and then iterates:

```text
existing Darma/Takvin product-size lines UNION target product-size lines
```

For an existing line omitted from the new file:

```text
new quantity = 0
```

Then inventory sync reverses previous SaleAllocation and sets applied quantity accordingly.

This is why re-uploading the same corrected file can remove a previously wrong product-size line without manual database deletion.

Do not change XLSX import into additive-only behavior.

---

## 12. Sale inventory reversal behavior

`sync_sale_inventory` in `core/final_services.py` first restores old SaleAllocation quantities to their stored location and deletes old allocation/shortage records before applying the new quantity.

Important consequences:

- setting sale quantity to zero restores the previously allocated physical shorts;
- reversal uses historical allocation records, so it is not dependent on today's ProductComposition;
- if product composition changed since the sale, existing allocation can still be restored correctly.

However, historical auto-transfer HOME/KHORSHID mechanics can mean location distribution after a reversal is not identical to a full earlier physical baseline. This is why exact physical baseline resets were used for forensic cleanup when required.

---

## 13. Daily report color source

Active daily report uses `SaleAllocation` as authoritative actual physical color breakdown.

For a line with allocations:

- group allocations by color;
- include replacement quantities;
- display actual allocated color totals.

Only for older lines with no allocations does it fall back to current ProductComposition and mark the source as composition/inferred.

Do not replace allocation-first reporting with composition-only reporting.

---

## 14. Daily sale line price edit V21

Price edit is designed to be accounting-safe:

- changes sale price;
- updates Digikala fee/receivable economics;
- preserves historical/physical COGS and inventory allocation;
- does not resell/re-deduct inventory.

Inspect `core/daily_report_actions_v21.py` before modifying.

---

## 15. Daily sale line delete V21

Delete flow sets quantity to zero and uses sale inventory sync to restore the sale's physical allocations, then synchronizes receivable/removes line according to current implementation.

Do not raw-delete SaleLine without reversal.

---

## 16. Darma variable-color s3

Darma code `s3` is pack-1 with no fixed ProductComposition for import purposes. The sold color is resolved per title row.

Known case-sensitive hints/history:

```text
s2 = کرم
s3 = مشکی
S3 = صورتی
s5 = سرمه‌ای
```

White can also be recognized from title text.

Important: lowercase `s3` and uppercase `S3` are not the same color hint.

Title remains authoritative; seller code must not override the title/product identity rule.

Variable-color sales use `core/variant_sale_v12.py` rather than normal fixed-composition sync.

---

## 17. Darma code 06 composition

Current source composition was corrected after a real bug:

```text
مشکی
سفید
سرمه ای
صورتی
کرم
طوسی
```

The erroneous earlier source had `قرمز` where `کرم` should be.

Do not reintroduce red into code 06.

Code 06 and `pack6` represent the same Darma product concept; historical processing should not create a separate pack6 product row.

---

## 18. Shortage behavior

The current sale inventory service can create shortages if stock is insufficient. Historically, a shortage path could still drive a stock row negative while recording shortage metadata.

Therefore importer guards compare total expected versus actual brand stock changes and shortage warnings are surfaced.

Do not hide negative/shortage behavior by silently clamping stock to zero; that would break accounting and forensic traceability.

---

## 19. Standalone return V37

Active page:

```text
/returns/
```

It is intentionally separate from sales.

### Mode A — by color

Flow:

```text
color mode -> Darma/Takvin -> size -> color quantities
```

Each positive quantity creates a positive `InventoryAdjustment` at HOME for selected brand/size/color.

### Mode B — by code

Flow:

```text
code mode -> Darma/Takvin -> size -> code pack quantities
```

The page only shows active ProductSize rows for that brand/size.

For each entered pack quantity:

1. require fixed ProductComposition;
2. multiply each component qty by entered packs;
3. create HOME positive adjustment for each component color;
4. verify summed component units equals `packs * pack_qty`;
5. atomic rollback on mismatch.

Variable-color/non-fixed codes must be returned by color.

### What return must never do

- no SaleLine;
- no SaleSnapshot;
- no Digikala fee;
- no receivable movement;
- no AccountEntry;
- no raw-material movement;
- no cash movement.

Finished inventory/capital increases only because owned stock increased.

---

## 20. Return regression test

`core/management/commands/check_returns_calculator_v37.py` checks:

- `/returns/` and `/returns/apply/` route to V37;
- old daily return route no longer resolves;
- template load;
- rollback stock adjustment changes only HOME/value during transaction;
- no Digikala/finance/sale side effects;
- outer rollback restores all data.

Future changes to returns should extend this test rather than bypass it.

---

## 21. What to inspect before changing any sales/import issue

Minimum reading list:

1. `core/urls.py`
2. `core/daily_order_views_v8.py`
3. `core/daily_order_import_v23.py`
4. `core/daily_order_import_v12.py`
5. `core/title_product_resolver_v27.py`
6. `core/variant_sale_v12.py`
7. `core/final_services.py`
8. `core/cost_accounting_v14.py`
9. `core/finance.py`
10. `core/finance_excel_v9.py`
11. `core/daily_report_v8.py`
12. `core/daily_report_actions_v21.py`
13. `core/returns_v37.py` if task concerns returns

Do not diagnose a wrong color/model using only the UI label; inspect the original XLSX title, SaleLine, ProductSize, SaleAllocation and current resolver path.
