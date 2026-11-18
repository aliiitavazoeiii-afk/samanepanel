"""Regression tests for the independent sister invoice and Mehr accounting ledger."""
import os
import tempfile
import unittest
from pathlib import Path
from daily_sales_service.engine import init_db, ImportErrorDetail
from daily_sales_service.sister_invoices import (
 create_invoice, dispatch_invoice, record_receipt, receive_purchase,
 settlement, mehr_balance, invoices
)
from daily_sales_service.effective_costs import today

class SisterInvoiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=init_db(Path(self.tmp.name)/"invoice-tests.sqlite3")
        day=today()
        self.day=day
        self.skus={}
        for size in ("کوچک","متوسط","بزرگ"):
            self.db.execute("""INSERT INTO master_products
             (category,code,title,size,color,sale_price_toman,cost_toman,
              seller_stock,digikala_stock,khorshid_stock,active,created_at,updated_at)
             VALUES ('قالب',?,?,?,?,0,40000,0,0,0,1,?,?)""",
             ("test-"+size,"قالب تست",size,"مشکی",day,day))
            self.skus[size]=self.db.execute(
                "SELECT id FROM master_products WHERE code=?",("test-"+size,)).fetchone()[0]
        self.db.execute("""INSERT INTO sister_finance_accounts
          (title,opening_toman,created_at) VALUES ('حساب تست',0,?)""",(day,))
        self.account=self.db.execute("SELECT id FROM sister_finance_accounts WHERE title='حساب تست'").fetchone()[0]

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def _invoice(self,origin="home"):
        return create_invoice(self.db,"مشتری تست","09120000000",self.day,origin,{
          "کوچک":{"master_id":self.skus["کوچک"],"qty":2,"purchase":40000,"sale":70000},
          "متوسط":{"master_id":self.skus["متوسط"],"qty":1,"purchase":50000,"sale":80000},
          "بزرگ":{"qty":0}}, "نمونه")

    def test_home_purchase_then_sale_does_not_double_count_supplier_debt(self):
        receive_purchase(self.db,self.skus["کوچک"],3,40000,self.day,"purchase-one")
        receive_purchase(self.db,self.skus["متوسط"],2,50000,self.day,"purchase-two")
        self.assertEqual(mehr_balance(self.db)["debt"],220000)
        invoice=self._invoice()
        self.assertEqual(self.db.execute("SELECT seller_stock FROM master_products WHERE id=?",(self.skus["کوچک"],)).fetchone()[0],3)
        dispatch_invoice(self.db,invoice)
        self.assertEqual(mehr_balance(self.db)["debt"],220000)
        self.assertEqual(self.db.execute("SELECT seller_stock FROM master_products WHERE id=?",(self.skus["کوچک"],)).fetchone()[0],1)
        with self.assertRaises(ImportErrorDetail):dispatch_invoice(self.db,invoice)
        self.assertEqual(mehr_balance(self.db)["debt"],220000)

    def test_factory_dispatch_creates_supplier_debt_without_home_stock(self):
        invoice=self._invoice("factory")
        dispatch_invoice(self.db,invoice)
        self.assertEqual(mehr_balance(self.db)["debt"],130000)
        self.assertEqual(self.db.execute("SELECT SUM(seller_stock) FROM master_products WHERE category='قالب'").fetchone()[0],0)

    def test_receipts_to_mehr_create_credit_but_do_not_change_cash(self):
        invoice=self._invoice("factory")
        dispatch_invoice(self.db,invoice)
        record_receipt(self.db,invoice,100000,"mehr",self.day,"r1")
        record_receipt(self.db,invoice,40000,"check_mehr",self.day,"r2",check_date=self.day,notes="چک تحویل")
        b=mehr_balance(self.db)
        self.assertEqual((b["debt"],b["credit"]),(130000,140000))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM sister_finance_movements").fetchone()[0],0)
        settlement(self.db,"offset",130000,self.day,"offset-1")
        self.assertEqual(mehr_balance(self.db),{"debt":0,"credit":10000,"net":10000})
        with self.assertRaises(ImportErrorDetail):
            settlement(self.db,"offset",130000,self.day,"offset-2")

    def test_payment_to_mine_posts_cash_and_reduces_customer_balance(self):
        invoice=self._invoice()
        record_receipt(self.db,invoice,50000,"mine",self.day,"bank-r1",account_id=self.account)
        rows=invoices(self.db,"مشتری تست")
        self.assertEqual(rows[0]["paid"],50000)
        self.assertEqual(self.db.execute("SELECT SUM(amount_toman) FROM sister_finance_movements").fetchone()[0],50000)
        with self.assertRaises(ImportErrorDetail):
            record_receipt(self.db,invoice,50000,"mine",self.day,"bank-r1",account_id=self.account)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM sister_invoice_receipts").fetchone()[0],1)

    def test_factory_debt_and_credit_settlement_by_bank(self):
        invoice=self._invoice("factory");dispatch_invoice(self.db,invoice)
        record_receipt(self.db,invoice,200000,"mehr",self.day,"mehr-r1")
        settlement(self.db,"received_from_mehr",70000,self.day,"receive-mehr",account_id=self.account)
        self.assertEqual(mehr_balance(self.db)["credit"],130000)
        self.assertEqual(self.db.execute("SELECT SUM(amount_toman) FROM sister_finance_movements").fetchone()[0],70000)
        settlement(self.db,"offset",130000,self.day,"offset-final")
        self.assertEqual(mehr_balance(self.db)["net"],0)

    def test_missing_home_sku_rejected_and_factory_requires_no_sku(self):
        with self.assertRaises(ImportErrorDetail):
            create_invoice(self.db,"تست مشتری","",self.day,"home",{
                "کوچک":{"qty":1,"purchase":10000,"sale":20000}})
        iid=create_invoice(self.db,"تست مشتری","",self.day,"factory",{
                "کوچک":{"qty":1,"purchase":10000,"sale":20000}})
        self.assertTrue(iid)

if __name__=="__main__":
    unittest.main()
