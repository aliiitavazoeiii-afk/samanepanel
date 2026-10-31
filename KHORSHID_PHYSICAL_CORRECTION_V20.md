# Khorshid physical correction v20

Date documented: 2026-08-27

The user supplied the corrected physical Khorshid spreadsheet `موجودی انبار خورشید(1).xlsx`.

Authoritative correction for Darma / KHORSHID / XXL:

- قرمز / XXL: **0** (the old v18 baseline incorrectly recorded 140)
- کرم / XXL: **400** (the old v18 baseline incorrectly recorded 260)

This is a color/model misclassification of the same 140 pieces:

- red delta = -140
- cream delta = +140
- total Darma quantity delta = 0

Do **not** rerun the full v18 physical baseline to repair this. Use the one-off safe command:

```bash
python manage.py correct_khorshid_red_cream_xxl_v20
python manage.py correct_khorshid_red_cream_xxl_v20 --apply
```

Preferred production deployment path:

```bash
cd /opt/darma-general
git pull --ff-only
bash server_correct_khorshid_red_cream_xxl_v20.sh
```

The command refuses to apply unless the current known-bad cells are still exactly red=140 and cream=260, or exits harmlessly if already corrected to red=0 and cream=400. It records explicit InventoryMovement ADJUST rows and requires total Darma quantity to remain unchanged.

Rollback branch before this correction code:

`before-khorshid-red-cream-xxl-correction-v20`
