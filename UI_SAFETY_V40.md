# UI / INTEGRATION SAFETY — V40 DIGIKALA READ-ONLY

V40 adds direct Digikala Open API visibility to DARMA General.

## Allowed V40 behavior

- login-protected GET page `/digikala/`;
- login-protected GET JSON summary `/digikala/summary/`;
- GET-only Digikala calls for orders, order statistics, inventory, profile, commitments and invoices;
- official POST `/open-api/v1/auth/refresh-token` only when the Access Token expires;
- atomically replace both returned token files;
- show external Digikala operational counts/status on the dashboard;
- keep Digikala network failure isolated from the normal internal dashboard render.

## Forbidden V40 behavior

V40 must not:

- create/update/delete `SaleLine`;
- create/update/delete `SaleSnapshot` or `SaleAllocation`;
- modify `StockBalance` or create inventory movements;
- modify Digikala receivable/account entries;
- change capital or inventory valuation;
- replace or invoke the XLSX importer from API data;
- change returns, payments, material reports, production or calculator semantics;
- call Digikala write endpoints for orders, inventory, products, variants, shipments or invoices;
- mount the RSA private key into the web container;
- expose Access Token, Refresh Token, authorization code or private key in HTML/JSON/log output.

## Confirmed external probe baseline before V40

Successful live GET probes:

```text
orders: 200, 396 rows
orders/statistics: 200
inventories: 200, 1382 rows
profile: 200
commitments: 200, 67 rows
commitments/metadata: 200
invoices: 200, 195 rows
```

Excluded after live failures:

```text
insight/overview: HTTP 500
insight/sales-reports: HTTP 400 Validation failed
```

## Secret boundary

Host RSA private key remains at:

```text
/opt/darma-secrets/digikala/private_key.pem
```

Only token runtime files under:

```text
/opt/darma-secrets/digikala/runtime/
```

are mounted to `/run/secrets/digikala` in the web container.

## Deployment invariant rule

V40 deployment must compare and preserve exactly:

```text
CAPITAL
FINISHED
RAW
DIGI
DARMA
TAKVIN
NOVANI
SALES
ACCOUNT_ENTRIES
```

Expected deployment marker:

```text
SUCCESS: DIGIKALA READ-ONLY V40 DEPLOYED
```

Until the user posts that output, V40 is code prepared on GitHub, not confirmed production state.
