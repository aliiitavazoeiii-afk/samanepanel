# V30B Shahrivar workflow reset

V30 failed safely because payment #2 fabric had already been moved/consumed and `reverse_purchase_stock()` correctly refused to pretend the purchased fabric was still entirely in warehouse. The transaction rolled back; no V30 reset changes were committed to the database.

V30B intentionally uses a different accounting contract requested for the debugging reset:

- Sales from 1405/06/01 onward are truly reversed from their existing SaleAllocation rows, then removed.
- Digikala receipts from 1405/06/01 onward are truly reversed (Mellat down, receivable restored), then removed.
- Outgoing BusinessPayment rows from 1405/06/01 onward are removed as history, but their current balance-sheet effects are PRESERVED as the new baseline. This prevents already moved/consumed fabric or correct current raw-material stock from being corrupted.
- Payment-specific MoneyMovement ledgers are removed and active RawMaterialStock notes that referenced deleted payment IDs are relabeled as baseline metadata only; quantities and unit prices are unchanged.
- Old outgoing payments removed by V30B MUST NOT be re-entered, because their economic effects were preserved in the baseline.
- 31 Mordad and earlier, physical/manual stock adjustments, and material-report state are preserved.

After reset: re-enter daily sales only for 1, 2, 3 Shahrivar, then restore/check the exact authoritative physical post-3-Shahrivar Darma baseline before proceeding day by day.
