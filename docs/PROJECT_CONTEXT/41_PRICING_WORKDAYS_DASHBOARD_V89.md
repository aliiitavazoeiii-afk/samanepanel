# V89 — WORKING-DAY PRICING COMPARISON + DASHBOARD CLEANUP

Prepared: 2026-09-25
Updated: 2026-09-26

## Scope

V89 is additive/read-only for business data. It changes pricing-monitor comparison semantics and dashboard presentation only. It does not change sales, accounting, inventory, receivable, payments, SaleSnapshot, cost rules, price rules or capital formulas.

Active routes after V89:

- `/` -> `core.excel_dashboard_v89.dashboard`
- `/pricing-monitor/` -> `core.pricing_monitor_v89.pricing_monitor`
- `/pricing-monitor/export/xlsx/` -> `core.pricing_export_v89.pricing_monitor_xlsx`

## Working-day definition

For the Darma pricing monitor, a business working day is a date that contains at least one positive Darma `SaleLine`.

This definition is intentionally derived from the user's real recorded Darma business activity rather than an external holiday calendar.

Consequences:

- a holiday / date with no positive Darma sale is not shown as a zero-sales daily comparison;
- if the selected date is the 3rd Darma working day of the current Jalali month, it is compared with the 3rd Darma working day of the previous Jalali month;
- if the previous month does not contain that many working days, daily comparison is unavailable rather than fabricated;
- today's raw values may still be shown if today is a working day, but daily percentage deltas remain provisional while today is incomplete.

## Cumulative comparison

Month-to-date comparison is now workday-aligned.

For current completed Darma working days `1..N`, V89 compares them with previous-month Darma working days `1..N`.

If today is incomplete, today is excluded from cumulative comparison exactly as before.

Charts use workday ordinal labels (`1`, `2`, `3`, ...) instead of calendar day numbers.

## 10-working-day price evaluation

V88's 10-day evaluation is replaced on the active V89 route by a 10-working-day evaluation.

For the latest effective price rule of each Darma code/size:

- the price-rule date itself remains excluded because V60 stores only date precision, not wall-clock activation time;
- up to 10 completed Darma working days after the price date are evaluated;
- each working day is compared with the same working-day ordinal in the previous Jalali month;
- all economics still come from `sale_line_metrics()` / historical `SaleSnapshot`;
- adjusted previous profit still recomputes only previous-period COGS using the current Darma accounting cost;
- no price is changed automatically.

Status logic remains descriptive. The positive status string is:

`نشانه مثبت؛ نرخ تبدیل نامشخص`

The V89 template now correctly renders this positive status with the positive/green badge style.

## Pricing-table layout fix

Both the dashboard pricing summary and the full pricing report now use explicit fixed horizontal table behavior:

- header and body cells use `white-space: nowrap`;
- cells are vertically and horizontally aligned;
- wide tables have explicit minimum widths;
- table containers scroll horizontally instead of wrapping headings/data into mismatched rows;
- the product key column remains visually stable in the full report.

This fixes the V88 UI mismatch where headings and numeric values could appear visually out of alignment.

## Dashboard changes

The dashboard warning panel is removed from the V89 dashboard.

The sales/profit chart changes from the latest 14 recorded-sale dates to the latest 30 recorded-sale dates.

As in V88, empty/holiday dates are omitted; the chart is a sequence of actual recorded sale dates, not 30 calendar dates containing zero placeholders.

The chart is full-width and horizontally scrollable on narrow screens so all 30 dates remain inspectable.

Above this chart V89 now shows three averages derived from exactly the same displayed sale-day population:

- average daily gross sales;
- average daily profit;
- average shorts sold per sale day.

The denominator is `chart_day_count`, not a hard-coded 30. Therefore if only 23 recorded sale dates are available, all three averages are divided by 23. Holiday/empty dates never dilute these averages.

The shorts average includes both ordinary `SaleLine` shorts and Dia Gallery quantities, matching the chart's existing inclusion of Dia Gallery gross/profit.

## Accounting / inventory safety

V89 does not modify:

- `SaleLine` or `SaleSnapshot`;
- stock or inventory movements;
- Digikala/Dia receivables;
- payment or receipt ledgers;
- Darma/Takvin/Novani cost rules;
- V60 sale-price rules;
- capital history or current capital formulas.

V88 remains in source as the formula/helper base; V89 layers workday selection and new UI routes on top of it.

## Regression

Run:

```bash
python manage.py check_pricing_monitor_v89
```

Expected marker:

```text
SUCCESS: PRICING WORKDAYS + DASHBOARD V89 CHECK PASSED
```

The regression is read-only and verifies:

- active V89 routes;
- V89 templates compile;
- dashboard alert block is absent;
- 30-sale-day marker is present;
- the three 30-sale-day average KPI cards are present in source and rendered HTML;
- pricing table alignment guard exists;
- positive evaluation status text is current;
- working-day detection and ordinal mapping;
- non-working dates cannot produce daily comparison rows;
- V89 XLSX integrity and working-day sheets;
- SaleLine/AppSetting row counts remain unchanged.

## Deployment

No migration is required.

Use:

```bash
bash server_pricing_workdays_dashboard_v89.sh
```

The deploy script must preserve the pre-deploy business snapshot exactly because this release is report/UI-only.

Expected final marker:

```text
SUCCESS: PRICING WORKDAYS + DASHBOARD V89 DEPLOYED
```

Do not call V89 production-confirmed until the user posts the actual VPS success marker/output.
