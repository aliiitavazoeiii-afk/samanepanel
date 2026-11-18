"""Regression for independent Dia/Darma/Bodyguard supplier purchasing."""
import tempfile
import unittest
from pathlib import Path

from daily_sales_service.engine import ImportErrorDetail, init_db
from daily_sales_service.effective_costs import today
from daily_sales_service.sister_purchases import (
    register_purchase,register_supplier_payment,supplier_totals,suppliers,
    purchase_detail,
)

class SupplierPurchasesTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.conn=init_db(Path(self.tmp.name)/"purchases.sqlite3")
        self.day=today()
        self.ids={}
        for category,code,size,color in (
            ("شورت زنانه دیا","DIA-P","M","مشکی"),
            ("شورت زنانه دارما","DARMA-P","L","سفید"),
            ("بادیگارد","BG-P","XL","سرمه‌ای"),
            ("قالب","MOLD-P","کوچک","مشکی")):
            self.conn.execute("""INSERT INTO master_products
              (category,code,title,size,color,sale_price_toman,cost_toman,
               seller_stock,digikala_stock,khorshid_stock,active,created_at,updated_at)
              VALUES (?,?,?,?,?,0,50000,0,0,0,1,?,?)""",
              (category,code,code,size,color,self.day,self.day))
            self.ids[code]=self.conn.execute("SELECT id FROM master_products WHERE code=?",(code,)).fetchone()[0]
        self.conn.execute("""INSERT INTO sister_finance_accounts(title,opening_toman,created_at)
          VALUES ('حساب خرید',1000000,?)""",(self.day,))
        self.bank=self.conn.execute("SELECT id FROM sister_finance_accounts WHERE title='حساب خرید'").fetchone()[0]
    def tearDown(self):
        self.conn.close();self.tmp.cleanup()
    def count_stock(self,code,column="seller_stock"):
        return self.conn.execute("SELECT "+column+" FROM master_products WHERE id=?",(self.ids[code],)).fetchone()[0]
    def test_multi_line_purchase_increases_exact_physical_skus_and_supplier_debt(self):
        pid=register_purchase(self.conn,"دیا",self.day,"home",[
            (self.ids["DIA-P"],10,58000),(self.ids["BG-P"],5,85000)
        ],"purchase-dia-1",supplier_invoice="F-101")
        self.assertEqual(self.count_stock("DIA-P"),10)
        self.assertEqual(self.count_stock("BG-P"),5)
        self.assertEqual(self.count_stock("DARMA-P"),0)
        s=suppliers(self.conn)[0]
        self.assertEqual(s["name"],"دیا")
        self.assertEqual(s["due"],10*58000+5*85000)
        p,lines=purchase_detail(self.conn,pid)
        self.assertEqual(len(lines),2)
        self.assertEqual(p["total_toman"],s["due"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sister_finance_movements").fetchone()[0],0)
        with self.assertRaises(ImportErrorDetail):
            register_purchase(self.conn,"دیا",self.day,"home",[
                (self.ids["DIA-P"],10,58000)
            ],"purchase-dia-1")
        self.assertEqual(self.count_stock("DIA-P"),10)
    def test_supplier_payment_moves_cash_once_and_lowers_payable(self):
        register_purchase(self.conn,"دارما",self.day,"home",[(self.ids["DARMA-P"],4,100000)],"dar-1")
        sid=suppliers(self.conn)[0]["id"]
        register_supplier_payment(self.conn,sid,self.bank,150000,self.day,"pay-dar-1")
        self.assertEqual(supplier_totals(self.conn,sid)["due"],250000)
        row=self.conn.execute("""SELECT amount_toman,kind,reference FROM sister_finance_movements""").fetchone()
        self.assertEqual((row["amount_toman"],row["kind"]),(150000,"payment"))
        from daily_sales_service.sister_finance_logic import accounts,cancel_movement
        self.assertEqual([x for x in accounts(self.conn) if x["id"]==self.bank][0]["balance"],850000)
        mid=self.conn.execute("SELECT id FROM sister_finance_movements").fetchone()[0]
        with self.assertRaises(ImportErrorDetail):cancel_movement(self.conn,mid)
        with self.assertRaises(ImportErrorDetail):
            register_supplier_payment(self.conn,sid,self.bank,150000,self.day,"pay-dar-1")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sister_purchase_payments").fetchone()[0],1)
    def test_explicit_khorshid_warehouse_isolated_from_home(self):
        register_purchase(self.conn,"بادیگارد",self.day,"khorshid",[(self.ids["BG-P"],3,85000)],"kh-1")
        self.assertEqual(self.count_stock("BG-P","khorshid_stock"),3)
        self.assertEqual(self.count_stock("BG-P"),0)
        self.assertEqual(self.conn.execute("SELECT delta FROM master_stock_events WHERE reference='supplier-purchase:1'").fetchone()[0],3)
    def test_reject_mold_and_duplicate_or_invalid_rows_without_any_stock_writes(self):
        for rows in (
            [(self.ids["MOLD-P"],1,1000)],
            [(self.ids["DIA-P"],2,58000),(self.ids["DIA-P"],1,58000)],
            [(self.ids["DIA-P"],-1,58000)],
            [(self.ids["DIA-P"],1,0)]):
            with self.assertRaises(ImportErrorDetail):
                register_purchase(self.conn,"دیا",self.day,"home",rows,"bad-"+str(len(rows))+str(rows[0][1]))
        self.assertEqual(self.count_stock("DIA-P"),0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sister_purchase_orders").fetchone()[0],0)
    def test_does_not_auto_import_existing_stock_as_new_purchase(self):
        self.conn.execute("UPDATE master_products SET seller_stock=50 WHERE id=?",(self.ids["DIA-P"],))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sister_purchase_orders").fetchone()[0],0)
        self.assertEqual(len(suppliers(self.conn)),0)
        with self.assertRaises(ImportErrorDetail):
            register_purchase(self.conn,"مه هر",self.day,"home",[(self.ids["DIA-P"],1,58000)],"invalid-mehr")
        self.assertEqual(self.count_stock("DIA-P"),50)

if __name__=="__main__":
    unittest.main()
