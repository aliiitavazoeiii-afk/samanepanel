# UI / INTEGRATION SAFETY V65 — DIGIKALA ZERO GUARD SAFE MODE

V65 must remain incapable of changing a Digikala listing.

Allowed:

- read Darma HOME + KHORSHID combined stock;
- persist zero/positive notification state in AppSetting;
- send Telegram notification on a new positive->zero transition;
- GET Digikala variants only;
- map title -> Darma ProductCode using the existing title-only resolver;
- map size using the existing size aliases;
- show a read-only list of potentially affected DKPCs;
- display a visibly locked deactivation action.

Forbidden in V65:

- PUT/PATCH business requests to Digikala;
- activation/deactivation endpoint calls;
- seller-stock mutation;
- automatic or manual Digikala listing changes;
- seller-code product identity;
- any sale/accounting/inventory/material/payment/return mutation;
- any HOME/KHORSHID transfer caused by this guard.

The bot may read the existing runtime token files. The RSA private key must remain outside the bot container.

Deployment must prove:

- `core/digikala_client_v40.py` is unchanged;
- no V65 source contains activation/seller-stock mutation endpoints;
- current accounting/inventory invariants are unchanged;
- V59/V60/V62/V63/V64 regressions still pass;
- V65 rollback regression passes;
- live mapping check prints `DIGIKALA WRITE CALLS = 0`.

Only a later explicitly authorized version may add real Digikala write behavior.


Network-failure rule:

- transient timeout/connection failure on GET mapping may defer mapping without failing SAFE MODE deployment;
- deferred mapping must print that Digikala writes are zero/absent;
- Telegram preview may retry later;
- network failure must never be converted into guessed mapping or a write.


Rate-limit rule:

- public API health may be read before variant mapping;
- when health reports current >= max, do not call /variants;
- a direct HTTP 429 from /variants must stop the scan immediately with no retry;
- 429 must never be treated as permission to guess from stale/unresolved rows;
- write mode remains absent/locked.


Health endpoint rule:

- the read-only health check must call exactly `GET /open-api/v1/` with the trailing slash;
- HTML seller-panel responses are not valid Open API health responses and must not be interpreted as rate-limit data;
- this health-path correction does not authorize any Digikala write.


Variant quota rule:

- public health rate_limit is informational only and must not be assumed to be the /variants quota;
- the first successful /variants page may expose data.meta_data.rate_limit, which is authoritative for continuing that mapping scan;
- if the first /variants call is 429, stop immediately with zero retry;
- if endpoint remaining quota is less than pages still required, stop before requesting the next page;
- partial variant mappings must never be presented as complete or used for a future write decision.


Production variants paging rule:

- use page size 50 for `GET /open-api/v1/variants`; production probes returned 200 for size 50 and 429 for size 100;
- page serially only;
- `data.meta_data.rate_limit` is optional and may be absent on successful responses;
- never invent a quota when rate metadata is absent;
- stop immediately on the first real 429 and reject/cache no partial mapping;
- read-only mapping remains incapable of changing listing state.


Darma API-filter rule:

- every V65 `/variants` page request must include `search[search_term]=دارما` and `size=50`;
- the search filter only narrows API candidates and must never become product identity;
- title-only resolver + size resolver remain authoritative and fail closed;
- current production probe reduced the candidate set from 1375 rows / 28 pages to 347 rows / 7 pages;
- no unfiltered full-catalog scan is allowed in the V65 zero-guard path.


V66 special-product safety boundary:

- ProductCode/catalog support for user-confirmed active Darma models is separate from Digikala listing writes.
- mass-06 is variable-color pack10: title color determines the stock color and every sold pack consumes exactly 10 HOME units.
- fixed D-W*/D-PN/D-KM packs use explicit two-color ProductComposition only.
- mass-03 is fixed 10 × cream even if Digikala display text uses another cosmetic color label.
- KID-220, BLK-01, 1111, s1 and mass-12 remain ignored; BNR remains unmapped until the user supplies its composition.
- new special ProductSize rows may have zero price and must fail sale import until V60 date-effective pricing is configured.
- no automatic Digikala activation/deactivation is authorized by these catalog/import changes.
