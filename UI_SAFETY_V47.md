# UI SAFETY V47 — BLACK / RED RUNTIME THEME

V47 is strictly presentation-only.

Allowed effects:

- black/charcoal/red CSS palette;
- sidebar logo plaque/background presentation;
- red active/hover/focus accents;
- comprehensive-report KPI layout alignment;
- professional inventory-table styling only: sticky headers/model column, zebra rows, hover states, numeric alignment, total/footer emphasis, responsive presentation;
- responsive visual changes only.

Forbidden effects:

- any model/migration change;
- any route/view/business service change;
- any accounting, receivable, capital or valuation change;
- any inventory quantity/location change;
- any HOME/KHORSHID semantic change;
- any sale/import/allocation change;
- any payment/material/production/return/Digikala behavior change.

Deployment must capture the exact filtered economic snapshot before and after and require equality.

V47 is implemented as runtime CSS overlays inside the web container. Tracked business code, templates and production CSS source remain unchanged. This makes rollback a clean web-container rebuild/recreate from current Git source.

Full UI trial command:

```bash
bash server_black_red_ui_v47_full.sh
```

Remove only the inventory-table extension while keeping the base V47 theme:

```bash
bash server_black_red_ui_v47.sh
```

Rollback all V47 presentation changes:

```bash
bash server_rollback_black_red_ui_v47.sh
```

Do not call the full V47 trial production-confirmed until the user posts:

```text
SUCCESS: BLACK RED UI V47 + PROFESSIONAL INVENTORY UI DEPLOYED
```
