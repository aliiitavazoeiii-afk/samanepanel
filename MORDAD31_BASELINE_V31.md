# Darma 31 Mordad Baseline V31

Authoritative source: user workbook `mojodi 31 mordad.xlsx` uploaded on 2026-08-29.

This is a combined HOME + KHORSHID Darma inventory snapshot for end-of-day 1405/05/31.
It is intentionally used exactly as supplied, including negative cells. `راه راه سرمه ای` in the workbook maps to the internal Darma color `راه راه`.

Target totals:

- TOTAL = 14,864 shorts
- M = 2,109
- L = 4,096
- XL = 3,002
- XXL = 4,106
- 3XL = 1,143
- 4XL = 408
- Accounting value at 61,000 toman/short = 906,704,000 toman

Reconcile semantics:

- No SaleDay dated 1405/06/01 or later may exist when applying this baseline.
- The workbook has no location split, so existing KHORSHID rows are preserved.
- For each Darma color x size cell, only HOME receives the delta required to make HOME + KHORSHID equal the workbook target.
- Every applied delta is recorded with InventoryMovement reference `mordad31-baseline-v31`.

Command:

```bash
python manage.py reconcile_darma_mordad31_v31
python manage.py reconcile_darma_mordad31_v31 --apply
```

Safe server script:

```bash
bash server_darma_mordad31_v31.sh
```
