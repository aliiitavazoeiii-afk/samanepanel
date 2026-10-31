# UI / BUSINESS SAFETY V46 — HOME-ONLY SALES

V46 is an explicit inventory-location business-rule change, not a cosmetic UI change.

## Required behavior

- A sale can make Darma HOME negative.
- A sale must never decrement KHORSHID or create an automatic KHORSHID -> HOME transfer.
- This applies to normal Darma, Anbaresh-backed Darma stock, variable-color `s3`, replacement-color sale paths, and Dia Gallery.
- Manual inventory transfer remains the only operation allowed to move KHORSHID -> HOME.
- Example invariant: HOME `-10` + explicit transfer `30` => HOME `20`; KHORSHID decreases `30`.

## Historical correction boundary

- Reverse only automatic sale transfers after the authoritative end-of-day 3 Shahrivar physical baseline (`day3-physical-files-v32`).
- Never reverse pre-baseline movement history against the physical baseline.
- Historical reversal changes only HOME/KHORSHID split; combined Darma quantity/value and capital must remain identical.

## Frozen areas

V46 must not change:

- sale prices;
- Digikala fees;
- SaleSnapshot economics;
- Digikala receivable;
- Dia Gallery receivable/price;
- product composition;
- XLSX title resolver/replacement semantics;
- material/production/payment rules;
- returns semantics;
- combined finished inventory value or capital solely because of location repair.

## Deployment gate

Production is not V46 until `server_no_auto_transfer_v46.sh` finishes successfully and prints the final success marker plus the actual reversal quantity/location snapshots.
