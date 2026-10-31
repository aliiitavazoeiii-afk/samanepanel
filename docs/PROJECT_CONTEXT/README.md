# PROJECT_CONTEXT MANIFEST

This directory is the authoritative, detailed continuation pack for a new AI/chat.

Read `../00_NEW_CHAT_READ_FIRST.md` first. As of 2026-09-03 that entrypoint contains the complete current-chat handoff through V50, including canonical formulas/rules, the daily-report V48 incident, V49/V50 inventory-operation semantics, deployment-status uncertainty, the UI rollback history, exact do-not-repeat rules, and the one-shot next-chat prompt. Then continue through the numbered context files below; V51 through V60 are newer follow-ups after that handoff.

Then read all numbered files in order:

1. `01_BUSINESS_RULES_AND_INVARIANTS.md`
2. `02_ACCOUNTING_FORMULAS_AND_LEDGER_SEMANTICS.md`
3. `03_ACTIVE_CODE_MAP.md`
4. `04_SALES_DIGIKALA_AND_RETURNS.md`
5. `05_INVENTORY_MATERIALS_PRODUCTION_PAYMENTS.md`
6. `06_DEPLOYMENT_SAFETY_AND_RECOVERY.md`
7. `07_BUG_HISTORY_AND_DO_NOT_REPEAT.md`
8. `08_LIVE_STATE_AND_CHECKPOINTS.md`
9. `09_UI_AND_USER_WORKFLOW_CONTRACT.md`
10. `10_EXACT_BASELINES_CATALOG_AND_SPECIAL_CASES.md`
11. `11_DATA_MODEL_AND_LEDGER_RELATIONSHIPS.md`
12. `12_VERSION_TIMELINE_V18_TO_V37.md`
13. `13_NEW_CHAT_OPERATING_PROTOCOL.md`
14. `14_HANDOFF_SCOPE_AND_COMPLETENESS.md`
15. `15_CODE_FINGERPRINT_AT_HANDOFF.md`
16. `16_UI_MODERNIZATION_V38.md`
17. `17_LOGO_TYPOGRAPHY_V39.md`
18. `18_DIGIKALA_API_V40.md`
19. `19_DIGIKALA_DELIVERIES_V41.md`
20. `20_DIGIKALA_FREE_WAREHOUSE_V42.md`
21. `21_DIGIKALA_CENTER_V43.md`
22. `22_DIGIKALA_CENTER_V44.md` — fixes future-date commitment split, inventory-backed old/current products, sales endpoint fallback, physical return-warehouse detection, and multi-worker/shared API caching.
23. `23_DIA_GALLERY_V45.md` — separate daily sales channel consuming Darma color/size stock at fixed 71,000 toman per short, with its own receivable included in accounts/capital.
24. `24_NO_AUTO_TRANSFER_V46.md` — explicit new rule: every Darma-backed sale deducts HOME only and may make HOME negative; KHORSHID changes only through explicit manual transfer; post-day-3 phantom auto-transfers are reversed without changing combined stock/capital.
25. `25_BLACK_RED_UI_V47.md` — reversible presentation-only black/charcoal/red runtime theme, dark Darma logo plaque, aligned comprehensive-report KPI grid, DB/UI backup, and one-command rollback.
26. `26_DAILY_REPORT_STABILITY_V48.md` — fixes the active saved-day daily-report HTTP 500 caused by a missing child-template tag-library load and adds a read-only runtime render smoke test for every historical sales day.
27. `27_INVENTORY_OPERATIONS_V49.md` — changes manual stock correction input from delta to absolute counted stock while preserving delta audit records, and replaces one-color-at-a-time Darma transfer entry with one size + all colors in a single atomic fixed KHORSHID -> HOME batch.
28. `28_INVENTORY_OPERATIONS_V50.md` — makes both inventory-operation cards compact and changes absolute stock correction to one date/brand/size/location selection plus all colors for that brand in one atomic physical-count submit; blank means unchanged and explicit zero means final stock zero.
29. `29_INVENTORY_ADJUSTMENT_DELETE_V51.md` — adds a guarded delete/reversal action only for manual V50 `InventoryAdjustment` rows in the recent movement table; exact delta is reversed to restore the pre-correction quantity, while deletion is blocked if any newer movement exists on that same stock cell. Standalone-return V37 adjustments are explicitly excluded from this delete surface.
30. `30_INVENTORY_THRESHOLD_HIGHLIGHTS_V52.md` — presentation-only low-stock highlighting on active inventory tables: HOME below 30 red; TOTAL below 50 red and 50–99 orange; requested yellow/red/bear/black-ribbed/navy-stripe/leopard models are exempt; KHORSHID and all quantities/formulas remain unchanged.
31. `31_INVENTORY_TOTAL_RED_STRENGTH_V53.md` — presentation-only refinement of V52: in the TOTAL table, the former 50–99 orange band now uses the previous red visual, while the below-50 critical band uses a much brighter red; thresholds, exemptions, HOME and KHORSHID behavior remain unchanged.
32. `32_DAILY_SALE_DAY_DELETE_V54.md` — adds a guarded POST-only **حذف صورت روز** action beside the sales calendar on the active daily report; it atomically reverses SaleLine/Digikala, Anbaresh-backed Darma stock, variable `s3`, and Dia Gallery stock/receivable effects before deleting the SaleDay, while preserving unrelated same-date business activity and blocking unsafe historical rows without authoritative allocations.
33. `33_DARMA_COST_RULE_V55.md` — replaces Darma color/size accounting-cost drift with one date-effective per-short Darma cost source used by new Darma/Anbaresh/s3 snapshots, Dia, missing-snapshot COGS fallback, current Darma inventory valuation, returns and physical adjustments; seeds the confirmed 61,000 baseline and repairs only 12 + 14 Shahrivar 1405 cost snapshots.
34. `34_DARMA_INVENTORY_PAGE_COST_V56.md` — fixes the active inventory page that still valued Darma from legacy color×size `InventoryModelCost`; Darma cell/size/grand inventory values now use only the current V55 central rate and the add-color UI no longer exposes a separate Darma cost input.
35. `35_RETURNS_REPORT_EDIT_DELETE_V57.md` — exposes existing standalone-return V37 groups as visible return forms under `/returns/`, with grouped view, date/quantity edit, and guarded exact deletion that reverses only the return's own HOME adjustments/movements while preserving later unrelated stock movements and all sales/Digikala/accounting ledgers.
36. `36_RETURNS_MULTI_SIZE_V58.md` — removes the one-size-at-a-time entry workflow for new returns: all allowed sizes render under one shared date/form and one atomic submit, while each populated size remains a separate V57 report for exact view/edit/delete compatibility.
37. `37_COST_RULES_TAKVIN_PURCHASE_V59.md` — adds a single date-effective Novani per-short accounting cost parallel to Darma and fixes the active Takvin purchase page so purchases add exact HOME inventory alongside debt; includes an idempotent repair for today's legacy purchase rows that increased debt without adding stock.
38. `38_SALE_PRICE_ELASTIC_MULTI_V60.md` — makes Darma and Takvin selling prices date-effective by SaleDay while freezing every saved SaleLine price, routes manual/XLSX sales through the dated default, adds a Jalali start date to per-product and bulk Darma pricing, and allows one elastic payment to contain all purchased colors with independent 16/25 quantities and prices.
39. `39_DIGIKALA_ZERO_GUARD_V65.md` — SAFE MODE Telegram guard for Darma combined-stock zero transitions: sends a private alert, GETs current Digikala variants only on preview, maps title/size through existing resolvers, and shows affected DKPCs while real activation/seller-stock writes remain completely absent and locked.

Important supersession rule for V46: older statements in `01`/`05` that sale logic may auto-transfer KHORSHID -> HOME are obsolete. `24_NO_AUTO_TRANSFER_V46.md` and the explicit V46 section in `00_NEW_CHAT_READ_FIRST.md` are authoritative for sale location behavior.

Important supersession rule for V55/V56/V59: Darma and Novani accounting costs are single date-effective per-short sources. Darma uses `darma_cost_for(date)` and Novani uses `novani_cost_for(date)`. Legacy per-color/per-size `InventoryModelCost` and ProductSize unit-cost fields must not drive Darma/Novani current capital valuation or sale COGS. Takvin remains size-specific and date-effective through its own rule set.

Important V57/V58 return rule: standalone V37 returns are grouped from their existing `[standalone-return-v37] group=...` `InventoryAdjustment` audit rows. Editing/deleting a return may change only that return's HOME stock contribution and its exact adjustment/movement records. V58 new-entry submits may contain multiple sizes, but each populated size keeps its own group and all groups from one submit are created atomically. Sales, Digikala receivable, fees, account entries, payments, and unrelated stock events must remain untouched.

Important V59 Takvin-purchase rule: the active `/takvin/` Excel-style purchase page represents supplier debt in `ExcelManualSetting(key="takvin_debt")` and physical goods in Takvin HOME `StockBalance` plus exact `InventoryMovement.PURCHASE`. Saving a purchase must apply both sides once. Do not use a second Account.TAKVIN purchase ledger in this page's path.

Important V60 selling-price rule: Darma/Takvin selling-price changes are dated defaults, not historical rewrites. `SaleLine.sale_price` is frozen once saved. New manual or Digikala-imported rows use `sale_price_for(product_size, SaleDay.date)`. A future price must never be copied into today's legacy ProductSize default merely because it was scheduled today.

Important V60 elastic-payment rule: one BusinessPayment may contain many elastic colors, each with independent 16/25 quantity and unit price, while retaining one actual-paid amount. The full physical purchase payload lives in the V14 purchase ledger and edit/delete must preserve guarded atomic reverse semantics.

After these, read `UI_SAFETY_V37.md` through `UI_SAFETY_V47.md`, then current `core/urls.py`, exact active source files, and older handoff docs last.

When older docs conflict with this directory or current active code, the later explicit business-rule document + current active code wins.

The latest numerically recorded production checkpoint is now V65 SAFE MODE, confirmed by the user's posted final invariant block on 2026-09-07. V46 through V60 must not be called fully production-confirmed without their successful server output markers. V49 does have direct behavioral confirmation from the user that the new KHORSHID -> HOME transfer worked and was "عالی", but that is not the same as a preserved full invariant success block. V55 requires both `SUCCESS: DARMA COST RULE V55 DEPLOYED` and `SUCCESS: DARMA COST SHAHRIVAR V55 REPAIR APPLIED`; V56 requires `SUCCESS: DARMA INVENTORY PAGE COST V56 DEPLOYED`; V57 requires `SUCCESS: RETURNS REPORT EDIT DELETE V57 DEPLOYED`; V58 requires `SUCCESS: RETURNS MULTI-SIZE V58 DEPLOYED`; V59 requires `SUCCESS: NOVANI COST RULE + TAKVIN PURCHASE V59 DEPLOYED`, and when missing today's purchase stock exists also `SUCCESS: TODAY TAKVIN PURCHASE STOCK V59 REPAIRED`; V60 requires `SUCCESS: SALE PRICE + ELASTIC MULTI V60 DEPLOYED`. V65 safe mode requires `SUCCESS: DIGIKALA ZERO GUARD V65 SAFE MODE DEPLOYED`; that marker confirms notification/read-only mapping only and does not authorize Digikala writes.

Latest confirmed numeric production snapshot:

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

This V65 deployment-boundary snapshot is continuity data, not a reset target.

Standing rule: after every important change update context; after every confirmed successful deployment update the live checkpoint with actual server output.


## V88 pricing monitor

40. `40_PRICING_MONITOR_V88.md` — read-only Darma code+size comparison against the same Jalali day/month-to-date in the prior month, historical SaleSnapshot economics, V60 price history, adjusted-profit analysis, 10-day evaluation and filtered XLSX export. No accounting or inventory mutation.


## V102 finance consolidation

52. `52_FINANCE_HUB_CAPITAL_V102.md` — resolves the V100/V101 branch split in favor of the user's final direct Finance-root design: exactly three Finance cards, dedicated Accounts page using the existing account sources/mutations, no account preview on the hub, and one canonical current-capital calculator consumed by Comprehensive Report without changing the economic formula.

**Current GitHub continuation line:** `v102-finance-hub-consolidated`.

V101's expandable Finance submenu is superseded by V102 and must not be reintroduced unless the user explicitly changes this UX rule.


## V103 native Finance navigation

53. `53_NATIVE_FINANCE_NAV_V103.md` — replaces the V102 post-render Finance-navigation rewrite with a native direct link in `base.html`. The Finance hub remains exactly three cards and Accounts remains `/finance/accounts/`; no business/accounting logic changes.

**Current GitHub continuation line:** `v103-native-finance-nav`.


## V104 Finance KPIs and calculator

54. `54_FINANCE_KPIS_CALCULATOR_V104.md` — reuses one six-balance KPI source across Payments and Finance, improves Accounts KPI typography, and rebuilds Calculator as target-profit pricing + direct profit calculation + live current profitability for every active Darma/Takvin ProductSize.

**Current GitHub continuation line:** `v104-finance-kpis-calculator`.


## V105 margin semantics + code summary + material KPIs

55. `55_MARGIN_CODE_SUMMARY_MATERIAL_KPIS_V105.md` — changes calculator target percentage to sale-margin semantics, collapses profitability to one summary row per code with expandable size details, moves material-report KPI cards below the title, improves number/unit typography, and adds all-history Darma average cut for the five base colors.

**Current GitHub continuation line:** `v105-margin-code-summary-material-kpis`.


## V106 corrected continuation

56. `56_PERSON_PAYMENTS_THREE_DELIVERIES_V106.md` — continues V105 directly, preserves native direct Finance navigation + V104/V105 Finance/calculator/material work, adds person-account payees with atomic reverse semantics, and splits each tailor-delivery output cell into three cumulative internal inputs.

**Current GitHub continuation line:** `v106-person-payments-three-deliveries`.

**Do not use:** `v102-person-payments-three-deliveries`. It was accidentally based on obsolete V101 and reintroduced the Finance submenu superseded by V102/V103.


## V108 FINAL STABLE BASELINE

57. `57_FINAL_STABLE_BASELINE_V108.md` — canonical continuation baseline built from the complete V106/V105 lineage. It server-side removes the obsolete Comprehensive Report finance/account boxes, preserves native direct Finance navigation + exactly three Finance cards + six KPI balances, preserves final V105 Calculator semantics, V106 person-account payments and three delivery boxes, and adds five open-work base-color cards below the existing six material KPIs.

**Canonical future development line after production confirmation:** `stable-final-2026-10-04`.

After `SUCCESS: FINAL STABLE BASELINE V108 DEPLOYED`, do not start new work from older V97-V107 branches.


## V109 material color rolls + collapsed-summary UI

58. `58_MATERIAL_COLOR_ROLLS_SUMMARY_UI_V109.md` — based directly on the V108 stable baseline; adds per-color open-work fabric-roll counts to the five base-color cards and stacks/enlarges the collapsed material-sheet summary labels without changing business logic.

**Current feature line:** `v109-material-color-rolls-summary-ui`.


## V110 compact material summary box grid

59. `59_COMPACT_MATERIAL_SUMMARY_BOX_GRID_V110.md` — continues V109 and restores the saved material-sheet collapsed header to a compact horizontal five-box desktop layout while preserving V109 color-roll cards, V106 three-delivery semantics, and the V108 stable baseline.

**Current feature line:** `v110-material-summary-box-grid`.


## V111 canonical product definition

60. `60_PRODUCT_DEFINITION_V111.md` — fourth product-definition card; independent title field via additive migration 0018; direct use of existing ProductCode/ProductComposition/ProductSize in color catalog and manual daily orders; Darma-to-Anbaresh title mirror.

**Current feature line:** `v111-product-definition-catalog-sales`.


## V112 — Selected destination on tailor delivery sync

61. `61_TAILOR_DELIVERY_DESTINATION_V112.md` — replaces generic confirm with
one Home/Khorshid picker per material sheet, writes only new delivered output
to that stock location, keeps historical quantities where they were, and
reconciles tailor wages automatically. Uses additive migration 0019.

**Current feature line:** `v112-tailor-delivery-destination`.


## V113 production unit-cost calculator
62. `62_PRODUCTION_COST_V113.md` — third read-only calculator beside target-margin and profit calculators. Inputs for per-kg fabric price, roll weight, pieces, elastic weight/price and dozen wage; no persistent state writes. Current feature branch: `v113-unit-production-cost-calculator`.


## V114 — clean icon navigation
63. `63_CLEAN_ICON_SIDEBAR_V114.md` — nine direct sidebar links; 72px icon-only desktop rail on main-content hover; inventory Returns; two-card Definitions landing; no backend business changes. Branch: `v114-clean-icon-sidebar-navigation` (parallel UI work should merge, never overwrite).


## V115 stable sidebar and comprehensive report
64. `64_STABLE_SIDEBAR_REPORT_V115.md` — fixes sidebar reload bounce, compact logout, sales metrics layout, six shared finance KPIs and relocates Darma pricing monitoring into Comprehensive Report. New branch: `v115-stable-sidebar-report-dashboard`.


## V116 registered fabric-roll count
65. `65_FABRIC_ROLL_COUNT_V116.md` — distinct registered fabric codes per color, explicit uncoded-sheet diagnostics, no business-state mutation. Branch: `v116-fabric-roll-count-audit`.


### V117 integrated UI and fabric counts

Continuation branch: `v117-unified-ui-fabric-count`, descended from the newest `v116-fabric-roll-count-audit` (Oct 14), with V116 SVG sidebar and report-priority changes carried forward from `v116-smooth-rail-report-priority`. Run `bash server_unified_ui_fabric_v117.sh`; it runs the V116 UI check, V110 material summary check and V116 white/pink roll audit, plus legacy immutable finance/production checks. No migrations, stock transfers or data reconciliation are performed. Roll card counts only distinct saved fabric codes; current stock remains a separate physical quantity in kilograms.


### V118 — unapplied coded fabric rolls and total weight

66. `66_UNAPPLIED_FABRIC_WEIGHT_V118.md` — Count distinct nonempty fabric codes only on color rows without recorded positive fabric consumption, separately from finished output. Show the all-time cumulative delivered fabric weight for each Darma base color. V117 UI remains. Deploy with `server_unapplied_fabric_v118.sh` instead of older scripts.


### V119 — Wholesale Novani

67. `67_NOVANI_WHOLESALE_V119.md` — independent wholesale buyer, small invoice cards, Novani stock, Pedram-to-tailor offset, per-buyer prices and Excel export. Single schema migration with registered Pedram; deploy through `server_novani_wholesale_v119.sh` (not older scripts).


### V120 — Wholesale color/size entry

68. `68_NOVANI_COLOR_SIZE_MATRIX_V120.md`: choose a color once to reveal six-size Novani quantity matrix with one wholesale unit price per color; combine multiple colors into one V119 atomic invoice, without touching existing sidebar/finances/exports. Deploy `server_novani_color_matrix_v120.sh`.


### V121 — Correct Pedram claims / repair old invoice

69. `69_PEDRAM_RECEIVABLE_V121.md` — fix wholesale signed Pedram shared tailor balance (+gross, not -gross), correct old 144,384,000-toman invoice once (+288,768,000 relative to wrong posted state; no extra stock movement), show actual net signed person balance, and thousands separators for all wholesale entry fields. Guarded `server_pedram_receivable_v121.sh`.


### V122 — Net material delivery and open carryover

70. `70_MATERIAL_NET_CARRYOVER_V122.md`: per-color total signed net after offsetting roll surpluses against shortages, registered delivery separated from stock-applied, current Jalali month plus pending earlier-month sheets, V122 live pink audit. Deploy read-only guarded `server_material_net_open_v122.sh`.


### V123 — Material colors and two-way inventory transfer

71. `71_MATERIAL_COLOR_APPLY_BIDIRECTIONAL_TRANSFER_V123.md` — archive every prior Jalali month, show only this month's raw-fabric-unapplied colors upstairs, add independent color-specific fabric/elastic apply, bidirectional warehouse/home transfer with no-refresh working session and default reset on page reload. Deploy via `server_material_color_transfer_v123.sh`.


### V124 — Payment fabric purchase color choices

72. `72_PAYMENT_REGISTERED_COLORS_V124.md` — include all live Darma-registered inventory colors in new and edit payments, retain historic nine color keys, accept new colors in purchase validation; no finance formula or stock write changes. Guarded `server_payment_colors_v124.sh` requires installed V123.


73. V125 `73_JALALI_MATERIAL_ARCHIVE_REPORT_V125.md` — archived Jalali month KPI selection on month-header click; restores Mehr 1405 summary without carrying into Aban and separately counts unfinished tailoring deliveries after fabric has been applied.


75. V126 `74_PAYMENT_HISTORY_FILTERS_V126.md` — payments Jalali date range filters matching receipts, all-time unfiltered amount, 100-row pages, no financial ledger writes, guarded installer.
