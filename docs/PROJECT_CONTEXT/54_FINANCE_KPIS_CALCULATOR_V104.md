# V104 — FINANCE KPIs + CALCULATOR REBUILD

Prepared: 2026-10-01  
Branch: `v104-finance-kpis-calculator`  
Base: production-confirmed V103 `e65af89816dd32d7db4fe36dc9518afca71eb21b`

## User requirements

1. Improve the two read-only summary cards on Finance -> Accounts:
   - حساب بانک و اشخاص
   - طلب Dia Gallery

   Their numbers must be larger, aligned cleanly and separated from the unit text.

2. Show the exact same six balances that appear on Payments at the top of Finance & Tools:
   - موجودی ملت
   - موجودی مفید
   - طلب دیجی‌کالا
   - طلب Dia Gallery
   - حساب خیاط
   - بدهی تکوین

3. Keep the Finance hub itself at exactly three navigation cards:
   - پرداخت‌ها
   - حساب‌ها
   - محاسبه‌گر

4. Remove the old calculator structure and replace it with:
   - finished-cost + desired profit percentage -> required sale price after real Digikala fees;
   - sale price + finished cost -> net toman profit + profit percentages;
   - a live profitability table for every active Darma and Takvin ProductSize.

## Shared Finance KPI source

New read-only helper:

`core.finance_overview_v104.finance_kpis()`

Both Payments and Finance home consume this exact helper.

It reads the same underlying sources already used by Payments:

- Mellat: `business_tools_v21.mellat_balance()`
- Mofid: `payment_source_v63.source_balance(SOURCE_MOFID)`
- Digikala receivable: `finance_excel_v9.digikala_receivable_total()`
- Dia Gallery receivable: `dia_gallery_v45.dia_gallery_receivable_total()`
- Tailor: `business_tools_v21.tailor_balance()`
- Takvin debt: current `ExcelManualSetting(key="takvin_debt")`

No new balance, ledger or accounting formula is introduced.

The same template partial is rendered in both locations:

`templates/core/_finance_kpis_v104.html`

## Calculator target-profit semantics

The user-entered target percentage explicitly means:

```text
target profit percent = net profit / finished cost * 100
```

The calculator solves for the minimum whole-toman sale price such that:

```text
sale price
- canonical Digikala fee
- finished cost
>= desired net profit
```

The Digikala fee comes only from:

`core.finance.digikala_fee_for_unit()`

The practical displayed recommendation is rounded upward to the next 1,000 toman. The exact minimum mathematical price is also shown.

## Normal profit calculator

Inputs:

- sale price
- finished cost

Outputs:

- canonical Digikala fee
- net toman profit
- net profit / finished cost
- net profit / sale price

Formula:

```text
net profit = sale price - Digikala fee - finished cost
```

## Live Darma/Takvin profitability table

Rows include every active `ProductSize` for active Darma and Takvin products.

For each row:

```text
current sale price = sale_price_for(product_size, today)
pack quantity       = ProductCode.pack_qty
```

Darma:

```text
unit cost     = darma_cost_for(today)
finished cost = pack quantity * unit cost
```

Takvin:

```text
unit cost     = takvin_cost_for(size, today)
finished cost = pack quantity * unit cost
```

Then:

```text
fee            = digikala_fee_for_unit(current sale price, today)
net profit     = sale price - fee - finished cost
profit on cost = net profit / finished cost * 100
sale margin    = net profit / sale price * 100
```

This is read-only. It does not modify sale-price rules, ProductSize defaults, SaleLine rows, SaleSnapshots, inventory or accounts.

Future scheduled prices are not treated as current selling prices. The table uses the price effective **today**.

## Regression

Run:

`python manage.py check_finance_calculator_v104`

It verifies:

- Finance and Payments both render the same six KPI categories;
- Finance still has exactly three navigation cards;
- Accounts uses the V104 summary-card presentation;
- legacy calculator structure is absent;
- the target-price solver is minimal and reaches the requested profit after the canonical fee;
- every active Darma/Takvin ProductSize is covered;
- each row's current sale price, cost, fee and profit equal an independent recomputation from canonical sources;
- no business state changes.

Expected marker:

`SUCCESS: FINANCE KPI + CALCULATOR V104 CHECK PASSED`

## Rollback

Rollback ref:

`before-finance-kpis-calculator-v104-20261001`

## Deployment

Use:

`bash server_finance_calculator_v104.sh`

Expected final marker:

`SUCCESS: FINANCE KPI + CALCULATOR V104 DEPLOYED`

GitHub state alone is not production confirmation.
