"""Factory-to-home invoice origin correction; isolated DB only."""
import tempfile,unittest
from pathlib import Path
from daily_sales_service.app import app
from daily_sales_service.engine import init_db,ImportErrorDetail
from daily_sales_service.master_engine import add_master
from daily_sales_service.sister_invoices import (
 submit_invoice,invoice_detail,mehr_balance,mehr_open_items,
 correct_invoice_origin_to_home,record_receipt
)
from daily_sales_service.sister_invoice_api import origin_home_form,edit_form
from daily_sales_service.sister_finance_logic import sales_report

class FactoryToHomeTests(unittest.TestCase):
 def setUp(self):
  folder=tempfile.TemporaryDirectory()
  self.addCleanup(folder.cleanup)
  self.db=init_db(Path(folder.name)/"test.sqlite3")
  self.addCleanup(self.db.close)
  self.sku=add_master(self.db,"قالب","TEST-FACTORY-HOME","قالب آزمایشی","بزرگ","مشکی",0,50)
  self.db.execute("UPDATE master_products SET seller_stock=20 WHERE id=?",(self.sku,))

 def make_invoice(self):
  return submit_invoice(self.db,"مدبر","", "2026-11-20","factory",
   {"بزرگ":{"qty":4,"purchase":50,"sale":100}},"","factory-home-test-1",
   "400","mine","2026-11-20")

 def test_switch_origin_reverses_debt_and_consumes_home_once(self):
  i=self.make_invoice()
  before=invoice_detail(self.db,i)
  self.assertEqual(mehr_balance(self.db)["debt"],200)
  self.assertEqual(self.db.execute("SELECT seller_stock FROM master_products WHERE id=?",(self.sku,)).fetchone()[0],20)
  original_sales=sales_report(self.db)["gross"]
  changed=correct_invoice_origin_to_home(self.db,i,before[0]["version"],"origin-fix",{"بزرگ":self.sku})
  self.assertTrue(changed["posted"])
  after=invoice_detail(self.db,i)
  self.assertEqual(after[0]["origin"],"home")
  self.assertEqual(after[1][0]["master_id"],self.sku)
  self.assertEqual(after[2],before[2])
  self.assertEqual(mehr_balance(self.db)["debt"],0)
  self.assertEqual(self.db.execute("SELECT seller_stock FROM master_products WHERE id=?",(self.sku,)).fetchone()[0],16)
  self.assertEqual(sales_report(self.db)["gross"],original_sales)
  self.assertEqual(len(list(self.db.execute("SELECT * FROM master_stock_events WHERE reference LIKE 'sister-invoice-origin-home:%'"))),1)
  self.assertEqual(len(list(self.db.execute("SELECT * FROM sister_invoice_audit WHERE invoice_id=?",(i,)))),1)
  with self.assertRaises(ImportErrorDetail):
   correct_invoice_origin_to_home(self.db,i,before[0]["version"],"origin-fix",{"بزرگ":self.sku})
  self.assertEqual(mehr_balance(self.db)["debt"],0)

 def test_customer_paid_mehr_stays_credit_not_lost(self):
  i=submit_invoice(self.db,"مدبر","", "2026-11-20","factory",
   {"بزرگ":{"qty":4,"purchase":50,"sale":100}},"","factory-home-test-2",
   "100","mehr","2026-11-20")
  before=invoice_detail(self.db,i)
  self.assertEqual(mehr_balance(self.db)["net"],-100)
  correct_invoice_origin_to_home(self.db,i,before[0]["version"],"origin-fix-2",{"بزرگ":self.sku})
  self.assertEqual(mehr_balance(self.db)["net"],100)
  item=next(x for x in mehr_open_items(self.db) if x["id"]==i and x["kind"]=="invoice")
  self.assertEqual(item["credit"],100)
  self.assertEqual(item["gross"],0)
  self.assertEqual(invoice_detail(self.db,i)[2],before[2])

 def test_bad_sku_rollback_and_form(self):
  i=self.make_invoice()
  before=invoice_detail(self.db,i)
  html=origin_home_form(invoice_id=i,conn=self.db).body.decode()
  self.assertIn("اصلاح مبدأ",html)
  self.assertIn("master_بزرگ",html)
  with self.assertRaises(ImportErrorDetail):
   correct_invoice_origin_to_home(self.db,i,before[0]["version"],"bad-target",{"بزرگ":999999})
  self.assertEqual(invoice_detail(self.db,i),before)
  self.assertEqual(mehr_balance(self.db)["debt"],200)

if __name__=="__main__":unittest.main()
