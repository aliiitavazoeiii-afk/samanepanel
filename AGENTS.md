# Samanepanel — Instructions for coding assistants

**AUTHORITATIVE CONTINUATION GUIDE:** [docs/SISTER_CHATGPT_HANDOFF.md](docs/SISTER_CHATGPT_HANDOFF.md). Read it in full before touching code, database, deployment scripts, or business calculations.

## Identity — do not work in the wrong project
- Repo: `aliiitavazoeiii-afk/samanepanel`
- Active development/deployment branch: `dia-darma-fresh` (**not** stale `main`).
- Sister business UI: `https://forosh.filmjadiid.ir`
- Server checkout: `/opt/dia-darma-fresh`
- Docker Compose file: `compose.fresh.yml`
- SQLite sister sales DB inside container: `/data/sales.sqlite3`. Isolated Django `web` and PostgreSQL `db` containers.
- **Never conflate this with** `aliiitavazoeiii-afk/darma-general`, `/opt/darma-general`, or `gozaresh.filmjadiid.ir`. This repository contains old **copied Darma docs** (`AI_START_HERE.md`, `PROJECT_HANDOFF_CURRENT.md`, `docs/00_NEW_CHAT_READ_FIRST.md`); they are NOT authoritative for this project.

## Required workflow
1. Verify current GitHub repo/ref and live file contents; user speaks Persian and may provide screenshots/terminal logs.
2. Read the sister handoff and subsystem code/tests. Distinguish current source, CI-tested version and actual VPS-deployed version.
3. Prefer smallest safe, tested, reversible change. Commit code and add regression tests. Confirm relevant GitHub Actions. For sensitive changes, use a PR/review workflow.
4. When adding a FastAPI GET/POST endpoint, register routers in `master_v2_api.py`, authorize the path in Django `core/sister_sales.py` (`_ALLOWED` and `_POST` for forms), and add canonical Django URL in `core/urls.py` when appropriate.
5. Run Django and sister engine tests, then use backup-first isolated deployment script:
   `deploy/darma-fresh/upgrade_sales_channels.sh`.
   Never use `docker compose down -v`, truncate databases, recreate production volumes, or reset sales/finance data.
6. **Never claim deployed to VPS merely because GitHub commit or CI passed**. Verify explicit server terminal output or authorized live evidence. Never claim access to the server without real tool access.
7. Update `docs/SISTER_CHATGPT_HANDOFF.md` whenever invariants, navigation, deployment method, or economic formulas change.

## Non-negotiable accounting and stock invariants
- Canonical physical inventory = `master_products`. DigiKala listing variants = `products`; packs consist of physical SKU components. All sales channels share stock.
- Confirmed sales may make stock **negative**; do not reject an otherwise valid sale due solely to a shortage. Never map ambiguous colors/sizes or mold ranges by guessing.
- DigiKala daily input is the unchanged standard owner `packageDeliveryReport*.xlsx`, typically lacking a price column; read per-variant prices from configured/date-effective sources. Sale snapshots preserve historical prices and COGS.
- Preview first, commit on explicit user confirmation. Daily source/date replacement must not double-deduct inventory; day deletion restores physical units and receivable atomically with permanent audit, but refuses to invalidate already settled funds.
- DigiKala catalog deletion is **reversible archive** only; bulk max 50 codes. Preserve all original variant identities, past sales and warehouse links.
- Capital = COGS-valued finished inventory + bank/cash + net marketplace receivables + separately declared raw materials/equipment/other assets − separate liabilities. Do **not** add sale profits again or import any Darma/Takvin balances. Missing COGS means a full capital valuation is **unknown**, not zero. Never fabricate financial numbers.
- Do not expose credentials, `.env`, tokens, SSH keys, database dumps, customer PII, or server secrets in commits or chats.

For full file map, navigation, business rules, safeguards, and newcomer starting message, consult the handoff guide above.
