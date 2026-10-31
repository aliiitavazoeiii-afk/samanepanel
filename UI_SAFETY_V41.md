# UI SAFETY V41 — DIGIKALA DELIVERY BOARD

V41 is an external read-only operational visibility change.

## Allowed external reads

- `GET /open-api/v1/commitments`
- `GET /open-api/v1/commitments/metadata`
- existing V40 approved GET endpoints

The existing official token refresh POST remains credential maintenance only.

## Frozen internal semantics

V41 must not mutate or reinterpret:

- capital equation;
- Digikala receivable ledger;
- SaleLine / SaleSnapshot / SaleAllocation;
- StockBalance / InventoryMovement;
- daily XLSX import V23/title resolver V27;
- finished/raw inventory valuation;
- material report consumption/output;
- BusinessPayment purchase/prepayment flows;
- Digikala receipt settlement;
- standalone returns V37;
- calculator V37 or fee engine.

No model or migration is added.

## Delivery-number source

Do not use `GET /orders` total rows as the "must deliver" number.

Headline must-deliver quantity comes from:

```text
GET /open-api/v1/commitments/metadata
-> data.summary_statistics.effectiveCommitments
```

Itemized actionable quantity is calculated from the commitments list as:

```text
commitment.nextDays + commitment.today
```

`delayed` is shown separately and is not silently added to the actionable list.

If metadata effective count and itemized actionable sum differ, show the mismatch rather than inventing a reconciliation.

## Deployment invariant

Before and after V41 deploy, require exact equality of:

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

Any difference aborts the V41 deployment.
