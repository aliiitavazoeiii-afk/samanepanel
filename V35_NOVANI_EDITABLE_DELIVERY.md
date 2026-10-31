# V35 — Novani editable delivered-goods sync

Business rule:

- Novani delivered quantities are cumulative and editable both upward and downward.
- Save is data-only. It may now save a lower/blank Novani delivered cell even if that cell was already applied.
- `همگام‌سازی تحویل و موجودی` applies the signed difference:
  - positive delta: add only Novani stock and deduct wage for the increase;
  - negative delta: remove only Novani stock and return wage for the reduction.
- A reduction is blocked atomically if the affected Novani color/size does not have enough current stock.
- Darma retains the old positive-only reduction floor and cost-blending path.
- Wage rule is 110,000 toman per 12 delivered pieces. Cut quantity never creates delivery wage.
- V35 keeps a cumulative wage-piece ledger in `AppSetting` for each Novani material block. Legacy positive blocks can initialize only when V34 wage repair marker exists; otherwise sync is blocked for safety.

UI:

- Delivery-date column removed.
- `برش` column comes from the same material input row (`cut`).
- `کسری / مازاد` compares delivered total to cut: shortage red, surplus green.
- Grand total of all delivered pieces is shown below the table.
- Values update live in the browser while editing.

Rollback branch:

`before-novani-output-edit-v35`

Deploy:

```bash
cd /opt/darma-general
git pull --ff-only
bash server_novani_output_edit_v35.sh
```

The deploy backs up PostgreSQL, forces the configured dozen wage to 110,000, runs transactional regression checks, verifies business quantities/capital are unchanged, and then recreates the live web container.
