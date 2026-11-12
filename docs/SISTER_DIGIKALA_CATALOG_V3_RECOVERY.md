# DIA sister panel — DigiKala catalog edit / archive / restore (V3)

**Verified live on 2026-11-12** on the isolated `dia-darma-fresh` stack.
Repository: `aliiitavazoeiii-afk/samanepanel`
Main development branch: `dia-darma-fresh`
Verified tested source commit: `dbd0d43015e45167a45b124b71a607fb1525f387`
Server project directory: `/opt/dia-darma-fresh`
User-visible page: `https://forosh.filmjadiid.ir/settings/products/platforms/digikala/`

## What is preserved in GitHub

- Per-DigiKala-variant local display title and optional display price.
- Individual reversible removal from the **local catalog view**, not deletion of the external variant.
- The **حذف‌شده‌ها** tab and per-variant restoration.
- Django authenticated/CSRF-protected POST proxy routes.
- FastAPI POST handlers for `/daily-sales/catalog/edit`, `/archive`, and `/restore`.
- Regression tests of edits, removals, preservation of history and stock, and real HTTP POST routing.
- The exact **successful** no-build, backup-first hotpatch:
  `deploy/darma-fresh/hotpatch_digikala_catalog_actions_v3.sh`.

Source files involved:
- `daily_sales_service/dk_catalog_preferences.py`
- `daily_sales_service/master_api.py`
- `daily_sales_service/master_v2_api.py`
- `daily_sales_service/master_v2_logic.py`
- `daily_sales_service/digikala_auto_link.py`
- `daily_sales_service/digikala_manual_pack.py`
- `core/sister_sales.py`
- `core/tests_sister_sales.py`
- `tests/test_digikala_catalog_actions.py`

## Successful live installation evidence (owner's terminal)

```text
FASTAPI_VERSION 0.162.0
CATALOG_POST_ENDPOINTS_OPENAPI_PASS ['/daily-sales/catalog/archive', '/daily-sales/catalog/edit', '/daily-sales/catalog/restore']
PRODUCTS_BEFORE_RESTART=538
LIVE_ROUTES_VERIFIED_BY_OPENAPI ['/daily-sales/catalog/archive', '/daily-sales/catalog/edit', '/daily-sales/catalog/restore']
CATALOG_HTTP_OK unmapped
CATALOG_HTTP_OK removed
SISTER_SOURCE_PRODUCT_COUNT 538
CATALOG_REAL_POST_REACHED edit
CATALOG_REAL_POST_REACHED archive
CATALOG_REAL_POST_REACHED restore
SISTER_DIGIKALA_CATALOG_EDIT_REMOVE_RESTORE_HTTP_OK
SISTER_VARIANT_COUNT_UNCHANGED=538
DJANGO_CATALOG_PROXY_ROUTES_OK
SISTER_DIGIKALA_SINGLE_ITEM_EDIT_DELETE_RESTORE_READY
BACKUP_PATH=/opt/dia-darma-fresh/backups/dk-catalog-actions-v3-20261112T172331
```

Note: the HTTP POST smoke uses **invalid** variant IDs and confirms the handlers
are reachable without modifying catalog records. Actual operator-originating
edit/delete operations were not exercised in the success log.

## Future recovery or repeat of the tested hotpatch

**Only on the isolated sister server**, after verifying the correct repository,
working tree and Compose project. Never run on production Darma or Dia Gallery.

```bash
cd /opt/dia-darma-fresh

curl -fsSLo /root/fix_digikala_v3.sh \
  https://raw.githubusercontent.com/aliiitavazoeiii-afk/samanepanel/dbd0d43015e45167a45b124b71a607fb1525f387/deploy/darma-fresh/hotpatch_digikala_catalog_actions_v3.sh

set -o pipefail
bash /root/fix_digikala_v3.sh 2>&1 | tee /root/dk-catalog-v3-recovery.log
```

The script fast-forwards the working checkout to branch `dia-darma-fresh`;
performs isolated sister SQLite and code backups; stages the matching
`daily_sales_service` tree and `core/sister_sales.py`; validates the API via
OpenAPI and real read-only / deliberately invalid-ID HTTP probes; restarts
**only** sister `web` and `sister-digikala` containers; rolls code back on
failure. If any later changes on the development branch are incompatible,
pin the deployment to this tested commit or the stable snapshot branch and
review changes before executing, rather than blindly following moving HEAD.

The versioned hotpatch is a convenience for existing containers; it is
**not a replacement for building updated images** and does not download Python
dependencies.

## When containers are recreated or the server is moved

A source-only hotpatch changes the *running container filesystem*. A Docker
recreate replaces that filesystem; the image must be built from the updated
GitHub source to make the feature durable:

- Sister FastAPI build source: `deploy/darma-fresh/Dockerfile.sister-sales`
  copies `daily_sales_service/` from the repository.
- Django `web` build source: repository root `Dockerfile` copies `core/sister_sales.py`.
- Compose project: `compose.fresh.yml` under `/opt/dia-darma-fresh`.
- Before any fresh build, back up the dedicated sister SQLite Docker volume and
  Django database, validate dependency availability, and keep rollback images.
  Rebuild **only** `web` and `sister-digikala` using an audited build plan.
  Do not remove volumes (`down -v` is forbidden).
- After rebuild, check actual HTTP response for `/daily-sales/catalog?status=unmapped`
  and `?status=removed`, and issue invalid-ID POST checks to `edit`,
  `archive`, `restore` to confirm no 404.
- The local catalog preferences are stored in the **sister SQLite database**
  in `sister_sales_data` and are **not committed to GitHub**. Preserve
  / restore that database volume or the preference selections will not follow
  a server migration.

## Safety and behavior

- Archiving does not delete a DigiKala product from its remote marketplace
  and does not stop its existing historical variant ID appearing in incoming
  sales files; these are intentional protections against losing accounting data.
- The optional display price only changes the label shown in this internal
  page; it does not update DigiKala's remote price or historical sales.
- Physical master SKU inventory, prior mappings, and recorded sales are retained.
- `app.routes` is **not a valid completeness test on FastAPI 0.162**:
  `include_router` can produce lazy wrappers. Use `app.openapi()["paths"]`
  and real authenticated HTTP POST tests instead.
- Never store credentials, `.env`, production database contents or backups in GitHub.

## Source of truth / future work

Use the tested commit above for reproducing this successful V3 behavior.
The active `dia-darma-fresh` branch may continue to receive unrelated updates.
For future feature changes, review this document, `tests/test_digikala_catalog_actions.py`,
and the isolated sister-only Compose project before deployment.
