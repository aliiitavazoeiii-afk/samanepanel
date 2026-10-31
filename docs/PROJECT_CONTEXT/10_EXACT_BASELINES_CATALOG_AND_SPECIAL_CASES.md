# 10 — EXACT BASELINES, CATALOG AND SPECIAL CASES

This file contains exact reference data that has repeatedly mattered in debugging. Historical baselines are labeled clearly; do not apply them to current live state without explicit user intent.

Last synchronized: 2026-08-29 after confirmed V37 live deployment.

---

# PART A — DARMA PHYSICAL END-OF-DAY 3 SHAHRIVAR BASELINE

## 1. Meaning of this baseline

This is the authoritative physical Darma count **after sales of 1405/06/03**.

Therefore if restoring this historical baseline:

- preserve the 3 Shahrivar SaleDay as history;
- do not reapply 3 Shahrivar sales after setting baseline;
- later sales must be handled separately.

Correct totals:

```text
HOME=4,585
KHORSHID=8,890
TOTAL=13,475
```

Per-size totals:

```text
M=1,948
L=3,807
XL=2,529
XXL=3,716
3XL=1,071
4XL=404
```

---

## 2. Exact HOME matrix

Format:

```text
color: M, L, XL, XXL, 3XL, 4XL
```

```text
مشکی:          54, 190, 134, 134, 48, 78
سفید:         150, 168, 101,  86, 93, 79
سرمه ای:       36, 149, 157, 115,110, 87
صورتی:         97, 225,  68, 153, 33, 81
کرم:          169, 245, 245, 212, 77, 79
قرمز:         150,   0,   0,   0,  0,  0
زرد:            0,  80,   0,   0,  0,  0
طوسی:          42,  17,  43,   0,  0,  0
راه راه:       41,  15,  22,  90, 36,  0
راه راه طوسی:  15,   6,  48,  29, 31,  0
برعکس مشکی:    18,  12,  16,  25, 14,  0
برعکس سفید:    16,   9,  24,  23,  5,  0
برعکس سرمه ای:  0,  11,  51,  29, 14,  0
```

HOME total = 4,585.

---

## 3. Exact corrected KHORSHID matrix

Use the corrected physical values, **not** the original V18 transcription.

```text
مشکی:         180, 460, 350, 620,   0, 0
سفید:         120,  70,   0, 200,  10, 0
سرمه ای:        0, 400, 500, 730, 150, 0
صورتی:        120, 450,   0, 250,   0, 0
کرم:          110, 600, 300, 400,   0, 0
قرمز:         160,   0,   0,   0,   0, 0
زرد:            0,  30,   0,   0,   0, 0
طوسی:          40,  70,   0,   0,   0, 0
راه راه:      170,  90,   0,   0,   0, 0
راه راه طوسی: 200, 310, 400, 410, 250, 0
برعکس مشکی:    30,  70,  60,  60,  70, 0
برعکس سفید:    30,  70,  10,  90,  70, 0
برعکس سرمه ای:  0,  60,   0,  60,  60, 0
```

KHORSHID total = 8,890.

Critical corrected cells:

```text
KHORSHID کرم XXL = 400
KHORSHID قرمز XXL = 0
```

Original V18 transcription had cream260/red140, which was wrong.

---

## 4. Total color quantities at this baseline

```text
مشکی          2,248
سفید          1,077
سرمه ای       2,434
صورتی         1,477
کرم           2,297
قرمز            450
زرد              110
طوسی             212
راه راه           464
راه راه طوسی    1,699
برعکس مشکی        375
برعکس سفید        347
برعکس سرمه ای     285
```

Important reference totals/cells:

```text
Darma cream 3XL total = 77
Darma grey 4XL total = 0
Darma red XXL total = 0
Darma red M total = 310 (HOME150 + KH160)
all corrected non-M red cells = 0
```

---

## 5. Relevant physical baseline commands

Historical/reference files:

- `core/management/commands/reconcile_darma_physical_v18.py`
- `server_darma_physical_v18.sh`
- `server_correct_khorshid_red_cream_xxl_v20.sh`
- day-3 exact reconcile V32 files/scripts in repo.

Before using any of them, read current implementation and confirm the historical target is actually what user wants.

---

# PART B — 31 MORDAD HISTORICAL DARMA BASELINE

## 6. Aggregate totals from user workbook

Historical `mojodi 31 mordad.xlsx` baseline used during forensic rebuild:

```text
TOTAL = 14,864
M     = 2,109
L     = 4,096
XL    = 3,002
XXL   = 4,106
3XL   = 1,143
4XL   =   408
```

At 61,000:

```text
906,704,000 toman
```

Workbook included negative historical cells such as examples:

```text
قرمز L=-34
قرمز XL=-29
قرمز XXL=-39
زرد M=-4
طوسی XXL=-3
```

Those values were not automatically zeroed because the workbook was being used as historical accounting truth.

The workbook aggregate did not contain HOME/KHORSHID split. V31 logic preserved KHORSHID and adjusted HOME to reach workbook totals.

This is history only.

---

# PART C — DARMA CATALOG

## 7. Current known Darma code set

Current intended active Darma codes include:

```text
D 110
D 220
D 330
D 440
D 550
D 660
pack 5
880
990
770
p12
400
06
rah-110
pgw
rah-220
op
s3   # variable color, special import semantics
```

Historical unwanted standalone aliases `rah` and `blk` must not be reintroduced as active products.

---

## 8. Current fixed Darma compositions from source catalog

### D 110

```text
سرمه ای x1
سفید x1
کرم x1
```

### D 220

```text
سفید x1
صورتی x1
کرم x1
```

### D 330

```text
مشکی x1
سفید x1
صورتی x1
```

### D 440

```text
مشکی x1
سفید x1
سرمه ای x1
```

### D 550

```text
مشکی x1
سرمه ای x1
صورتی x1
```

### D 660

```text
مشکی x1
سرمه ای x1
کرم x1
```

### pack 5

```text
مشکی x1
سفید x1
سرمه ای x1
صورتی x1
کرم x1
```

### 880

```text
مشکی x1
سفید x1
کرم x1
```

### 990

```text
مشکی x1
قرمز x1
زرد x1
```

### 770

```text
سفید x1
سرمه ای x1
صورتی x1
```

### p12

```text
مشکی x2
سفید x2
سرمه ای x2
صورتی x2
قرمز x2
زرد x2
```

### 400

```text
مشکی x1
سرمه ای x1
صورتی x1
طوسی x1
```

### 06

**Correct current source:**

```text
مشکی x1
سفید x1
سرمه ای x1
صورتی x1
کرم x1
طوسی x1
```

Never replace cream with red.

### rah-110

```text
راه راه x1
سفید x1
سرمه ای x1
```

### pgw

```text
سفید x1
صورتی x1
طوسی x1
```

### rah-220

```text
راه راه طوسی x1
سفید x1
طوسی x1
```

### op

```text
برعکس مشکی x1
برعکس سفید x1
برعکس سرمه ای x1
```

### s3

Variable-color pack-1 product. No fixed composition should be assumed for Digikala row allocation.

---

## 9. Darma selling-price source table for standard fixed pack sizes

`core/product_catalog.py` includes current fixed pack price tables by size for pack counts 3/4/5/6.

At handoff source:

### pack 3

```text
M     385,000
L     405,000
XL    430,000
XXL   455,000
3XL   470,000
4XL   495,000
```

### pack 4

```text
M     485,000
L     515,000
XL    545,000
XXL   570,000
3XL   610,000
4XL   630,000
```

### pack 5

```text
M     570,000
L     618,000
XL    658,000
XXL   701,000
3XL   743,000
4XL   790,000
```

### pack 6

```text
M     699,000
L     755,000
XL    795,000
XXL   860,000
3XL   920,000
4XL   980,000
```

These are source catalog defaults, not a guarantee that every live ProductSize price still equals source if user edited pricing later. Inspect live DB/current settings before overwriting.

---

# PART D — TAKVIN CATALOG/COST

## 10. Known Takvin codes

```text
12
987
06مشکی
سفید 09
502
4444
654-1
555-1
2222
1010
787
23
16
gg
403
```

Active standard sizes:

```text
M, L, XL, XXL
```

Some niche source catalog rows may only have a subset of size prices (e.g. special codes). Do not activate missing sizes globally without checking ProductSize/current catalog.

---

## 11. Historical/default Takvin accounting cost set

Date-effective Takvin sale COGS defaults historically seeded as:

```text
M     108,000
L     126,000
XL    139,500
XXL   153,000
```

Current settings/rules may have later effective sets. For historical SaleLine COGS, SaleSnapshot must win.

---

## 12. Takvin Digikala 1-654 alias

Digikala title model:

```text
1-654
```

maps to canonical internal:

```text
654-1
```

Do not create a second `1-654` product row.

---

# PART E — COLORS AND NORMALIZATION

## 13. Darma base colors/models

```text
مشکی
سفید
سرمه ای
صورتی
کرم
قرمز
زرد
طوسی
راه راه
راه راه طوسی
برعکس مشکی
برعکس سفید
برعکس سرمه ای
```

`core/brand_colors.py` normalizes Persian/Arabic character variants, spacing and ZWNJ where applicable.

Do not treat superficial text spacing variants as new colors.

---

## 14. Historical mapping `راه راه سرمه‌ای`

In the 31 Mordad workbook workflow, `راه راه سرمه‌ای` was mapped to internal `راه راه` according to that workbook/import interpretation.

If a new workbook contains a similar label, inspect context before creating a new color.

---

# PART F — S3 VARIABLE COLOR

## 15. Case-sensitive color hints

Known business mapping:

```text
s2 = کرم
s3 = مشکی
S3 = صورتی
s5 = سرمه‌ای
```

The lowercase/uppercase distinction matters.

White may be inferred from explicit title text.

Product identity remains title-first under V27; seller code is discarded by V23 parser.

---

# PART G — NOVANI

## 16. Novani current production sizes

```text
S
M
L
XL
XXL
3XL
```

Do not add 4XL to Novani unless user explicitly changes the rule.

---

## 17. Novani delivered block used in V34/V35

Exact delivered row totals:

```text
مشکی 710
  S=80, M=150, L=160, XL=160, XXL=90, 3XL=70

سفید 660
  S=70, M=150, L=150, XL=150, XXL=70, 3XL=70

سرمه‌ای 750
  S=80, M=170, L=170, XL=170, XXL=80, 3XL=80

صورتی 700
  S=60, M=160, L=160, XL=160, XXL=80, 3XL=80

کرم 810
  S=90, M=180, L=180, XL=190, XXL=90, 3XL=80
```

Grand total:

```text
3,630
```

At 110,000 per dozen:

```text
33,275,000 toman sewing wage
```

This block was central to V34 wage repair and V35 two-way edit behavior.

---

# PART H — DIGIKALA TITLE SPECIAL CASES

## 18. Strict resolver aliases

Current source `title_product_resolver_v27.py` explicitly supports Darma title keys such as:

```text
d110,d220,d330,d440,d550,d660
110,220,330,440,550,660
pack5,pack05
rah110,rah220
op,opbnw
770,880,990,400
06,6,pack6
p12,pgw,s3
```

Takvin special alias:

```text
1654 -> 654-1
```

No seller-code fallback.

---

## 19. Current real D220 contradiction example

Never forget this regression case:

```text
seller code = rah220
title model = D-220
size title = 46-48 -> 4XL
qty = 5
```

Expected product:

```text
D 220 / 4XL
```

not rah-220.

---

## 20. Brandless 400 example

```text
شورت زنانه مدل 400 مجموعه 4 عددی | XL | ...
```

can resolve to Darma 400 only if it remains unique across import brands.

---

# PART I — HISTORICAL RETURN FILE

## 21. Known return-only file

```text
packageDeliveryReport_17851669002377.xlsx
```

must not be treated as daily sales.

---

# PART J — SOURCE VERSUS LIVE DATA WARNING

## 22. Never blindly sync source catalog into live DB

`core/product_catalog.py` is a source definition, but a broad catalog sync can rewrite:

- composition;
- active states;
- default sale prices;
- unit costs;
- size activation.

Because the user can edit live product settings and historical data exists, do not run `sync_catalog()` merely to make source/live look identical.

For a single known defect, prefer a targeted migration/management command with before/after guards.

---

## 23. Historical baseline data is not current stock

This file intentionally contains exact historical matrices because they are necessary for forensic continuity.

Never treat these as a current target without an explicit user request naming the historical checkpoint.

For current stock questions, query live `StockBalance` or use current inventory UI/diagnostics.
