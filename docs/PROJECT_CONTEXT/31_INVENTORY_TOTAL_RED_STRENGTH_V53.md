# 31 — INVENTORY TOTAL RED STRENGTH V53

Status at creation: GitHub-prepared. This is a presentation-only follow-up to V52.

User changed only the visual severity colors in the `موجودی کل` table:

- V52 semantic band `orange` (TOTAL 50..99) should no longer look orange; it should use the previous normal red appearance.
- V52 semantic band `red` (TOTAL below 50) should use a much brighter / more vivid red appearance.
- HOME table behavior/appearance stays as V52.
- KHORSHID table stays unchanged.
- Thresholds and exemption rules stay exactly V52.

Therefore backend alert semantics remain:

```text
HOME: <30 => red
TOTAL: <50 => red, 50..99 => orange, >=100 => normal
```

but template visual mapping for TOTAL becomes:

```text
TOTAL semantic orange => previous red visual
TOTAL semantic red    => vivid/hot red visual
```

The semantic names are intentionally retained in `inventory_v20.py` because this is a UI-only request and no threshold/business logic needs to change.

Exempt colors/models remain unchanged:

- زرد
- قرمز
- خرسی variants
- مشکی کبریتی / کبریتی مشکی
- راه راه سرمه ای variants
- پلنگی variants

Changed file:

- `templates/core/inventory_v19.html`

No model, migration, inventory quantity, valuation, accounting, sale, transfer, correction, return, material, payment, or Digikala logic changes.
