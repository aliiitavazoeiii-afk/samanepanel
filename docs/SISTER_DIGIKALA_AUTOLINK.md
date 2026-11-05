# DigiKala → canonical stock: guarded automatic matching

## Dataset actually audited

Source: existing 538 DigiKala external-variant records, matching the
previously provided `digikala kala.xlsx`, plus the verified 213
SKU `catalog_body_20261031.json` manifest. No external stock quantity
is copied into physical inventory.

| Marketplace group | Total variants | Matched in isolated fixture |
| --- | ---: | ---: |
| Men's underwear | 325 | 165 |
| Women's underwear | 196 | 147 |
| Men's undershirts | 9 | 9 |
| Shoe molds/accessories | 8 | 0 |
| **Total** | **538** | **321** |

The remaining fixture results are 24 ambiguous and 193 unknown/no exact
SKU. Actual results may differ when the live isolated panel contains extra
manually defined master SKUs or existing manual connections.

### Rules

- Physical SKU identity: category + exact normalized color + size +
  men's slip/padar type (when provided). Never compare digits in
  merchant model identifiers as a substitute for a physical size.
- Women's size ranges: 36–38=M, 38–40=L, 40–42=XL, 42–44=XXL,
  44–46=3XL. Single-number `36`, `38`, `40` or `42` is
  intentionally **not** interpreted as a range.
- Men’s `XXL` and `2XL` are the same physical `2XL` in the verified
  Bodyguard inventory; women’s `XXL` remains `XXL`.
- Equivalent spelling, e.g. `سرمه ای` / `سرمه‌ای`, `آبی نفتی` /
  `ابی نفتی`, is normalized. Generic `طوسی` is NOT guessed to mean
  `طوسی فیلی` or `طوسی ملانژ`.
- A multi-item listing is mapped only if the exact number and color of
  each physical item is known. E.g. two black plus one white deducts
  2×black and 1×white per order. A 4-piece two-color listing with no
  per-color quantities remains unmapped.
- Men's listings without an explicit slip/padar type can map only when
  exactly one possible physical SKU exists. Ambiguities remain unmapped.
- Mold size ranges cannot be inferred as small/medium/large, so they
  remain unmapped.
- Previous manual mappings, existing prices, prior sales and physical
  balances are preserved. Variants with prior sales are never silently
  remapped.

### Storage & transactions

`products.master_id` remains the legacy representative link.
`dk_variant_parts` records each *actual* piece of a listing by position
and `master_id`. `dk_auto_match_audit` tracks exact match status and
failure reason per variant.

In the strict DigiKala sale preview, cost of goods is the sum of all
physical components per marketplace unit, using the effective-dated
cost rule on the sale date. Stock-check and commit atomically deduct
each component in the selected location. Reimport of the same
date/source restores and reapplies quantities with proper multipliers,
rather than double-decrementing stock. The preview carries a stable
component signature and fails closed if mapping changed after preview.
Fee calculation is based on the original DigiKala category, not on
internal Bodyguard category labels.

### Deployment

After backing up isolated Postgres and SQLite, running all unit and
route tests, and importing missing physical master definitions without
opening stock, the sister-only installer runs:

```bash
docker compose -f compose.fresh.yml exec -T sister-digikala python -m daily_sales_service.digikala_auto_link --dry-run
docker compose -f compose.fresh.yml exec -T sister-digikala python -m daily_sales_service.digikala_auto_link --apply
```

Final marker: `DK_538_AUTO_LINK_AUDITED_READY`.

The `/settings/products/platforms/digikala/` page shows totals,
matched physical components, and the reason for leaving each variant
unmapped. Filter `فقط بدون اتصال` to inspect unmatched variants.

Never apply this importer to `/opt/darma-general`, `/opt/dia-gallery`
or their production databases/volumes.
