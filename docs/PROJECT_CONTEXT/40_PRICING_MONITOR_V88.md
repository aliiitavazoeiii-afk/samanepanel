# V88 — DARMA PRICING / PRODUCT PERFORMANCE MONITOR

Prepared: 2026-09-24

## Scope

V88 adds a read-only pricing/performance monitor. It does not change accounting,
inventory, receivable, historical SaleLine or capital formulas.

Active routes:

- /pricing-monitor/
- /pricing-monitor/export/xlsx/

The dashboard embeds a short top-product comparison and links to the full report.

## Core comparison

For a selected Jalali date, each row is one canonical Darma product code + size.

Example:

- 1405/07/03 is compared with 1405/06/03.
- current and previous packs, gross sales, profit, margin, average pack price,
  average short price and sales share are shown.
- if the selected date is today, raw live values are shown but daily percentage
  changes are deliberately marked provisional until the day is complete.

The month-to-date comparison uses completed days only. Therefore a live day is
excluded from the fair cumulative comparison.

The monitored list is the top 20 product-code/size combinations by packs sold in
the full previous Jalali month.

## Financial source of truth

V88 never invents a new sales-profit formula.

It uses:

    core.finance.sale_line_metrics()

Therefore historical SaleSnapshot values remain authoritative where present:

- historical pack quantity;
- historical unit cost / COGS;
- historical Digikala fee.

Existing SaleLine.sale_price is the authoritative actual saved sale price.

## Pack 6 canonicalization

Darma aliases 06 / 6 / pack6 / pack06 are grouped as canonical code:

    06

This prevents separate report rows for the same product concept.

Case of unrelated product codes is otherwise preserved.

## Price history

V88 reads existing V60 date-effective sale-price rules. No price values are hard-coded.

The first rule for a ProductSize compares to that ProductSize's legacy
default_sale_price. Later rules compare to the prior rule for the same ProductSize.

Price rules have date precision because V60 stores an effective date, not an
actual wall-clock activation timestamp. V88 must not claim hour-level causality.

## Adjusted historical profit

For cumulative comparisons, V88 reports both:

- actual historical profit using the historical SaleSnapshot cost;
- previous-period profit recomputed using the current Darma accounting unit cost.

This second number is explicitly an adjusted analytical comparison; it never
rewrites historical accounting.

## Credit-sale limitation

The current internal SaleLine/SaleSnapshot schema does not persist a reliable
cash-vs-credit classification and actual credit settlement fee per order.

V88 therefore does NOT hard-code 7.6%, 3.9pp or any other estimate. The UI and
XLSX explicitly state that credit splitting is unavailable from the present
internal data model. Add it only after a reliable source of order-level credit
data is integrated.

## 10-day evaluation

V88 uses the latest effective price rule for each code/size. Only completed days
are counted. Fewer than 10 completed days is labeled as insufficient data.

After 10 completed days the status is descriptive:

- نامزد بررسی افزایش
- نیازمند پایش بیشتر
- نیازمند بررسی افت عملکرد

No product price is ever changed automatically.

## XLSX

Sheets:

1. خلاصه مدیریتی
2. مقایسه روز مشابه
3. مقایسه تجمعی
4. تاریخچه قیمت
5. ارزیابی ۱۰ روزه

The export follows the selected date/code/size filters.

## Regression

Run:

    python manage.py check_pricing_monitor_v88

Expected marker:

    SUCCESS: PRICING MONITOR V88 CHECK PASSED

The command is read-only and verifies route/template/XLSX availability,
historical Jalali comparison and 06/pack6 canonical grouping.

## Deployment notes

V88 is based on v87-historical-capital commit
358f27e1cf39e8c160e0e4904f63490e30469fb6.

No migration is required.

Production source is baked into the Docker web image, so rebuilding/recreating
the web service is required after checkout.
