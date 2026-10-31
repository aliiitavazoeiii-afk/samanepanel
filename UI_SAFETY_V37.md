# UI / returns / calculator safety contract v37

- Existing capital formula, sale profit formula, Digikala fee engine, receivable logic, inventory valuation, material consumption, production costing, payment logic and SaleSnapshot history are frozen.
- The old return box inside the daily sales report is retired. The daily report renders its pre-return v21 template again.
- The only active returns workflow is the standalone `/returns/` page linked under `کار روزانه`.
- A standalone return creates positive HOME inventory adjustments only. It creates no SaleLine, SaleSnapshot or AccountEntry and does not change Digikala receivable.
- Capital rises only because the existing finished-inventory valuation sees more HOME stock; the capital equation is not changed.
- Color returns are loose shorts. Code returns use the existing active ProductSize + ProductComposition for the selected brand and size. Variable-color products without fixed composition must be returned through the color path.
- The target-price calculator uses the realized current-Jalali-month `profit / COGS` percentage separately for Darma and Takvin.
- The target-price solver calls the existing `digikala_fee_for_unit()` engine. Commission, processing percentage/floor, taxable floor portion and VAT are not reimplemented or changed.
