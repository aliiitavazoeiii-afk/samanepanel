# Sister Finance V5 — independent ledger, platform receivables and daily profit

**Isolation:** only `dia-darma-fresh` and sister SQLite at
`/data/sales.sqlite3` inside `sister-digikala`.
Do not modify original `/opt/darma-general`, `/opt/dia-gallery`, their
databases, financial ledger, bank accounts or Docker volumes.

## Sales and commission

- **Basalam**: exactly 15% of **gross actual sale price** (Toman) at the
  order level, rounded half-up to integer Toman.
  - A 500,000 sale produces 75,000 fee and 425,000 receivable.
  - For an 80,000 COGS snapshot, profit = 500,000 − 75,000 − 80,000
    = **345,000 Toman**.
  - Sale registration atomically deducts the exact physical color/size
    components and saves gross, fee, cost and profit inputs in one transaction.
  - The form offers an **optional actual price per pack** for discounted
    orders; it overrides the listed pack price ONLY for that sale, without
    changing the price catalog.
  - Legacy V3 rows with unknown commission are read using the same 15%
    rule, without mutating their other saved financial or stock information.
- **DigiKala**: the authoritative `sales` table stores per-unit
  commission, processing and VAT/fees, sale price and COGS snapshot.
  The claim equals `SUM(qty*(price_toman − fee_toman))`, even when
  the daily Excel has been reimported for a corrected day. No second
  sale/accrual entry is written.
- **Site/molds**: share the same sales, COGS, bank and settlement flows;
  default known platform fee is **zero** until another rate/charge is
  explicitly provided. Never invent payment gateway, shipping, taxes or
  other marketplace fees.

**Sale profit = Gross − known platform fees − physical COGS.**
If any item has unknown COGS, the whole reported period profit is unknown,
not a misleading zero. This is contribution profit after the listed sale
costs, **not** an audited final profit after general overhead.

## Financial receivables vs cash

The financial ledger has no extra copy of sales or amounts due:
- `platform outstanding = cumulative confirmed gross sales − cumulative
  sale platform fees − active receipts from that platform`.
- Sale creates the accrual *implicitly*, not a new transfer row.
- A **receipt** increases the selected cash/bank balance and decreases that
  platform's outstanding claim. It never creates additional sales or profit.
- A **payment** to a person or supplier decreases the selected bank/cash
  balance. A payment is **not automatically added to COGS**: some supplier
  payments purchase stock or settle previously accrued debt, so automatic
  expense double counting would be incorrect.
- Account balance = user-supplied opening + receipts − payments. Accounts
  and payees may be created from the dedicated finance UI.
- Digikala, Basalam, site, molds and Snap are built-in payees; Snap has no
  sales accrual until Snap sales exists.
- Each receipt/payment may have a unique bank reference (per kind and payee)
  to protect from double posting, date, amount, bank and memo.
- Mistakes can be **voided** (soft cancelled with timestamp); cancelled
  movements are preserved for audit and excluded from balances. Original
  sales/stock postings are never edited by voiding a receipt.

## New additive isolated tables

- `sister_finance_parties`: platforms and user-defined counterparties
- `sister_finance_accounts`: bank and cash account names and opening balance
- `sister_finance_movements`: receipt/payment transfer log, soft cancellations

No migration or mutation of legacy `ExcelManualRow`, `BusinessPayment`,
`DigikalaSettlement` or the original `dia-gallery` schema.

## User-facing locations

- `/finance/` — finance overview and platform balances
- `/finance/accounts/` — receivables cards and user-defined bank accounts
- `/payments/?section=receipt` — **دریافتی**, dropdown **دریافت از**,
  **واریز به حساب**, date/amount/reference/memo
- `/payments/?section=payment` — **پرداختی**, dropdown **پرداخت به**,
  **پرداخت از حساب**, date/amount/reference/memo
- `/finance/sales/` — unified platform-by-platform sale, fee, COGS,
  gross/net and profit report
- `/sales/basalam/`, `/sales/site/`, `/sales/ghaleb/` — daily
  filter, KPIs, order entry and exact breakdown
- `/sales/digikala/` — existing DigiKala upload/sales dashboard, now also
  showing other platforms and their financial settlements

Previous ERP finance views (for audit only) remain reachable at
`/finance/legacy/`, `/finance/legacy-accounts/` and
`/payments/legacy/`. This intentionally avoids double-counting
old Darma/Dia ledger balances with the sister business.

**Existing pre-V5 bank account and receivable opening balances are not
auto-imported**. User should set each opening bank balance when creating
the account; old historical platform receivables (outside sister sale
tables) require explicit reconciliation before importing as an opening
claim. Never create a duplicate receivable for a sale already posted.

## Regression and deployment

`tests/test_sister_finance_v5.py` checks fees (including discounts),
actual multi-color packs, historic DigiKala snapshot fees, missing COGS,
receipt/payee/bank math, idempotent receipt refs, payment path, and safe
voids. HTTP tests exercise the complete product→sale→claim→receipt→void
sequence. Django tests verify native routes and CSRF-protected forms.

Deploy ONLY through `deploy/darma-fresh/upgrade_sales_channels.sh`.
It validates branch/worktree and creates isolated PostgreSQL+SQLite
backups before rebuilding only `web` and `sister-digikala`. It checks
the new routes and tables; a successful run prints
`SISTER_FINANCE_BASALAM_15_PERCENT_LEDGER_READY`. GitHub CI passing
**does not mean the VPS has been upgraded**.
