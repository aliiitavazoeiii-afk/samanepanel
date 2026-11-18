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
    def test_reject_duplicate_or_invalid_rows_without_any_stock_writes(self):
        for rows in (
            [(self.ids["DIA-P"],2,58000),(self.ids["DIA-P"],1,58000)],
            [(self.ids["DIA-P"],-1,58000)],
            [(self.ids["DIA-P"],1,0)]):
            with self.assertRaises(ImportErrorDetail):
                register_purchase(self.conn,"دیا",self.day,"home",rows,"bad-"+str(len(rows))+str(rows[0][1]))
        self.assertEqual(self.count_stock("DIA-P"),0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sister_purchase_orders").fetchone()[0],0)
    def test_excel_style_grid_supports_mold_and_apparel_sizes(self):
        from daily_sales_service.app import app
        from daily_sales_service.sister_purchase_grid import purchase_grid
        page=purchase_grid(self.conn)
        self.assertIn('id="purchase-category"',page)
        self.assertIn('id="purchase-grid-body"',page)
        self.assertIn('purchase-discount-percent',page)
        for label in ("قالب","شورت زنانه دیا","شورت زنانه دارما","بادیگارد"):
            self.assertIn(label,page)
        self.assertIn("MOLD-P",page)
        self.assertIn("DIA-P",page)
        self.assertIn("BG-P",page)

    def test_mold_purchase_routes_to_existing_mehr_debt_without_double_posting(self):
        from daily_sales_service.sister_invoices import mehr_balance
        pid=register_purchase(self.conn,"مه هر",self.day,"home",[
            (self.ids["MOLD-P"],5,90000)],"mehr-one",discount_percent="10")
        self.assertEqual(self.count_stock("MOLD-P"),5)
        self.assertEqual(mehr_balance(self.conn)["debt"],405000)
        self.assertEqual(len(suppliers(self.conn)),0)
        p,lines=purchase_detail(self.conn,pid)
        self.assertEqual((p["subtotal_toman"],p["total_toman"]), (450000,405000))
        self.assertEqual((lines[0]["list_unit_cost_toman"],lines[0]["unit_cost_toman"]), (90000,81000))
        with self.assertRaises(ImportErrorDetail):
            register_purchase(self.conn,"مه هر",self.day,"home",[(self.ids["MOLD-P"],5,90000)],"mehr-one")
        self.assertEqual(mehr_balance(self.conn)["debt"],405000)
        self.assertEqual(self.count_stock("MOLD-P"),5)

    def test_mixed_exact_skus_under_single_supplier_purchase(self):
        register_purchase(self.conn,"دیا",self.day,"home",[
            (self.ids["DIA-P"],3,58000),
            (self.ids["DARMA-P"],2,80000),
            (self.ids["BG-P"],1,85000),
        ],"mixed-buy",discount_percent="12.5")
        self.assertEqual(self.count_stock("DIA-P"),3)
        self.assertEqual(self.count_stock("DARMA-P"),2)
        self.assertEqual(self.count_stock("BG-P"),1)
        self.assertEqual(suppliers(self.conn)[0]["purchased"],366625)

    def test_purchases_page_has_only_purchase_and_stock_entry_not_financial_forms(self):
        from daily_sales_service.app import app
        from daily_sales_service.sister_purchase_api import purchase_home
        page=purchase_home(conn=self.conn).body.decode("utf-8")
        self.assertIn("ثبت قطعی خرید و افزایش موجودی",page)
        self.assertIn("خریدهای اخیر",page)
        self.assertNotIn("ثبت تسویه مه هر",page)
        self.assertNotIn("ثبت پرداخت</button>",page)
        self.assertNotIn("حساب تأمین‌کنندگان (تومان)",page)

    def test_mehr_ledger_kept_on_invoices_page(self):
        from daily_sales_service.app import app
        from daily_sales_service.sister_invoice_api import supplier
        page=supplier(conn=self.conn).body.decode("utf-8")
        self.assertIn("حساب مه هر",page)
        self.assertIn("ثبت تسویه یا تهاتر",page)
        self.assertIn("واریز مه هر به من",page)

    def test_supplier_purchase_liability_is_reflected_in_overall_capital(self):
        from daily_sales_service.app import app
        from daily_sales_service.sister_finance_logic import overview
        from daily_sales_service.capital_api import financial_capital
        before=financial_capital(self.conn)
        self.assertEqual(before["known_components_total"],1000000)
        register_purchase(self.conn,"دیا",self.day,"home",
                          [(self.ids["DIA-P"],10,58000)],"cap-liability-1")
        info=overview(self.conn)
        self.assertEqual(info["supplier_payable"],580000)
        self.assertEqual(info["mehr_payable"],0)
        cap=financial_capital(self.conn)
        self.assertEqual(cap["supplier_payable"],580000)
        self.assertEqual(cap["known_components_total"],920000)
        self.assertIsNone(cap["total_capital"])

    def test_does_not_auto_import_existing_stock_as_new_purchase(self):
        self.conn.execute("UPDATE master_products SET seller_stock=50 WHERE id=?",(self.ids["DIA-P"],))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sister_purchase_orders").fetchone()[0],0)
        self.assertEqual(len(suppliers(self.conn)),0)
        self.assertEqual(self.count_stock("DIA-P"),50)

if __name__=="__main__":
    unittest.main()
