# 39 — DIGIKALA ZERO-STOCK TELEGRAM GUARD V65

Status: PRODUCTION-CONFIRMED SAFE MODE as of 2026-09-07. The user posted the final marker `SUCCESS: DIGIKALA ZERO GUARD V65 SAFE MODE DEPLOYED`.

## User requirement

When a Darma color/size reaches zero in **combined internal inventory**:

```text
combined = HOME + KHORSHID
```

the existing Telegram inventory bot should notify the authorized user, for example:

```text
سفید / XL = 0
```

The user ultimately wants an approval action that can deactivate every Digikala variant for the same size whose Darma product depends on that color.

## V65 safety boundary

V65 is deliberately the read-only discovery/approval-preview phase.

It DOES:

- scan Darma combined stock about every 60 seconds;
- persist only zero/positive transition markers in AppSetting so restarts do not spam;
- seed currently-zero cells silently on the first bot scan after deploy;
- notify only when a cell later changes from positive to zero;
- provide a Telegram button to preview affected Digikala variants;
- GET current Digikala `/open-api/v1/variants`;
- resolve product identity exclusively from Digikala title text through `title_product_resolver_v27`;
- resolve size through the existing `SIZE_ALIASES` / `_resolve_size` path;
- handle variable-color Darma `s3` from the title color;
- display seller variant id, DKPC, active state, seller stock and Digikala warehouse stock.

V65 DOES NOT:

- call `PUT`, `PATCH` or business `POST` endpoints on Digikala;
- call `/variants/<id>/activation`;
- call `/variants/<id>/seller-stock` for mutation;
- deactivate any current Digikala product;
- change any internal SaleLine, SaleSnapshot, SaleAllocation, StockBalance or InventoryMovement;
- change accounting, capital, receivable, payments, returns, materials or production;
- use seller code to identify a product.

## Exact affected-product rule

For a fixed-composition Darma product and selected size:

- the product is affected only if its active ProductSize for that size exists;
- its ProductComposition contains the zero color with positive quantity;
- the current Digikala title resolves to that exact Darma product and size.

For variable-color `s3`:

- fixed composition is not invented;
- the selected color must be one of the supported title colors;
- the Digikala title itself must identify the same color and size.

Unknown or ambiguous titles fail closed and are reported as unresolved; they are never guessed.

## Zero transition semantics

Only combined owned Darma stock is watched:

```text
HOME + KHORSHID <= 0 -> zero
HOME + KHORSHID > 0  -> positive
```

A first V65 bot startup initializes marker state without sending a burst for historical zero cells.

After that:

```text
positive -> zero  => one Telegram alert
zero -> zero      => no repeat
zero -> positive  => marker reset
positive -> zero  => alert again
```

This is independent of the existing 09:00 grouped production/transfer alert.

## Telegram flow in V65

Zero alert:

```text
⛔ موجودی کل دارما صفر شد
سفید / XL
[بررسی کدهای متاثر]
[فعلاً کاری نکن]
```

Preview shows the real read-only mapping. The action button is explicitly locked:

```text
🔒 غیرفعال‌سازی فعلاً قفل است
```

A later version may enable real Digikala writes only after the user reviews actual VPS mapping output and explicitly authorizes the write phase.

## Existing bot/token architecture

The existing bot service remains `run_inventory_bot`.

V65 mounts only the existing Digikala runtime token directory into the bot:

```text
/opt/darma-secrets/digikala/runtime -> /run/secrets/digikala
```

The RSA private key is still not mounted.

## Regression

```bash
python manage.py check_digikala_zero_guard_v65
python manage.py check_digikala_zero_guard_v65 --live-map
```

The normal check uses synthetic title mapping and an atomic rollback zero-transition test.

`--live-map` performs GET-only current Digikala mapping and prints:

- total variants read;
- title/size resolution counts;
- Darma resolution count;
- unresolved Darma-like titles;
- current zero cells and how many active DK variants each would affect;
- `DIGIKALA WRITE CALLS = 0`.

## V59 regression correction carried with V65

The Novani resolver itself already filters by date. The old V59 regression incorrectly treated the literal cost 65,000 as proof of leakage on the prior date. That can false-fail if a legitimate earlier rule is also 65,000.

The regression is corrected to:

1. capture the exact prior-date cost before inserting a future test rule;
2. use a unique sentinel future cost;
3. assert the future date resolves to the sentinel;
4. assert the prior date remains exactly equal to its captured value.

No Novani accounting resolver or business rule is changed by this regression correction.

## Deployment

Rollback branch:

```text
before-digikala-zero-guard-v65-20260907
```

Deploy script:

```bash
bash server_digikala_zero_guard_v65.sh
```

Expected final marker:

```text
SUCCESS: DIGIKALA ZERO GUARD V65 SAFE MODE DEPLOYED
```

This marker confirms only the safe Telegram/read-only phase. It does NOT mean Digikala write/deactivation is enabled.


## V65 network-resilience patch

A production safe-mode run showed that `GET /open-api/v1/variants` can exceed the original 8-second read timeout.

The safe mapper now retries the same GET-only operation with increasing per-request timeouts:

```text
15s -> 30s -> 45s
```

with a short backoff between attempts.

If all read attempts still fail during deployment:

- deployment reports `LIVE DIGIKALA MAP DEFERRED`;
- deployment may continue because V65 contains no Digikala write path;
- the Telegram bot remains capable of zero-stock notifications;
- clicking the preview button later retries the GET path;
- any preview network failure returns a Telegram error message and performs zero Digikala changes.

This behavior is intentionally different from a future write-enabled phase: once real deactivation is ever introduced, successful live mapping and explicit user confirmation must become mandatory again before any write.

The deploy script also sets `COMPOSE_IGNORE_ORPHANS=1` only to suppress the harmless warning caused when the already-running Telegram bot exists outside a base-compose command. It does not remove or recreate an orphan by itself, and `--remove-orphans` is not used.


## Confirmed production checkpoint — 2026-09-07

The user posted the successful production boundary with:

```text
SUCCESS: DIGIKALA ZERO GUARD V65 SAFE MODE DEPLOYED
```

The running bot reported:

```text
Telegram bot connected: @darmageneralbot
Authorized Telegram users: [107305979]
V65 zero guard state initialized safely; existing zero cells were not notified.
```

Final invariant snapshot:

```text
CAPITAL=5916084564
MELLAT=0
MOFID=24731000
FINISHED=1186669000
RAW=2807366700
DIGI=940899364
DIA=497000
TAKVIN_DEBT=65880000
DARMA_QTY=11432
TAKVIN_QTY=1429
NOVANI_QTY=3630
SALES=484
PAYMENTS=9
RECEIPTS=6
RAW_ROWS=53
MOVEMENTS=5225
TAKVIN_PURCHASES=10
```

Backup:

```text
backups/before-digikala-zero-guard-v65-20260907-205127.sql
```

This confirms only the V65 read-only Telegram guard. Digikala activation/write is still absent and locked.


## Rate-limit guard patch after production verification

A manual production `--live-map` check returned a real Digikala response:

```text
429 Too Many Requests
```

This proves the API endpoint was reachable and authenticated enough to return a rate-limit response, but the current request window was exhausted.

V65 now treats 429 differently from transport timeout:

- it first reads the public Open API health endpoint `GET /open-api/v1`;
- the health payload exposes `rate_limit.max`, `rate_limit.current`, and `resetTime`;
- if `current >= max`, V65 sends **zero** `/variants` requests;
- if `/variants` itself returns 429, V65 stops immediately with **zero immediate retries**;
- timeout/network errors may still use the bounded 15/30/45-second retry path;
- no 429 path can trigger a Digikala write.

New safe diagnostic:

```bash
python manage.py check_digikala_zero_guard_v65 --api-health
```

This performs only the public health GET and prints the current/max/remaining/reset window.

The regression command now simulates both an already-exhausted health window and a direct 429 response, and asserts that `/variants` is skipped or called only once respectively.


## Health endpoint trailing-slash fix

Production health testing returned the seller-panel HTML when V65 requested:

```text
/open-api/v1
```

The Digikala Open API health root requires the API-base form with the trailing slash:

```text
/open-api/v1/
```

The reference client uses base URL `https://seller.digikala.com/open-api/v1` plus an empty health endpoint; its HTTP client normalizes that request to the trailing-slash API root.

V65 now uses the explicit trailing-slash path and its regression asserts the exact request:

```text
GET /open-api/v1/
```

No authenticated variant endpoint, listing state, stock, accounting, or inventory behavior is changed by this patch.


## Variant-endpoint quota correction

A production sequence showed:

```text
public health: current=1 max=33 remaining=32
immediate GET /variants: 429 Too Many Requests
```

Therefore the public health rate-limit bucket is **not authoritative for the authenticated `/variants` endpoint**. It remains useful only as a general API health diagnostic.

The authoritative quota for variant paging is the successful `GET /variants` response itself:

```text
data.meta_data.rate_limit
```

V65 now:

1. sends exactly one first-page request:
   `GET /open-api/v1/variants?page=1&size=100`;
2. if that first request is 429, stops immediately with zero retry;
3. if page 1 succeeds, reads its `pager.total_pages` and `meta_data.rate_limit`;
4. calculates whether the endpoint-specific remaining quota is enough for every remaining page;
5. if quota is insufficient, stops before page 2 and rejects partial mapping;
6. if quota is sufficient, reads pages serially, one at a time;
7. re-checks endpoint quota after every successful page;
8. never accepts an incomplete mapping and never converts rate-limit failure into a Digikala write.

Public `GET /open-api/v1/` health is informational only and no longer gates `/variants`.

This correction does not change Telegram zero detection, internal stock, sales, accounting, or any Digikala listing state.


## Production page-size finding

A direct production probe on the same authenticated `/variants` endpoint showed:

```text
size=1  -> HTTP 200
size=50 -> HTTP 200
size=100 -> HTTP 429 Too Many Requests
```

For the current seller account, `size=50` returned:

```text
item_per_page=50
total_pages=28
total_rows=1375
```

The successful response did **not** include `data.meta_data.rate_limit`.

V65 therefore now uses:

```text
GET /open-api/v1/variants?page=N&size=50
```

and reads pages strictly serially.

If `meta_data.rate_limit` is present, V65 may use it to stop before the next page when the remaining quota is known to be insufficient.

If rate metadata is absent, V65 does not invent quota values. It continues serially and treats the first real HTTP 429 as a hard stop with zero immediate retry. Any partial mapping is discarded and never cached or accepted as complete.

No Digikala write endpoint is introduced by this change.


## Darma-filtered variants read

A production read-only probe confirmed Digikala's supported variant search filter:

```text
search[search_term]=دارما
```

With `size=50`, the same seller account returned:

```text
unfiltered: total_rows=1375, total_pages=28
Darma filter: total_rows=347, total_pages=7
```

Sample returned titles were Darma products such as PACK-5, D-220 and rah-220.

V65 now makes the API-side Darma search term mandatory in every variant page request:

```text
GET /open-api/v1/variants?page=N&size=50&search[search_term]=دارما
```

The API filter is only a bandwidth/quota reduction mechanism. It does **not** identify a product. Every returned row must still pass the existing title-only product resolver and size resolver; unknown or ambiguous rows fail closed.

This reduces the current production candidate set from 28 pages to 7 pages while preserving the V65 read-only boundary and zero Digikala writes.


## Unresolved Darma diagnostics

After the first successful production Darma-filtered live map, 347 Darma candidate rows were read, 204 resolved to a local Darma product+size, and 143 remained fail-closed.

The live-map diagnostic now classifies unresolved Darma-like rows as:

- product resolver failure;
- size resolver failure;
- both product and size unresolved;

and prints a bounded sample of unresolved titles/model candidates. This remains GET-only and does not change Digikala or business data.


## V66 special Darma product mapping (user-confirmed)

The user confirmed that several currently-selling Digikala title models are real Darma products that were not yet registered as ProductCode rows in the site.

V66 definitions:

- `mass-03`: pack 10, fixed composition = 10 × cream.
- `mass-06`: pack 10, variable single-color product. The title color is authoritative and one sold pack consumes 10 units of that color. Allowed colors: white, black, pink, navy, red, yellow. Title color `کالباسی` maps to the canonical pink stock color.
- `D-WP`: pack 2 = white + pink.
- `D-WN`: pack 2 = white + navy.
- `D-WK`: pack 2 = white + cream.
- `D-WB`: pack 2 = white + black.
- `D-PN`: pack 2 = pink + navy.
- `D-KM`: pack 2 = black + cream.

Explicitly ignored/inactive title models remain fail-closed:

`KID-220`, `BLK-01`, `1111`, `s1`, `mass-12`.

`BNR` is currently selling but its pack/color composition has not been supplied, so it remains intentionally unresolved/fail-closed.

The special-product sync creates/updates only the confirmed active products above. It does not create ignored or BNR rows. Existing sale prices are preserved; new ProductSize rows start with zero default sale price, and V60 date-effective sale-price rules must be configured before a sale import can create a new priced line.

No Digikala write/deactivation endpoint is added by V66.


## V67 p12 composition correction

User-confirmed p12 composition is now:

- black ×2
- white ×2
- navy ×2
- pink ×2
- cream ×2
- gray ×2

Red and yellow are no longer part of p12.

The canonical product catalog and the live ProductComposition row are updated through a targeted command. Existing p12 prices are preserved and no historical SaleLine/SaleSnapshot/SaleAllocation row is rewritten by this sync.

Zero-guard dependency follows live ProductComposition, so p12 must no longer be considered affected by red/yellow zero cells and must instead be considered affected by cream/gray zero cells.

The Digikala API field `warehouse_stock` (shown in diagnostics as DK_WH) is informational marketplace warehouse stock metadata, not a Darma product code.


## V68 confirmed Digikala deactivation gate

V68 adds the first Digikala mutation path, but it remains strictly user-confirmed and fail-closed.

Endpoint contract (scope: `variant`):

```text
PUT /open-api/v1/variants/{seller_variant_id}/activation
{"activation": false}
```

Safety gates:

1. Zero transition itself never writes; it only sends the existing Telegram alert.
2. Preview is GET-only.
3. The user must press a separate prepare button.
4. Prepare performs a fresh full Darma mapping and creates a SHA-256 plan fingerprint.
5. The final confirmation token is one-time, bound to the authorized Telegram user/chat, and expires after 90 seconds.
6. At final confirmation, V68 fetches the complete Darma mapping again. Any plan/fingerprint change aborts before the first PUT.
7. Every eligible variant is then fetched individually and must still resolve from title to the same Darma product, same size, and the same zero color dependency.
8. A variant with `warehouse_stock > 0` or `on_the_way_stock > 0` is blocked and never written by V68.
9. Unresolved Darma-like titles are outside write scope and are never guessed.
10. The internal combined stock is checked again immediately before writes; if it is positive, the operation aborts.
11. PUT mutations are never retried after arbitrary network/API failure. The only authenticated retry is after an explicit HTTP 401 token refresh.
12. After every acknowledged PUT, V68 GETs that variant again and expects `active=false`.
13. If a multi-variant operation partially succeeds and a later request fails, V68 stops immediately, reports the acknowledged successful variant IDs, and requires a new preview for continuation.

Production kill switch:

```text
DIGIKALA_ZERO_GUARD_WRITE_ENABLED=0
```

Keep it at `0` during deployment and regression. Enable it only after the mocked regression, GET-only token scope check, and GET-only live audit pass.

Regression / preflight:

```bash
python manage.py check_digikala_zero_guard_v68
python manage.py check_digikala_zero_guard_v68 --api-scope
python manage.py check_digikala_zero_guard_v68 --live-audit
```

The latter two modes are GET-only and never call the activation endpoint.
