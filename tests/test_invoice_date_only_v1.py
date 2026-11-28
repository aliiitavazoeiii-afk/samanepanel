"""Date correction for overcredited factory invoice is audit-only."""
import tempfile,unittest
from pathlib import Path
from datetime import date
from daily_sales_service.app import app
from daily_sales_service.engine import init_db,ImportErrorDetail
from daily_sales_service.sister_finance_logic import ensure_finance_schema,sales_report
from daily_sales_service.sister_invoices import (
 submit_invoice,record_receipt,edit_invoice,edit_invoice_date,
 invoice_detail,mehr_balance,mehr_open_items
)
from daily_sales_service.sister_invoice_api import edit_form

class DateOnlyInvoiceTests(unittest.TestCase):
 def setUp(self):
  t=tempfile.TemporaryDirectory()
  self.addCleanup(t.cleanup)
  self.db=init_db(Path(t.name)/"date-test.sqlite3")
  self.addCleanup(self.db.close)
  ensure_finance_schema(self.db)

 def make_overcredited(self):
  i=submit_invoice(self.db,"سجاد","", "2026-11-22","factory",{
   "بزرگ":{"qty":10,"purchase":58300,"sale":78700}
  },"","make-sajjad", "200000","mine","2026-11-22")
  record_receipt(self.db,i,"587000","mehr","2026-11-22","customer-paid-mehr")
  return i

 def test_date_edit_moves_sales_without_touching_ledger_or_stock(self):
  i=self.make_overcredited()
  before=invoice_detail(self.db,i)
  bal=mehr_balance(self.db)
  stock=self.db.execute("SELECT COUNT(*) FROM master_stock_events").fetchone()[0]
  audit_before=self.db.execute("SELECT COUNT(*) FROM sister_invoice_audit").fetchone()[0]
  old=sales_report(self.db,from_date="2026-11-01",to_date="2026-11-30")["gross"]
  self.assertEqual(old,787000)
  self.assertEqual(mehr_open_items(self.db)[0]["remaining"],0)
  edit_invoice_date(self.db,i,"2026-10-10",before[0]["version"],"correct-date")
  after=invoice_detail(self.db,i)
  self.assertEqual(after[0]["invoice_date"],"2026-10-10")
  self.assertEqual(after[1:],before[1:])
  self.assertEqual(mehr_balance(self.db),bal)
  self.assertEqual(self.db.execute("SELECT COUNT(*) FROM master_stock_events").fetchone()[0],stock)
  self.assertEqual(self.db.execute("SELECT COUNT(*) FROM sister_invoice_audit").fetchone()[0],audit_before+1)
  self.assertEqual(sales_report(self.db,from_date="2026-11-01",to_date="2026-11-30")["gross"],0)
  self.assertEqual(sales_report(self.db,from_date="2026-10-01",to_date="2026-10-31")["gross"],787000)

 def test_full_edit_same_cost_succeeds_even_with_overcredit(self):
  i=self.make_overcredited()
  old=invoice_detail(self.db,i)[0]
  edit_invoice(self.db,i,"سجاد","", "2026-10-10",{
   "بزرگ":{"qty":10,"purchase":58300,"sale":78700}
  },"",old["version"],"correct-full-edit")
  self.assertEqual(invoice_detail(self.db,i)[0]["invoice_date"],"2026-10-10")
  self.assertEqual(mehr_balance(self.db)["net"],4000)

 def test_new_date_form_and_no_duplicate_date(self):
  i=self.make_overcredited()
  html=edit_form(invoice_id=i,conn=self.db).body.decode()
  self.assertIn('action="/daily-sales/invoices/'+str(i)+'/date"',html)
  before=invoice_detail(self.db,i)[0]
  with self.assertRaises(ImportErrorDetail):
   edit_invoice_date(self.db,i,before["invoice_date"],before["version"],"same-date")
  self.assertEqual(invoice_detail(self.db,i)[0]["version"],before["version"])

if __name__=="__main__":unittest.main()
