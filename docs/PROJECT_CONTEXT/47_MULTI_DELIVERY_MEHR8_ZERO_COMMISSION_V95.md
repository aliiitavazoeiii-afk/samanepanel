# V95 — MULTI DELIVERY FILES + 8 MEHR ZERO DIGIKALA COMMISSION

## Purpose

Handle days where Digikala splits one sale day into multiple package-delivery XLSX files, and preserve the one-off business exception reported for 1405/07/08 (2026-09-30): Digikala commission was zero on every product for that date only.

## Multi-file day import

- The daily Digikala upload accepts one or more XLSX files in one submission.
- Every selected file is parsed with the existing V23 title-first resolver.
- Seller code remains intentionally ignored for identity.
- Rows from all selected files are merged by brand + product code + size + physical variant color.
- If the same product/size/color appears in two shipment files, quantities are summed.
- The merged set is the authoritative Darma/Takvin target for the day.
- Re-uploading the same complete file set is idempotent; it does not double quantities.
- Uploading files one-by-one is not the intended multi-shipment workflow because each submission is authoritative for the day. Select all same-day shipment files together.
- Manual Anbaresh rows on the same date remain untouched, matching V23 invariants.
- Inventory delta/invariant logic is unchanged.

## 8 Mehr 1405 fee exception

- Jalali 1405/07/08 maps to Gregorian 2026-09-30.
- On that date only, the Digikala commission component is 0%.
- Processing fee remains governed by the existing processing percentage/floor rules.
- VAT remains calculated from commission + taxable processing; with commission zero, there is no VAT contribution from commission.
- No other date receives this exception.
- `SaleSnapshot.digikala_fee_unit` is frozen using the SaleDay date, so a re-import of 8 Mehr refreshes the snapshot with the correct exceptional fee while preserving historical snapshots on other dates.
- Sale price, COGS, stock rules, and product identity are unchanged.

## User workflow for 8 Mehr

1. Open sale day 1405/07/08.
2. In Digikala XLSX upload, select BOTH shipment files at the same time.
3. Submit once.
4. The merged file set replaces the Darma/Takvin quantities for that date.
5. Existing positive SaleLine sale prices remain frozen; only quantity targets and sale snapshots are synchronized by the established importer behavior.
6. Digikala receivable entries are re-synced from the corrected quantities and the zero-commission fee snapshot.

## Regression

`python manage.py check_multi_delivery_mehr8_v95`

Checks:
- two previews merge into one full-day target;
- overlapping quantities sum;
- upload UI supports multiple XLSX files;
- 1405/07/08 == 2026-09-30;
- zero commission applies only on that date;
- processing-fee logic remains present;
- snapshot fee uses sale date;
- no stock/sale/snapshot/ledger writes occur during the read-only regression.

## Deployment

`bash server_multi_delivery_mehr8_v95.sh`

Expected final marker:

`SUCCESS: MULTI DELIVERY + MEHR8 ZERO COMMISSION V95 DEPLOYED`

GitHub branch state is not proof of production. Production is confirmed only after the VPS deploy completes and PRE / PROJECTED / FINAL invariants match.
