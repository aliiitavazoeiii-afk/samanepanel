"""Darma-style XLSX daily sheet is the only DigiKala sales landing.

Verify real strict-mode preview, two files, stock, receivable, receipt and
total-capital invariants (profit never double-counted).
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_engine import make_xlsx
from daily_sales_service.engine import init_db,create_preview,commit_preview
from daily_sales_service.effective_costs import schedule_cost,today
from daily_sales_service.master_v2_logic import add_model,batch_adjust,sku_rows
from daily_sales_service.digikala_daily_ui import daily_page,preview_page,_sold_rows
from daily_sales_service.capital_api import financial_capital,capital_report
from daily_sales_service.sister_finance_logic import (
    platform_balances,register_movement,add_account,parties,sales_report,accounts
)

class DigiKalaDailyCapitalTest(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.patcher=patch.dict(os.environ,{"SALES_MASTER_STRICT":"1"})
        self.patcher.start();self.addCleanup(self.patcher.stop)
        self.conn=init_db(Path(self.folder.name)/"test.sqlite3")
        self.addCleanup(self.conn.close)
        add_model(self.conn,"شورت زنانه دارما","کلاسیک","","مشکی","M")
        sku=sku_rows(self.conn,"شورت زنانه دارما")[0]
        self.sku_id=sku["id"]
        batch_adjust(self.conn,"شورت زنانه دارما",self.sku_id,"M","home",
                     {self.sku_id:10},"موجودی شروع آزمایش")
        schedule_cost(self.conn,"شورت زنانه دارما","","*",80000,today())
        self.variant=int(self.conn.execute(
            "SELECT variant_id FROM products WHERE active=1 AND master_id IS NULL ORDER BY variant_id LIMIT 1"
        ).fetchone()[0])
        self.conn.execute("UPDATE products SET master_id=?,sale_price_toman=? WHERE variant_id=?",
                          (self.sku_id,500000,self.variant))
        self.bank=add_account(self.conn,"ملت",0)

    def _upload(self,n=1,files=2):
        header=["کد تنوع","تعداد ارسالی","قیمت فروش (تومان)"]
        docs=[("part-"+str(i)+".xlsx",make_xlsx([header,[self.variant,n,500000]]))
              for i in range(files)]
        return create_preview(self.conn,today(),"seller",docs)

    def test_two_files_preview_shows_darma_style_sheet_and_stock_unchanged(self):
        before=financial_capital(self.conn)
        prepared=self._upload(1,2)
        self.assertEqual(prepared["files_count"],2)
        self.assertEqual(len(prepared["rows"]),1)
        self.assertEqual(prepared["rows"][0]["qty"],2)
        self.assertEqual(self.conn.execute(
            "SELECT seller_stock FROM master_products WHERE id=?",(self.sku_id,)
        ).fetchone()[0],10)
        self.assertEqual(financial_capital(self.conn)["total_capital"],before["total_capital"])
        html=preview_page(prepared).body.decode("utf-8")
        for required in ("پیش‌نمایش صورت دیجی‌کالا","فایل اکسل","هزینه دیجی‌کالا",
                         "بهای تمام‌شده","طلب","تأیید نهایی"):
            self.assertIn(required,html)
        self.assertIn("2 فایل",html)

    def test_sale_increases_capital_only_by_profit_and_receipt_is_transfer(self):
        baseline=financial_capital(self.conn)
        self.assertEqual(baseline["total_capital"],800000)
        preview=self._upload(1,2)
        committed=commit_preview(self.conn,preview["token"])
        self.assertEqual(committed["units"],2)
        self.assertEqual(self.conn.execute(
            "SELECT seller_stock FROM master_products WHERE id=?",(self.sku_id,)
        ).fetchone()[0],8)
        report=sales_report(self.conn,"digikala")
        self.assertEqual(report["gross"],1000000)
        self.assertEqual(report["cogs_known"],160000)
        balance=platform_balances(self.conn)["digikala"]
        self.assertEqual(balance["outstanding"],report["net"])
        after=financial_capital(self.conn)
        self.assertEqual(after["total_capital"]-baseline["total_capital"],report["profit"])
        self.assertEqual(after["total_capital"],640000+report["net"])
        self.assertEqual(after["sales_profit"],report["profit"])
        self.assertEqual(len(_sold_rows(self.conn,today())),1)
        self.assertEqual(_sold_rows(self.conn,today())[0]["units"],2)
        self.assertEqual(_sold_rows(self.conn,today())[0]["size"],"M")
        self.assertEqual(_sold_rows(self.conn,today())[0]["brand"],"شورت زنانه دارما")
        party=next(x for x in parties(self.conn) if x["code"]=="digikala")
        register_movement(self.conn,"receipt",party["id"],self.bank,200000,today(),"digi-bank")
        received=financial_capital(self.conn)
        self.assertEqual(received["total_capital"],after["total_capital"])
        self.assertEqual(received["cash_balance"],200000)
        self.assertEqual(received["total_receivable"],after["total_receivable"]-200000)
        self.assertEqual(accounts(self.conn)[0]["balance"],200000)

    def test_reupload_same_day_replaces_sold_units_and_claim_not_doubles(self):
        first=self._upload(1,2)
        commit_preview(self.conn,first["token"])
        a=financial_capital(self.conn)
        second=self._upload(1,2)
        commit_preview(self.conn,second["token"])
        self.assertEqual(financial_capital(self.conn)["total_capital"],a["total_capital"])
        self.assertEqual(platform_balances(self.conn)["digikala"]["outstanding"],a["total_receivable"])
        self.assertEqual(self.conn.execute(
            "SELECT seller_stock FROM master_products WHERE id=?",(self.sku_id,)
        ).fetchone()[0],8)
        revised=self._upload(1,1)
        commit_preview(self.conn,revised["token"])
        expected=sales_report(self.conn,"digikala")
        self.assertEqual(self.conn.execute(
            "SELECT seller_stock FROM master_products WHERE id=?",(self.sku_id,)
        ).fetchone()[0],9)
        self.assertEqual(financial_capital(self.conn)["total_capital"]-800000,expected["profit"])

    def test_digikala_page_contains_only_selected_day_and_brand_size_report(self):
        day=daily_page(self.conn,today()).body.decode("utf-8")
        self.assertIn("بارگذاری اکسل دیجی‌کالا",day)
        self.assertIn('type="file"',day)
        self.assertIn("multiple",day)
        for forbidden in ("گزارش تفکیک گروه کالا","فروش ثبت‌شده پلتفرم‌های دیگر",
                          "دریافت CSV", "ریز فروش‌ها (حداکثر"):
            self.assertNotIn(forbidden,day)
        self.assertNotIn("خلاصه برندهای فروخته‌شده",day)  # no day sales yet
        result=self._upload(1,2);commit_preview(self.conn,result["token"])
        body=daily_page(self.conn,today(),brand="شورت زنانه دارما",size="M").body.decode("utf-8")
        self.assertLess(body.index("بارگذاری اکسل دیجی‌کالا"),body.index("خلاصه برندهای فروخته‌شده"))
        for required in ("خلاصه برندهای فروخته‌شده","مدل‌ها و سایزهای فروخته‌شده",
                         "طلب ایجادشده از دیجی‌کالا","بهای تمام‌شده کالا",
                         "شورت زنانه دارما","مشکی","M","سود فروش"):
            self.assertIn(required,body)
        for forbidden in ("گزارش تفکیک گروه کالا","فروش ثبت‌شده پلتفرم‌های دیگر",
                          "دریافت CSV","مانده مطالبات پلتفرم‌ها"):
            self.assertNotIn(forbidden,body)

    def test_capital_report_shows_stock_claim_bank_without_duplicate_profit(self):
        self._post_one()
        info=financial_capital(self.conn)
        html=capital_report(conn=self.conn).body.decode("utf-8")
        for label in ("جمع سرمایه اصلی","ارزش موجودی انبارها",
                      "طلب از پلتفرم‌ها","مانده حساب‌ها و صندوق",
                      "سود فروش تحقق‌یافته","بدون دوباره‌شماری سود"):
            self.assertIn(label,html)
        self.assertIn(f'{info["total_capital"]:,}',html)
        self.assertEqual(info["total_capital"],
                         info["total_value"]+info["total_receivable"]+info["cash_balance"])

    def _post_one(self):
        result=self._upload(1,1)
        commit_preview(self.conn,result["token"])

if __name__=="__main__":unittest.main()
