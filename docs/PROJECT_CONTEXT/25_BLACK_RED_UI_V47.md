# 25 — BLACK / RED UI V47

Status at creation: GitHub-prepared runtime UI overlay. Do not call it production-confirmed until the user posts the successful deploy marker.

V47 is presentation-only. It was requested after the user showed the comprehensive-report page and asked for:

- a black/red visual identity instead of the existing navy/brown/orange feel;
- the Darma logo to be visible in the sidebar instead of appearing as a blank/light plaque;
- a cleaner, equal four-column KPI strip in the comprehensive report;
- professional inventory tables with stronger hierarchy and scanability;
- a safe backup and one-command rollback if the new look is not preferred.

## Absolute boundary

V47 must not change:

- models or migrations;
- routes/views;
- accounting formulas;
- inventory quantities or HOME/KHORSHID semantics;
- SaleLine / SaleAllocation / SaleSnapshot;
- Dia Gallery accounting;
- Digikala logic/API behavior;
- payments/materials/production/returns;
- capital or valuation formulas.

## Runtime overlay architecture

V47 intentionally does **not** rewrite the tracked production CSS or templates.

Base deploy script:

```bash
bash server_black_red_ui_v47.sh
```

Full deploy including the professional inventory-table extension:

```bash
bash server_black_red_ui_v47_full.sh
```

The base script:

1. creates a PostgreSQL backup;
2. backs up the tracked current `static/core/ui-polish.css`, logo asset and Git HEAD under `backups/before-black-red-ui-v47-*`;
3. builds a clean web image from current Git source;
4. verifies migrations/Django/templates;
5. captures exact economic invariants;
6. recreates the clean web container;
7. appends a V47 presentation-only CSS overlay **inside the running web container** to `/app/static/core/ui-polish.css`;
8. reruns `collectstatic` and restarts the same container so WhiteNoise's manifest uses the themed stylesheet;
9. proves the business snapshot is unchanged.

The full script runs the safe base deploy first, then adds a second runtime-only inventory overlay. It compiles `core/inventory_v19.html`, captures the economic snapshot again, backs up the live V47 CSS, applies only CSS, reruns `collectstatic`, and requires the before/after business snapshot to remain exactly equal.

Because tracked CSS and inventory templates are left untouched, rollback is deterministic: recreating/rebuilding the web container from Git source removes the runtime overlays.

Rollback script:

```bash
bash server_rollback_black_red_ui_v47.sh
```

It takes another DB backup, rebuilds a clean image from current Git source, force-recreates web, verifies the V47 marker is absent, compiles templates, and proves business invariants did not move.

Rollback branch representing the pre-V47 Git state:

```text
before-black-red-ui-v47-20260831
```

## Visual contract

V47 palette:

- base: near-black / charcoal;
- panels: charcoal glass, not blue;
- primary accent: Darma red;
- hover/focus: brighter red;
- positive financial semantics remain green;
- error/danger semantics remain red.

The existing Darma artwork is displayed as a white logo on a dark plaque. The old light plaque is overridden.

Comprehensive report KPI strip:

- four equal columns on desktop;
- equal-height cards;
- consistent padding and numeric alignment;
- two columns on tablet/mobile;
- one column only on very narrow screens.

Inventory table extension:

- dark professional data-grid treatment scoped only to the inventory page;
- sticky table header for easier scanning;
- sticky `رنگ / مدل` column while horizontally scrolling;
- zebra rows and controlled hover emphasis;
- tabular numeric alignment;
- distinct total column in the main inventory table;
- stronger total and capital footer rows while preserving green positive-capital semantics;
- cleaner card headers, scroll hint, brand tabs and add-model box;
- responsive sizing on mobile;
- no inventory data, model, view, route or business-rule changes.

To remove only the professional inventory-table overlay while keeping the base black/red V47 theme, rerun:

```bash
bash server_black_red_ui_v47.sh
```

To remove all V47 presentation changes and return to the pre-V47 source appearance, run:

```bash
bash server_rollback_black_red_ui_v47.sh
```

## Operational note

V47 is a runtime overlay by design. Any later `--force-recreate`/fresh image deployment removes the overlay unless the corresponding V47 deploy script is run again afterward. This is intentional because the user explicitly wanted an easy reversible visual trial without risking business source.
