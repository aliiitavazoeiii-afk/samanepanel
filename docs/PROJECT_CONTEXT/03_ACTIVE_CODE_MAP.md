# 03 — ACTIVE CODE MAP

This is the current source-of-truth map for `main`. Historical version numbers in filenames are not enough to determine what is active. Always verify `core/urls.py` first.

Last synchronized: 2026-08-30 after V40 Digikala read-only code was prepared on GitHub. V40 is not production-confirmed until successful server output.

---

## 1. Production stack

- Django 5.2
- PostgreSQL 16 Alpine
- Gunicorn
- WhiteNoise
- Caddy HTTPS
- Docker Compose
- Jalali business dates via `jdatetime`
- dark navy / glass UI
- project path `/opt/darma-general`
- production domain `gozaresh.filmjadiid.ir`

V40 adds a bind-mounted token-only Digikala runtime directory for the `web` service:

```text
/opt/darma-secrets/digikala/runtime -> /run/secrets/digikala
```

The RSA private key remains outside that runtime directory and must not be mounted into web.

---

## 2. Current route map from `core/urls.py`

### Dashboard

```text
/ -> core.excel_dashboard.dashboard
```

Important files:

- `core/excel_dashboard.py`
- `templates/core/dashboard_excel.html`

Current requested dashboard alert display is Darma HOME < 10, excluding red/yellow.

V40 adds an asynchronous Digikala summary card to the dashboard template. The internal dashboard calculation view remains unchanged; Digikala network I/O happens through `/digikala/summary/` after the page loads.

### Digikala Open API V40

```text
/digikala/ -> core.digikala_views_v40.digikala_home
/digikala/summary/ -> core.digikala_views_v40.digikala_summary
```

Important files:

- `core/digikala_client_v40.py`
- `core/digikala_views_v40.py`
- `templates/core/digikala_v40.html`
- `core/management/commands/check_digikala_v40.py`
- `compose.yml`
- `static/core/number_format.js` adds the sidebar navigation entry
- `server_digikala_readonly_v40.sh`

Both DARMA routes are login-protected and `@require_GET`.

Allowed external V40 calls are GET-only for orders, order statistics, inventory, profile, commitments and invoices. The only external POST is the official `/open-api/v1/auth/refresh-token` credential-maintenance endpoint. No Digikala API response is applied to internal SaleLine, inventory or accounting ledgers in V40.

### Calendar/sales entry

```text
/sales/ -> core.daily_views.sale_calendar
/sales/select/<jy>/<jm>/<jd>/ -> core.daily_views.select_sale_day
/sales/<day_id>/ -> core.sale_brand_v19.sale_brand
/sales/<day_id>/<brand_id>/<size_id>/ -> core.daily_views.sale_size
/sales/save/ -> core.excel_sales.sale_line_save
```

Important files:

- `core/daily_views.py`
- `core/sale_brand_v19.py`
- `core/excel_sales.py`
- `core/sale_inventory_v19.py`
- `core/final_services.py`
- `core/cost_accounting_v14.py`

### Daily Digikala XLSX

```text
/sales/<day_id>/import-xlsx/ -> core.daily_order_views_v8.import_daily_orders
```

The view imports the **V23** engine:

```python
from .daily_order_import_v23 import apply_delivery_report
```

Therefore active parser/apply path is:

- `core/daily_order_views_v8.py`
- `core/daily_order_import_v23.py`
- `core/daily_order_import_v12.py` for row resolution/aggregation helpers
- `core/title_product_resolver_v27.py` for strict title product identity
- `core/variant_sale_v12.py` for Darma s3 variable-color stock
- `core/final_services.py` for normal sale inventory sync
- `core/cost_accounting_v14.py` for sale snapshot
- `core/finance_excel_v9.py` for receivable sync

V40 does **not** replace this importer. Do not connect API orders to this flow without a separate accounting/stock-safe phase.

### Daily report

```text
/sales/<day_id>/report/ -> core.daily_report_v8.daily_report
```

After V37 the active daily report renders:

```text
templates/core/daily_report_v21.html
```

The V36 inline return box is retired. `daily_report_v8.py` no longer imports/builds the return catalog.

Daily report line actions:

```text
/sales/report-line/<line_id>/price/ -> core.daily_report_actions_v21.sale_price_update
/sales/report-line/<line_id>/delete/ -> core.daily_report_actions_v21.sale_line_delete
```

### Standalone returns V37

```text
/returns/ -> core.returns_v37.returns_home
/returns/apply/ -> core.returns_v37.return_apply
```

Important files:

- `core/returns_v37.py`
- `templates/core/returns_v37.html`
- `static/core/number_format.js` injects sidebar link under daily work
- `core/management/commands/check_returns_calculator_v37.py`

The old route:

```text
/sales/<day_id>/return/
```

must not exist in V37+.

### Comprehensive report

```text
/report/ -> core.report_v9.report
/report/manual/ -> core.report_v9.manual_report_action
```

Current report template:

```text
templates/core/report_excel_v36.html
```

This template extends/reorganizes the existing comprehensive-report UI. The accounting calculation remains in `core/report_v9.py`.

Important supporting files:

- `core/report_v9.py`
- `core/report_v5.py` for raw-material context / legacy manual actions
- `core/finance_excel_v9.py`
- `core/inventory_valuation_v17.py`
- `templates/core/report_excel_v36.html`
- raw-material partial templates

### Material report / production

Current route split:

```text
/material-report/ -> core.material_report_v22.material_report
/material-report/<block_id>/save/ -> core.material_report_v22.material_block_save
/material-report/<block_id>/apply/ -> core.material_report_v22.material_block_apply_materials
/material-report/<block_id>/apply-output/ -> core.material_report_v22.material_block_apply_output
/material-report/<block_id>/unapply/ -> core.material_report_v20.material_block_unapply_materials
/material-report/<block_id>/delete/ -> core.material_report_v20.material_block_delete
```

Important files:

- `core/material_report_v22.py` = active page/save/apply-materials/apply-output logic
- `core/material_report_v20.py` = base helpers + active unapply/delete
- `core/material_report_v21.py` remains imported but route map should be checked before edits
- `templates/core/material_report_v35.html`
- `core/material_flow.py`
- `core/material_cost_v13.py`
- `core/models.py` for MaterialReport* and InventoryMovement

Current V22/V35 semantics include editable cumulative Darma/Novani delivered quantities and two-way wage/stock sync.

### Payments

```text
/payments/ -> core.business_tools_v22.payments
/payments/add/ -> core.business_tools_v22.payment_add
/payments/<payment_id>/edit/ -> core.business_tools_v22.payment_update
/payments/<payment_id>/delete/ -> core.business_tools_v22.payment_delete
```

Important files:

- `core/business_tools_v22.py`
- `core/business_tools_v21.py` helpers/legacy finance paths
- `core/material_purchase_v13.py`
- `core/material_purchase_v14.py`
- `core/material_flow.py`
- `templates/core/payments_v22.html`

### Digikala receipt / Mellat manual set

```text
/payments/mellat/set/ -> core.business_tools_v21.mellat_set
/payments/receipts/add/ -> core.business_tools_v21.receipt_add
/payments/receipts/<receipt_id>/edit/ -> core.business_tools_v21.receipt_update
/payments/receipts/<receipt_id>/delete/ -> core.business_tools_v21.receipt_delete
```

Do not confuse these internal receivable/cash settlement routes with the external Open API V40 integration.

### Calculator V37

```text
/calculator/ -> core.calculator_v37.calculator
/calculator/quote/ -> core.calculator_v37.calculator_quote
/calculator/target-quote/ -> core.calculator_v37.calculator_target_quote
```

Important files:

- `core/calculator_v37.py`
- `templates/core/calculator_v37.html`
- `templates/core/_calculator_target_result_v37.html`
- `templates/core/_calculator_result.html`
- `core/finance.py` exact fee engine

### Finished inventory

```text
/inventory/ -> core.inventory_v20.inventory
/inventory/color-model/add/ -> core.inventory_v20.add_color_model
/inventory/operations/ -> core.inventory_operations_v15.inventory_operations
```

Important files:

- `core/inventory_v20.py`
- `core/inventory_operations_v15.py`
- `core/inventory_valuation_v17.py`
- inventory templates used by v20

### Takvin purchase screen

```text
/takvin/ -> core.takvin_v5.takvin_excel
```

### Settings

```text
/settings/ -> core.views.settings_home
/settings/catalog/ -> core.catalog_v5.settings_catalog
/settings/products/ -> core.pricing_v7.settings_products
/settings/products/new/ -> core.views.settings_product_form
/settings/products/<product_id>/ -> core.views.settings_product_form
/settings/stock/ -> core.settings_stock_v5.settings_stock
/settings/finance/ -> core.views.settings_finance
/settings/rules/ -> core.settings_rules_v17.settings_rules
```

### Legacy/general pages still routed

```text
/materials/ -> core.final_views.materials
/production/ -> core.final_views.production
/finance/ -> core.final_views.finance
/expenses/ -> core.final_views.expenses
/assets/ -> core.final_views.assets
```

Do not assume these are the primary current UI for raw materials/capital. Check user's requested entry point.

---

## 3. Protected calculation files

V40 deployment explicitly protects these from accidental modification:

- `core/finance.py`
- `core/report_v9.py`
- `core/inventory_valuation_v17.py`
- `core/business_tools_v22.py`
- `core/material_report_v22.py`
- `core/final_services.py`
- `core/cost_accounting_v14.py`
- `core/finance_excel_v9.py`
- `core/daily_order_import_v23.py`
- `core/returns_v37.py`
- `core/calculator_v37.py`
- `core/models.py`
- `core/migrations/`

A future UI/external-read change should preserve the same discipline unless the user explicitly requests a business-rule change.

---

## 4. Active source by concept

### Capital

- `core/report_v9.py`
- `core/inventory_valuation_v17.py`
- `core/report_v5.py` raw context
- `core/finance_excel_v9.py` Digikala total

### Digikala fee/profit

- `core/finance.py`
- `core/cost_accounting_v14.py` snapshot creation

### External Digikala Open API read visibility

- `core/digikala_client_v40.py`
- `core/digikala_views_v40.py`
- `templates/core/digikala_v40.html`
- `templates/core/dashboard_excel.html` async summary UI

This is separate from the internal Digikala fee/receivable/XLSX-import business flows.

### Sale physical allocation

- normal sale: `core/final_services.py`
- Anbaresh manual sale: `core/sale_inventory_v19.py`
- variable s3: `core/variant_sale_v12.py`

### Daily importer

- parser/apply: `core/daily_order_import_v23.py`
- resolution helpers: `core/daily_order_import_v12.py`
- strict title identity: `core/title_product_resolver_v27.py`
- web transaction/invariant wrapper: `core/daily_order_views_v8.py`

### Material consumption/output

- active main flow: `core/material_report_v22.py`
- base/unapply/delete/helpers: `core/material_report_v20.py`
- raw stock primitives: `core/material_flow.py`

### Payment purchase/prepayment

- `core/business_tools_v22.py`
- `core/material_purchase_v13.py`
- `core/material_purchase_v14.py`
- `core/business_tools_v21.py`

### Standalone return

- `core/returns_v37.py`

### Price target calculator

- `core/calculator_v37.py`
- exact fee engine `core/finance.py`

---

## 5. Management commands/checks that matter

Do not blindly run all historical checks; some are tied to old states. Current/high-value checks include:

```text
python manage.py check
python manage.py check_returns_calculator_v37
python manage.py check_digikala_v40 --live
python manage.py check_operational_roundtrip_v36
python manage.py check_v23_delivery_import
python manage.py check_current_delivery_file_v27
python manage.py check_daily_report_v26
python manage.py check_capital_integrity_v14
python manage.py capital_audit_v9
```

`check_digikala_v40 --live` reads external Digikala data and may rotate the API token if the Access Token expired; it does not write internal business data.

Before running an old versioned check, inspect its expectations against current routes. A check that expects an intentionally retired V36 route can fail for the correct reason.

---

## 6. Deployment scripts: current versus historical

Most `server_*.sh` files are historical one-time deployment/reconcile scripts. Do not choose one based on the highest version number alone.

Prepared V40 deployment script:

```text
server_digikala_readonly_v40.sh
```

It is the correct deployment path for the V40 Git state. It also builds the current presentation tree already on `main`, including V39 assets.

The script:

- isolates runtime API tokens from the RSA private key;
- starts DB;
- takes full pg_dump;
- captures capital/inventory/receivable/sales invariants;
- verifies source scope;
- builds new web image;
- verifies no migration drift;
- runs V37 regression;
- runs the live read-only Digikala check;
- verifies preflight changed no business values;
- recreates web/restarts Caddy;
- reruns live checks;
- compares final invariants.

Expected marker:

```text
SUCCESS: DIGIKALA READ-ONLY V40 DEPLOYED
```

Do not call V40 live until that output is posted by the user.

---

## 7. Historical docs status

- `AI_START_HERE.md` is valuable but last updated around v19 and contains stale route/deployment statements.
- `PROJECT_HANDOFF.md` is an older detailed forensic record and contains outdated assumptions superseded by later work.

Do not delete them. Read them for history, but when they conflict with current context pack/current code, current code + `docs/PROJECT_CONTEXT` wins.
