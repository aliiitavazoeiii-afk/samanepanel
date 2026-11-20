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


    def test_linked_bank_movement_cannot_be_cancelled_outside_invoice(self):
        from daily_sales_service.sister_finance_logic import cancel_movement
        invoice=self._invoice()
        record_receipt(self.db,invoice,50000,"mine",self.day,"bank-safe",account_id=self.account)
        movement_id=self.db.execute("SELECT id FROM sister_finance_movements WHERE reference LIKE 'invoice-receipt:%'").fetchone()[0]
        with self.assertRaises(ImportErrorDetail):
            cancel_movement(self.db,movement_id)
        self.assertIsNone(self.db.execute("SELECT cancelled_at FROM sister_finance_movements WHERE id=?",(movement_id,)).fetchone()[0])

    def test_comprehensive_capital_never_claims_known_total_when_new_invoice_present(self):
        from daily_sales_service.app import app
        from daily_sales_service.capital_api import financial_capital
        self._invoice()
        stat=financial_capital(self.db)
        self.assertTrue(stat["invoice_accounting_pending"])
        self.assertIsNone(stat["total_capital"])


    def test_dispatched_mold_invoice_profit_combines_with_platform_sales_once(self):
        from daily_sales_service.app import app
        from daily_sales_service.sister_finance_logic import sales_report, platform_balances
        from daily_sales_service.master_engine import now
        iid=self._invoice("factory")
        self.assertEqual(sales_report(self.db,"mold")["gross"],0)  # draft is not a sale
        dispatch_invoice(self.db,iid)
        mold=sales_report(self.db,"mold")
        self.assertEqual((mold["gross"],mold["cogs_known"],mold["profit"]),(220000,130000,90000))
        self.assertEqual((mold["mold_gross"],mold["mold_profit"],mold["mold_invoice_count"]),
                         (220000,90000,1))
        self.assertEqual(platform_balances(self.db)["mold"]["outstanding"],0)
        now_iso=now()
        cur=self.db.execute("""INSERT INTO platform_listings
            (channel,listing_code,title,master_id,pack_qty,created_at,updated_at)
            VALUES ('mold','test-mold-listing','قالب تست',?,1,?,?)""",
            (self.skus["کوچک"],now_iso,now_iso))
        self.db.execute("""INSERT INTO platform_sales
            (channel,listing_id,sale_date,packs,units,warehouse,unit_sale_price,
            cost_per_unit,gross_toman,cogs_toman,commission_toman,created_at)
            VALUES ('mold',?,?,1,1,'home',150000,80000,150000,80000,0,?)""",
            (cur.lastrowid,self.day,now_iso))
        mold=sales_report(self.db,"mold")
        self.assertEqual((mold["orders"],mold["gross"],mold["profit"],mold["mold_profit"]),
                         (2,370000,160000,160000))
        self.assertEqual(platform_balances(self.db)["mold"]["outstanding"],150000)
        self.assertEqual(sales_report(self.db)["gross"],370000)
        self.assertEqual(sales_report(self.db)["profit"],160000)

    def test_invoice_cash_and_mehr_claims_feed_finance_and_capital_without_double_counting(self):
        from daily_sales_service.app import app
        from daily_sales_service.sister_finance_logic import overview,platform_balances
        from daily_sales_service.capital_api import financial_capital
        iid=self._invoice("factory")
        dispatch_invoice(self.db,iid)
        record_receipt(self.db,iid,100000,"mehr",self.day,"rm-1")
        record_receipt(self.db,iid,50000,"mine",self.day,"rme-2",account_id=self.account)
        info=overview(self.db)
        self.assertEqual(info["invoice_receivable"],70000)
        self.assertEqual(info["mehr_receivable"],100000)
        self.assertEqual(info["mehr_payable"],130000)
        self.assertEqual(info["total_receivables_including_mehr"],170000)
        self.assertEqual(info["total_liabilities_recorded"],130000)
        self.assertEqual(info["cash_balance"],50000)
        self.assertEqual(info["sales"]["mold_profit"],90000)
        self.assertEqual(info["total_receivable"],0)  # Not a platform payout
        self.assertEqual(platform_balances(self.db)["mold"]["outstanding"],0)
        cap=financial_capital(self.db)
        self.assertEqual(cap["known_components_total"],90000)
        self.assertEqual(cap["all_recorded_receivables"],170000)
        self.assertEqual(cap["mehr_payable"],130000)
        self.assertIsNone(cap["total_capital"])  # historical opening balance not reconciled

    def test_mold_daily_sales_summary_includes_invoice_profit_but_hides_customer_details(self):
        from daily_sales_service.app import app
        from daily_sales_service.platform_packs_ui import daily_sales_page
        iid=self._invoice("factory")
        dispatch_invoice(self.db,iid)
        html=daily_sales_page(self.db,"mold",self.day).body.decode("utf-8")
        self.assertIn("فروش خالص",html)
        self.assertIn("سود فروش",html)
        self.assertIn("جزئیات فاکتورها",html)
        self.assertNotIn("فاکتور #"+str(iid)+" · مشتری تست</th>",html)

    def test_finance_sales_shows_combined_profit_without_customer_invoice_details(self):
        from daily_sales_service.app import app
        from daily_sales_service.sister_finance_api import all_sales,finance_home
        iid=self._invoice("factory")
        dispatch_invoice(self.db,iid)
        report=all_sales(channel="mold",conn=self.db).body.decode("utf-8")
        self.assertIn("سود کل قالب‌ها",report)
        self.assertIn("90,000",report)
        self.assertNotIn("مشتری تست",report)
        home=finance_home(conn=self.db).body.decode("utf-8")
        self.assertIn("سود کل قالب‌ها",home)
        self.assertIn("کل بدهی خرید من به مه هر",home)
        self.assertIn("مانده خالص حساب مه هر",home)
        self.assertIn("وجوه مشتری نزد مه هر",home)
        self.assertIn("طلب مشتریان فاکتورها",home)
        self.assertNotIn("مشتری تست",home)

    def test_draft_advances_are_customer_liabilities_not_sale_profit(self):
        from daily_sales_service.app import app
        from daily_sales_service.sister_finance_logic import overview
        from daily_sales_service.capital_api import financial_capital
        iid=self._invoice("factory")
        record_receipt(self.db,iid,30000,"mine",self.day,"draft-money",account_id=self.account)
        record_receipt(self.db,iid,40000,"mehr",self.day,"draft-mehr")
        report=overview(self.db)
        self.assertEqual(report["sales"]["gross"],0)
        self.assertEqual(report["sales"]["profit"],0)
        self.assertEqual(report["invoice_receivable"],0)
        self.assertEqual(report["customer_advances"],70000)
        self.assertEqual(report["cash_balance"],30000)
        self.assertEqual(report["mehr_receivable"],40000)
        self.assertEqual(financial_capital(self.db)["known_components_total"],0)


    def test_one_page_invoice_single_submit_is_atomic_and_idempotent(self):
        from daily_sales_service.sister_invoices import submit_invoice,invoice_detail
        from daily_sales_service.sister_finance_logic import overview
        from daily_sales_service.app import app
        start_stock=self.db.execute("SELECT seller_stock FROM master_products WHERE id=?",(self.skus["کوچک"],)).fetchone()[0]
        items={"کوچک":{"qty":2,"purchase":40000,"sale":70000}}
        iid=submit_invoice(self.db,"تست یک مرحله‌ای","0912",self.day,"home",items,"یادداشت",
                           "one-submit-1",initial_amount="50000",destination="mine",paid_on=self.day,
                           receipt_notes="واریز به من، بانک مشخص نیست")
        inv,lines,receipts=invoice_detail(self.db,iid)
        self.assertEqual(inv["status"],"dispatched")
        self.assertEqual((len(lines),len(receipts),receipts[0]["amount"]), (1,1,50000))
        self.assertIsNone(receipts[0]["account_id"])
        self.assertEqual(self.db.execute("SELECT seller_stock FROM master_products WHERE id=?",(self.skus["کوچک"],)).fetchone()[0],start_stock-2)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM master_stock_events WHERE reference=?",
                           ("sister-invoice:"+str(iid),)).fetchone()[0],1)
        same=submit_invoice(self.db,"تست یک مرحله‌ای","0912",self.day,"home",items,"یادداشت",
                            "one-submit-1",initial_amount="50000")
        self.assertEqual(iid,same)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM sister_invoice_receipts WHERE invoice_id=?",(iid,)).fetchone()[0],1)
        self.assertEqual(overview(self.db)["invoice_receivable"],90000)
        self.assertEqual(overview(self.db)["cash_balance"],0)

    def test_one_page_invoice_invalid_initial_payment_rolls_back_stock_and_invoice(self):
        from daily_sales_service.sister_invoices import submit_invoice
        items={"کوچک":{"qty":2,"purchase":40000,"sale":70000}}
        before=self.db.execute("SELECT COUNT(*) FROM sister_invoices").fetchone()[0]
        with self.assertRaises(ImportErrorDetail):
            submit_invoice(self.db,"مشتری برگشت","0912",self.day,"home",items,"",
                           "invalid-payment",initial_amount="200000")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM sister_invoices").fetchone()[0],before)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM master_stock_events").fetchone()[0],0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM sister_invoice_submission_keys").fetchone()[0],0)

    def test_factory_one_step_posts_mehr_debt_without_home_stock(self):
        from daily_sales_service.sister_invoices import submit_invoice
        items={"بزرگ":{"qty":3,"purchase":80000,"sale":120000}}
        iid=submit_invoice(self.db,"مشتری کارخانه","",self.day,"factory",items,"",
                           "factory-once",initial_amount="100000",destination="mehr",paid_on=self.day)
        self.assertEqual(mehr_balance(self.db)["debt"],240000)
        self.assertEqual(mehr_balance(self.db)["credit"],100000)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM master_stock_events").fetchone()[0],0)
        self.assertEqual(self.db.execute("SELECT status FROM sister_invoices WHERE id=?",(iid,)).fetchone()[0],"dispatched")

    def test_one_step_ambiguous_home_sku_must_be_selected(self):
        from daily_sales_service.sister_invoices import submit_invoice
        self.db.execute("""INSERT INTO master_products
            (category,code,title,size,color,sale_price_toman,cost_toman,
             seller_stock,digikala_stock,khorshid_stock,active,created_at,updated_at)
            VALUES ('قالب','alt-small','تست دوم','کوچک','سفید',0,40000,0,0,0,1,?,?)""",
            (self.day,self.day))
        items={"کوچک":{"qty":1,"purchase":40000,"sale":70000}}
        with self.assertRaisesRegex(ImportErrorDetail,"چند کالای واقعی"):
            submit_invoice(self.db,"مشتری مبهم","",self.day,"home",items,"","ambiguous")
        items["کوچک"]["master_id"]=self.skus["کوچک"]
        iid=submit_invoice(self.db,"مشتری مشخص","",self.day,"home",items,"","selected")
        self.assertTrue(iid)

    def test_finance_open_invoices_lists_unpaid_only_and_unallocated_receipts(self):
        from daily_sales_service.sister_invoices import submit_invoice
        from daily_sales_service.sister_finance_api import open_invoice_balances
        from daily_sales_service.app import app
        iid=submit_invoice(self.db,"مشتری حساب باز","",self.day,"home",
                           {"کوچک":{"qty":1,"purchase":40000,"sale":70000}},
                           "","open-sample",initial_amount="30000",destination="mine",paid_on=self.day)
        html=open_invoice_balances(conn=self.db).body.decode("utf-8")
        self.assertIn("مشتری حساب باز",html)
        self.assertIn("40,000",html)
        self.assertIn("30,000",html)
        self.assertIn("بانک نامشخص",html)
        record_receipt(self.db,iid,40000,"mine",self.day,"full-payment")
        html2=open_invoice_balances(conn=self.db).body.decode("utf-8")
        self.assertNotIn("مشتری حساب باز",html2)


    def test_mehr_net_receivable_and_bank_free_18m_payment(self):
        from daily_sales_service.app import app
        from daily_sales_service.sister_invoice_api import supplier
        from daily_sales_service.sister_finance_api import finance_home,open_invoice_balances
        from daily_sales_service.sister_finance_logic import overview
        # Mirror the user's verified ledger totals; no purchases or stock writes.
        from daily_sales_service.sister_invoices import _ledger
        self.db.execute("BEGIN IMMEDIATE")
        _ledger(self.db,self.day,76000000,0,"factory_invoice","test-factory-mehr")
        _ledger(self.db,self.day,41496000,0,"purchase_general","test-extra-mehr")
        _ledger(self.db,self.day,0,58000000,"customer_to_mehr","test-customer-mehr")
        self.db.execute("COMMIT")
        self.assertEqual(mehr_balance(self.db),{"debt":117496000,"credit":58000000,"net":-59496000})
        home=finance_home(conn=self.db).body.decode("utf-8")
        self.assertIn("بدهی خالص من به مه هر",home)
        self.assertIn("59,496,000",home)
        self.assertIn("طلب خالص من از مه هر",home)
        accounts=open_invoice_balances(conn=self.db).body.decode("utf-8")
        self.assertIn("59,496,000",accounts)
        form=supplier(conn=self.db).body.decode("utf-8")
        self.assertIn("59,496,000",form)
        self.assertIn("طلب خالص من از مه هر",form)
        self.assertNotIn('name="account_id"',form)
        before=self.db.execute("SELECT COUNT(*) FROM sister_finance_movements").fetchone()[0]
        settlement(self.db,"paid_to_mehr",18000000,self.day,"test-paid-18m",notes="تسویه بخشی")
        self.assertEqual(mehr_balance(self.db),{"debt":99496000,"credit":58000000,"net":-41496000})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM sister_finance_movements").fetchone()[0],before)
        row=self.db.execute("""SELECT notes FROM sister_mehr_ledger WHERE reference='test-paid-18m'""").fetchone()
        self.assertIn("حساب بانکی نامشخص",row["notes"])
        with self.assertRaisesRegex(ImportErrorDetail,"قبلاً ثبت"):
            settlement(self.db,"paid_to_mehr",18000000,self.day,"test-paid-18m")
        with self.assertRaisesRegex(ImportErrorDetail,"بدهی خالص"):
            settlement(self.db,"paid_to_mehr",41496001,self.day,"test-overpay")

    def test_mehr_bank_free_received_only_if_net_credit_exists(self):
        from daily_sales_service.sister_invoices import _ledger
        with self.assertRaisesRegex(ImportErrorDetail,"طلب خالص"):
            settlement(self.db,"received_from_mehr",10000,self.day,"not-due")
        self.db.execute("BEGIN IMMEDIATE")
        _ledger(self.db,self.day,20000,0,"purchase_general","debt-min")
        _ledger(self.db,self.day,0,30000,"customer_to_mehr","credit-plus")
        self.db.execute("COMMIT")
        settlement(self.db,"received_from_mehr",10000,self.day,"bank-free-credit")
        self.assertEqual(mehr_balance(self.db)["net"],0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM sister_finance_movements").fetchone()[0],0)

if __name__=="__main__":
    unittest.main()
