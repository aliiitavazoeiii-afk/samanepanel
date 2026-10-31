# 24 — NO AUTOMATIC KHORSHID TRANSFER V46

Status at creation: GitHub-prepared. Do not call production-live until the user posts successful server deployment output.

This file records an explicit user business-rule change on 2026-08-31. It supersedes older statements in `01_BUSINESS_RULES_AND_INVARIANTS.md` and `05_INVENTORY_MATERIALS_PRODUCTION_PAYMENTS.md` that said sale logic may automatically move Darma stock from KHORSHID to HOME.

---

## Explicit business rule

A sale must NEVER move physical Darma stock between locations automatically.

For every Darma-backed sale channel, including normal Darma sales, Anbaresh, variable-color `s3`, and Dia Gallery:

```text
sale quantity -> subtract from HOME only
KHORSHID -> unchanged by sale
```

HOME is allowed to become negative.

Example:

```text
HOME before sale = 5
sale = 15
HOME after sale = -10
KHORSHID = unchanged
```

A physical KHORSHID -> HOME transfer occurs only when the user explicitly records a transfer in inventory operations.

Example requested by user:

```text
HOME = -10
KHORSHID = 50
manual transfer = 30

HOME after = 20
KHORSHID after = 20
```

Manual transfer remains capital-neutral and total-quantity-neutral.

---

## Active source behavior

`core/final_services.py`

- `_transfer_for_need()` is retained for call compatibility but is now HOME-only.
- it does not read, decrement, or transfer KHORSHID stock.
- normal Darma sales, Anbaresh sales, replacement-color paths, and Dia Gallery callers therefore cannot auto-transfer warehouse stock.

`core/variant_sale_v12.py`

- the special variable-color `s3` path previously had its own direct KHORSHID auto-transfer block;
- V46 removes that block;
- it deducts the requested color quantity from HOME directly, even below zero.

`core/inventory_operations_v15.py` + `core/final_services.sync_stock_transfer()`

- explicit manual transfer semantics are unchanged;
- source location decreases by entered quantity;
- destination location increases by entered quantity;
- therefore a negative HOME balance is naturally offset when the real physical transfer is later entered.

---

## Historical repair

The authoritative physical HOME/KHORSHID baseline is end-of-day `1405/06/03`, movement reference:

```text
day3-physical-files-v32
```

Any automatic sale transfer before that baseline is already absorbed into the later physical count and must NOT be replayed/reversed separately.

V46 repair command:

```bash
python manage.py reconcile_no_auto_transfer_v46
python manage.py reconcile_no_auto_transfer_v46 --apply
```

The command:

- starts strictly after the last V32 physical-baseline movement;
- finds only Darma transfer-ledger pairs whose references contain `auto-transfer` or `replacement-transfer`;
- validates that each pair is exactly KHORSHID negative / HOME positive for the same amount;
- reverses that phantom transfer by subtracting the amount from HOME and restoring it to KHORSHID;
- allows HOME to become negative;
- leaves combined Darma quantity unchanged;
- leaves finished-inventory value and capital unchanged;
- does not alter SaleLine, SaleAllocation, or accounting entries;
- is idempotent per original transfer group through `v46-reverse-auto:<source_id>` references.

This is a one-time historical location correction plus an ongoing sale policy change.

---

## Important invariant after V46

For sales:

```text
KHORSHID sale delta = 0
HOME sale delta = -physical units sold
```

For explicit manual transfer `q` from KHORSHID to HOME:

```text
KHORSHID delta = -q
HOME delta = +q
combined delta = 0
capital delta = 0
```

Do not reintroduce automatic replenishment inside a sale/import path, even if HOME is negative and KHORSHID has enough stock.

Alerts may still SUGGEST a manual transfer. A suggestion is not permission for the backend to execute one automatically.

---

## Deployment safety

Rollback branch:

```text
before-no-auto-transfer-v46-20260831
```

Deploy script:

```bash
bash server_no_auto_transfer_v46.sh
```

The deploy script must:

- back up PostgreSQL;
- run source/migration checks;
- dry-run the historical reversal;
- recreate web with the new HOME-only sale policy before applying the reversal;
- run a rollback regression proving the exact `HOME=-10`, transfer `30` -> `HOME=20` arithmetic;
- apply the historical reversal atomically;
- prove combined Darma quantity/value and capital are unchanged.

---

## First production attempt — 2026-08-31

The first production run reached and successfully committed the historical location repair:

```text
After  HOME=2620 KHORSHID=8890 COMBINED=11510
SUCCESS: V46 REVERSED 19 PHANTOM AUTO-TRANSFER UNITS
```

The following final shell guard then stopped with:

```text
FAILED: V46 changed economic totals/capital
```

This failure occurred after the 19-unit repair had already committed; the shell exit did not roll that transaction back.

The guard compared the complete stdout of `manage.py shell -c`. Django 5.2 also emits a non-business automatic-import banner such as `54 objects imported automatically` / `55 objects imported automatically`. A changed banner across web image recreation can therefore make two otherwise identical economic snapshots compare unequal.

The deploy script was corrected to:

- filter snapshots to explicit invariant `KEY=value` lines only;
- exclude the Django shell import banner from comparisons;
- print both invariant snapshots if a real mismatch remains;
- remain safe to rerun because the historical repair command is idempotent.

V46 still must not be marked production-confirmed until the corrected deploy script completes with the final success marker.
