# 18 — DIGIKALA OPEN API V40

This file records the first direct Digikala Open API integration for DARMA General.

Status at creation: **committed to GitHub, NOT YET CONFIRMED LIVE**.

The latest confirmed production deployment remains V38 until the user posts an explicit successful VPS deployment output. V39 presentation code is already on `main`; a V40 deployment will naturally include the current V39 presentation state if it was not deployed separately beforehand.

---

## 1. User requirement

The user generated an official Digikala Open API application key pair and requested direct API data on the DARMA dashboard.

The first phase is deliberately **read-only**. It must not replace the existing XLSX sales importer, create SaleLines, change stock, change Digikala receivable, change capital, or write to any internal business ledger.

---

## 2. Authentication flow confirmed against the official Digikala specification

The user registered a 4096-bit RSA public key in the seller Open API panel.

The validation code flow was confirmed as:

1. Base64-decode the encrypted validation code;
2. decrypt the 512-byte RSA payload with the private key using PKCS#1 padding;
3. POST the decrypted `authorization_code` to:

```text
/open-api/v1/auth/token
```

The successful response returned both an Access Token and Refresh Token.

Refresh is performed through:

```text
/open-api/v1/auth/refresh-token
```

with both the previous `access_token` and `refresh_token`. Digikala returns a new refresh token on successful refresh, so V40 atomically replaces **both** token files.

Tokens are never committed to GitHub.

---

## 3. Scope probe confirmed by the user

The authenticated scope probe returned HTTP 200 and 20 application scopes, including write-level permission for:

```text
variant
product
order
inventory
profile
insight
growth_coach
question
lightening_deal
package
shipment
sbs_setting
sbs_orders
sbs_shipment
commission
promotion
voucher
invoice
search_ads
sbs_order_change_status
```

Important: the external application has broad permissions, but V40 intentionally does **not** exercise write business endpoints.

The two DARMA-facing V40 views are protected by Django login and `@require_GET`.

---

## 4. Real read-only API probe before implementation

The user ran the V40 pre-implementation read test against the live Digikala seller account.

Confirmed successful endpoints:

```text
GET /open-api/v1/orders?page=1&size=1             HTTP 200, total_rows=396
GET /open-api/v1/orders/statistics                HTTP 200
GET /open-api/v1/inventories?page=1&size=1        HTTP 200, total_rows=1382
GET /open-api/v1/profile                          HTTP 200
GET /open-api/v1/commitments?page=1&size=1        HTTP 200, total_rows=67
GET /open-api/v1/commitments/metadata             HTTP 200
GET /open-api/v1/invoices?page=1&size=1           HTTP 200, total_rows=195
```

The following Insight probes were not healthy and are intentionally excluded from V40:

```text
GET /open-api/v1/insight/overview                 HTTP 500
GET /open-api/v1/insight/sales-reports            HTTP 400 Validation failed
```

Do not reintroduce those endpoints into the dashboard until their required parameters/server behavior is separately verified.

---

## 5. V40 application files

New files:

```text
core/digikala_client_v40.py
core/digikala_views_v40.py
core/management/commands/check_digikala_v40.py
templates/core/digikala_v40.html
server_digikala_readonly_v40.sh
UI_SAFETY_V40.md
```

Changed integration files:

```text
core/urls.py
templates/core/dashboard_excel.html
static/core/number_format.js
compose.yml
```

No model or migration is added.

---

## 6. Routes

V40 adds:

```text
/digikala/          -> core.digikala_views_v40.digikala_home
/digikala/summary/  -> core.digikala_views_v40.digikala_summary
```

Both are login-protected and GET-only.

The main dashboard does **not** block on Digikala network I/O. Its Digikala card loads asynchronously from `/digikala/summary/`, so an external API outage does not prevent normal DARMA dashboard rendering.

---

## 7. Token and private-key isolation

The RSA private key stays outside the web runtime mount:

```text
/opt/darma-secrets/digikala/private_key.pem
```

The V40 deploy script creates/uses a runtime token-only directory:

```text
/opt/darma-secrets/digikala/runtime/
```

Docker mounts only that runtime directory as:

```text
/run/secrets/digikala
```

The web process receives:

```text
access_token.txt
refresh_token.txt
token_meta.json (when available)
```

It does **not** receive `private_key.pem`.

Token rotation uses an OS file lock plus atomic file replacement so concurrent Gunicorn workers do not overwrite each other's refresh result.

---

## 8. Dashboard data in V40

The main dashboard asynchronously displays:

- Open API connection state;
- current-order row count;
- Digikala inventory-variant row count;
- commitment count;
- invoice count.

The dedicated `/digikala/` page also displays:

- order shipping statistics;
- effective/non-effective commitments;
- Digikala-reported commitment penalty in **Rial**;
- token expiry metadata;
- partial endpoint errors without exposing tokens.

The values are external Digikala operational data only. They are not fed into DARMA accounting.

---

## 9. Frozen internal business boundary

V40 must not change:

- capital equation;
- finished/raw inventory valuation;
- existing Digikala receivable ledger;
- SaleLine / SaleSnapshot / SaleAllocation;
- daily XLSX importer V23;
- stock movements or shortage behavior;
- standalone returns V37;
- material Save / Apply Materials / Apply Output;
- payments / purchases / prepayments;
- Digikala receipt accounting;
- calculator V37;
- any historic fee/cost/wage semantics.

V40 is an external read integration plus token-refresh credential maintenance only.

---

## 10. Deployment safety

Rollback branch:

```text
before-digikala-readonly-v40-20260830
```

Purpose-specific deployment script:

```text
server_digikala_readonly_v40.sh
```

The script:

1. prepares an isolated token runtime directory without the RSA private key;
2. starts/checks PostgreSQL;
3. takes a full pg_dump;
4. captures live economic/business invariants;
5. enforces a V40 source-scope guard from pre-V40 main `47abb27b5b311baf7d0b96e891cd6b3059b2db2e`;
6. protects accounting/inventory/sales/material/payment/model/migration files;
7. builds the web image;
8. runs migration drift + Django checks;
9. runs V37 business regression;
10. runs `check_digikala_v40 --live` using only approved GET endpoints plus token refresh when required;
11. verifies the web mount does not contain the RSA private key;
12. compares business invariants before and after preflight;
13. recreates web/restarts Caddy;
14. reruns live checks;
15. requires exact final invariant equality.

Expected success marker:

```text
SUCCESS: DIGIKALA READ-ONLY V40 DEPLOYED
```

Do not record V40 as live until the user posts that output.

---

## 11. Future phase rule

Do not automatically convert API orders into DARMA sales merely because V40 reads them successfully.

Before replacing XLSX entry, first reconcile real API order rows against existing title-first V23 import behavior, pack quantity, Darma/Takvin brand resolution, s3 title-color semantics, SaleAllocation, SaleSnapshot, receivable idempotency, cancellation/return status, and duplicate prevention.

That future phase is accounting/stock-affecting and requires a separate version, explicit idempotency model, transaction rollback tests and deployment backup/invariant checks.
