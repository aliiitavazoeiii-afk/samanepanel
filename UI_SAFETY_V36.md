# UI / workflow safety contract v36

- Existing accounting formulas, sale formulas, Digikala fee logic, receivable logic, inventory valuation, material consumption, production valuation, payment logic and SaleSnapshot history are frozen for this phase.
- Dashboard/report work in v36 is presentation-only, except the explicitly requested daily-return workflow.
- Daily returns are isolated stock additions to HOME. They do not create SaleLine/SaleSnapshot/account entries, do not alter Digikala receivable, and do not calculate or deduct a Digikala fee.
- Return stock increases finished-goods value through the existing inventory valuation only; no capital formula is changed.
- Darma/Takvin catalog, pack composition and size activation remain source-of-truth for full-pack returns.
- Loose-short returns use the selected brand + size + color directly.
