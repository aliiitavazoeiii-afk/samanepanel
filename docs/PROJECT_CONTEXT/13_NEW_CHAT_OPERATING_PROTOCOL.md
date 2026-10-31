# 13 — NEW CHAT OPERATING PROTOCOL

This document tells a future AI/chat exactly how to continue the project without losing the reasoning discipline developed in the original chat.

---

## 1. Do not start by coding

For every new request:

1. identify the subsystem(s) involved;
2. inspect `core/urls.py` to confirm active route;
3. read the relevant context document(s);
4. read exact current source files;
5. identify business invariants that must remain unchanged;
6. decide whether request is UI-only, operational, accounting-affecting, or data-reconcile;
7. only then edit.

---

## 2. Classification rules

### UI-only

Examples:

- move cards;
- rename labels;
- collapse sections;
- filter display alerts;
- responsive layout.

Rule:

No business data or formulas may change. Deployment must prove invariant equality before/after.

### Operational stock workflow

Examples:

- returns;
- transfer;
- output sync;
- sale delete.

Rule:

Use existing stock services/ledgers, transaction.atomic, exact before/after quantity/value tests.

### Finance/accounting workflow

Examples:

- payment;
- receivable;
- Digikala receipt;
- cost rule;
- capital calculation.

Rule:

Trace both sides of every movement. Never update only the display total.

### Historical reconcile/reset

Examples:

- restore 31 Mordad baseline;
- remove later SaleDays;
- physical day-3 baseline;
- repair a known duplicated/misclassified stock event.

Rule:

Dry-run + backup + explicit scope + atomic apply + exact verification. Historical checkpoint must be named.

---

## 3. Source-of-truth hierarchy

When evidence conflicts, use this hierarchy:

1. explicit current user business rule;
2. current physical evidence / uploaded source file for the requested event;
3. current structured ledger/history (SaleAllocation, purchase ledger, MaterialReportOutputApplied, etc.);
4. current active code and DB aggregate state;
5. latest context docs;
6. older handoff/history;
7. assumptions/inference last.

Do not silently reconcile a conflict. State it before mutation.

---

## 4. Data-edit rule

Never change a number just because it looks wrong.

Before mutation, identify:

- what event originally created it;
- what ledger records that event;
- what reverse path exists;
- what other component must change simultaneously;
- whether current aggregate contains prior unrelated state.

Example: elastic aggregate 10kg with latest purchase note #6 did not prove purchase #6 added 10kg. Ledger proved purchase #6 added 5kg; aggregate could contain prior stock.

---

## 5. No raw deletes for applied business objects

Do not raw-delete:

- SaleLine;
- BusinessPayment;
- DigikalaSettlement;
- InventoryAdjustment;
- applied production/output;
- material purchase ledger;

unless a dedicated forensic command explicitly performs all required reversals/rebase steps atomically.

Use normal reverse/sync services.

---

## 6. Historical values versus current values

The repo intentionally contains historical matrices/checkpoints.

A future AI must use phrases conceptually like:

- "historical reference";
- "last confirmed live checkpoint";
- "current DB value";
- "physical target".

Never mix them.

---

## 7. Deployment confirmation wording

Allowed before server output:

- "code is on main";
- "deploy script is ready";
- "expected success marker is...".

Not allowed before server output:

- "it is live";
- "production is fixed";
- "the inventory is corrected".

After user posts explicit successful final output, record the new live checkpoint in this context pack or a new version doc.

---

## 8. Error handling

When user pastes an error:

- read the exact failing step;
- infer transaction scope;
- determine whether anything persisted;
- do not repeat a mutation until persistence is known;
- patch the script/check itself if the feature code already passed;
- do not bypass guards.

Examples:

- V30 failure rolled back everything;
- V33 `CHECK OK` followed by deploy-snapshot syntax failure did not prove web recreate/live deployment;
- V26 Gunicorn hang was a script entrypoint issue, not application logic.

---

## 9. Testing style

Prefer three layers:

### Static/source guard

Assert protected formulas/files/routes did not drift.

### Transactional regression

Apply a small realistic operation inside `transaction.atomic`, assert all expected side effects and forbidden side effects, then rollback.

### Deployment invariant snapshot

Compare persistent economic values before/preflight/after live recreate.

This pattern has been successful and should continue.

---

## 10. GitHub edit discipline

When implementing:

- edit repository directly;
- make a rollback branch before risky phase;
- avoid temporary junk marker files on main;
- if a temporary file is necessary during work, remove it before presenting deployment;
- create purpose-specific management command/tests and deploy script;
- do not edit unrelated files.

---

## 11. User-facing command style

Give short commands, normally:

```bash
cd /opt/darma-general
git pull --ff-only
bash server_<feature>.sh
```

If a dry-run must be reviewed before apply, give dry-run first and explicitly ask for output before apply.

Do not bury the actual command in a long tutorial.

---

## 12. When to create a read-only diagnostic

Create one before mutation if:

- source of discrepancy is unknown;
- aggregate state can contain prior events;
- reverse may fail because material moved/consumed;
- accounting delta is large;
- user remembers a total that conflicts with saved rows;
- a historical resolver bug may have already stored wrong rows.

Diagnostic should print:

- exact object IDs;
- exact target/current values;
- ledger references;
- totals and difference;
- a clear `NO DATA CHANGED` marker.

---

## 13. Never trust only a note field

Notes are useful labels, not always provenance.

Examples:

- RawMaterialStock aggregate note can be overwritten by latest purchase;
- source catalog note can be rewritten by sync;
- old textual references may survive migrations.

Prefer structured foreign keys/ledger identity/reference values.

---

## 14. Do not silently change business percentages

The exact Digikala fee engine is configurable. The calculator must call it.

The sewing wage is confirmed 110,000 per dozen.

Takvin historical cost is date-effective.

If a new price/cost/rate change is requested, implement an effective-date/current-setting mechanism where historical reporting requires preservation.

---

## 15. Update this context pack after major future phases

After a major accepted live change:

- update `03_ACTIVE_CODE_MAP.md` if routes changed;
- update `07_BUG_HISTORY...` if a new bug/fix matters;
- update `08_LIVE_STATE...` with confirmed server output only;
- update `12_VERSION_TIMELINE...` with new version semantics;
- update exact business rule doc if user changed a rule;
- bump the `00_NEW_CHAT_READ_FIRST.md` last-synchronized date/version.

This prevents the handoff from becoming stale like older v19-era docs.
