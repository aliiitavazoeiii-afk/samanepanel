"""Customer receipt destination is mine or Mehr; never require a bank account."""
import tempfile
import unittest
from pathlib import Path
# Import the FastAPI app first: it registers the invoice/finance routers, avoiding circular imports.
from daily_sales_service.app import app
from daily_sales_service.engine import init_db
from daily_sales_service.effective_costs import today
from daily_sales_service.sister_invoices import submit_invoice,invoice_detail,mehr_balance
from daily_sales_service.sister_finance_logic import ensure_finance_schema
from daily_sales_service.sister_finance_api import finance_accounts, finance_home, open_invoice_balances
from daily_sales_service.sister_invoice_api import new_invoice, supplier, detail

class BankFreeCustomerAccountingTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.conn=init_db(Path(folder.name)/"no-bank.sqlite3")
        self.addCleanup(self.conn.close)
        ensure_finance_schema(self.conn)

    def test_factory_invoice_receipts_without_bank_and_no_stock_change(self):
        before=self.conn.execute("SELECT COALESCE(SUM(seller_stock),0) FROM master_products").fetchone()[0]
        inv=submit_invoice(self.conn,"مشتری آزمایشی","",today(),"factory",{
          "بزرگ":{"qty":2,"purchase":70000,"sale":100000}},
          "", "test-bank-free-invoice", "100000", "mehr",today())
        invoice,_,receipts=invoice_detail(self.conn,inv)
        self.assertEqual(invoice["origin"],"factory")
        self.assertEqual(receipts[0]["destination"],"mehr")
        self.assertIsNone(receipts[0]["account_id"])
        self.assertEqual(mehr_balance(self.conn)["credit"],100000)
        self.assertEqual(mehr_balance(self.conn)["debt"],140000)
        self.assertEqual(self.conn.execute("SELECT COALESCE(SUM(seller_stock),0) FROM master_products").fetchone()[0],before)

    def test_new_and_existing_invoice_pages_do_not_request_bank(self):
        page=new_invoice(conn=self.conn).body.decode()
        self.assertIn('name="destination"',page)
        self.assertNotIn('name="account_id"',page)
        self.assertIn("به من",page)
        self.assertIn("به مهر",page)
        invoice=submit_invoice(self.conn,"مشتری دوم","",today(),"factory",{
          "متوسط":{"qty":1,"purchase":70000,"sale":100000}},
          "", "test-bank-free-invoice2", "50000", "mine",today())
        detail_page=detail(invoice_id=invoice,conn=self.conn).body.decode()
        self.assertNotIn('name="account_id"',detail_page)
        self.assertNotIn("بانک نامشخص",detail_page)
        self.assertIn("به من",detail_page)

    def test_mehr_and_finance_pages_show_no_bank_accounts_for_new_entries(self):
        mehr=supplier(conn=self.conn).body.decode()
        self.assertNotIn('name="account_id"',mehr)
        finance=finance_home(conn=self.conn).body.decode()
        self.assertNotIn("جمع موجودی حساب‌های ثبت‌شده",finance)
        account_page=finance_accounts(conn=self.conn).body.decode()
        self.assertNotIn('name="title"',account_page)
        self.assertNotIn('name="opening"',account_page)
        self.assertIn("به من",account_page)
        self.assertIn("به مهر",account_page)
        opened=open_invoice_balances(conn=self.conn).body.decode()
        self.assertIn("دریافت‌های ثبت‌شده به من",opened)

if __name__=="__main__":unittest.main()
