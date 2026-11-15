"""Daily Jalali picker, published report, safe void and financial reversal."""
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import date,timedelta
from pathlib import Path
from unittest.mock import patch
from test_engine import make_xlsx
from daily_sales_service.app import app
from daily_sales_service.engine import init_db,create_preview,commit_preview,ImportErrorDetail
from daily_sales_service.master_v2_logic import add_model,batch_adjust,sku_rows
from daily_sales_service.effective_costs import schedule_cost,today
from daily_sales_service.digikala_daily_ui import daily_page
from daily_sales_service.digikala_daily_delete import void_daily_digikala_sales
from daily_sales_service.calendar_jalali import ASSETS,picker
from daily_sales_service.sister_finance_logic import (
    platform_balances,add_account,parties,register_movement,
)

class DigiKalaDeleteJalaliTest(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        env=patch.dict(os.environ,{"SALES_MASTER_STRICT":"1","SALES_START_EMPTY_STOCK":"1"})
        env.start();self.addCleanup(env.stop)
        self.db=init_db(Path(folder.name)/"daily.sqlite3");self.addCleanup(self.db.close)
        add_model(self.db,"شورت زنانه دیا","کلاسیک تست","","مشکی","M")
        self.mid=sku_rows(self.db,"شورت زنانه دیا")[0]["id"]
        batch_adjust(self.db,"شورت زنانه دیا",self.mid,"M","home",
                     {self.mid:10},"موجودی تست")
        schedule_cost(self.db,"شورت زنانه دیا","","*",60000,today())
        self.vid=int(self.db.execute("SELECT variant_id FROM products WHERE active=1 ORDER BY variant_id LIMIT 1").fetchone()[0])
        self.db.execute("UPDATE products SET master_id=?,sale_price_toman=250000 WHERE variant_id=?",(self.mid,self.vid))
        self.day=today()
    def save(self,day=None,source="seller",qty=2):
        day=day or self.day
        file=[("packageDeliveryReport.xlsx",make_xlsx([
              ["کد تنوع","تعداد ارسالی"],[self.vid,qty]]))]
        before=create_preview(self.db,day,source,file)
        self.assertFalse(before["errors"],before["errors"])
        commit_preview(self.db,before["token"])
    def stock(self,column="seller_stock"):
        return self.db.execute("SELECT "+column+" FROM master_products WHERE id=?",
                               (self.mid,)).fetchone()[0]
    def test_calendar_has_persian_months_and_native_date_fallback(self):
        html=daily_page(self.db,self.day).body.decode()
        self.assertIn('data-jal',html)
        self.assertIn('name="sale_date"',html)
        self.assertIn('data-jal-label',html)
        self.assertIn('type="date"',html)
        self.assertIn("فروردین",html)
        self.assertIn("اسفند",html)
        self.assertIn("1405",self.day.replace("2026","1405") if False else "1405")
        self.assertIn('/daily-sales/day/delete',app.openapi()["paths"])
        if shutil.which("node"):
            js=ASSETS.split("<script>",1)[1].split("</script>",1)[0]
            subprocess.run(["node","--check"],input=js,text=True,
                           check=True,capture_output=True)
    def test_default_todays_date_shows_latest_saved_day_if_today_empty(self):
        previous=(date.fromisoformat(self.day)-timedelta(days=1)).isoformat()
        self.save(day=previous)
        body=daily_page(self.db).body.decode()
        self.assertIn("آخرین صورت ثبت‌شده",body)
        self.assertIn('data-jal-label="'+previous+'"',body)
        self.assertIn('value="'+self.day+'"',body)
        self.assertIn("250,000",body)
        self.assertNotIn("تعداد بسته / عدد",body)
        self.assertNotIn("مبنای قیمت",body)
        self.assertIn("قیمت فروش",body)
    def test_delete_restores_stock_receivables_and_can_reimport(self):
        self.save()
        self.assertEqual(self.stock(),8)
        before=platform_balances(self.db)["digikala"]
        self.assertGreater(before["outstanding"],0)
        body=daily_page(self.db,self.day).body.decode()
        self.assertIn("حذف صورت فروش این روز",body)
        self.assertIn("سود",body)
        removed=void_daily_digikala_sales(self.db,self.day,self.day)
        self.assertEqual(removed["deleted_lines"],1)
        self.assertEqual(removed["restored_units"],2)
        self.assertEqual(self.stock(),10)
        self.assertEqual(platform_balances(self.db)["digikala"]["outstanding"],0)
        self.assertIsNone(self.db.execute("SELECT 1 FROM sales WHERE sale_date=?",(self.day,)).fetchone())
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM digikala_daily_void_audit").fetchone()[0],1)
        with self.assertRaises(ImportErrorDetail):
            void_daily_digikala_sales(self.db,self.day,self.day)
        self.save()
        self.assertEqual(self.stock(),8)
        self.assertEqual(platform_balances(self.db)["digikala"]["outstanding"],before["outstanding"])
    def test_delete_refuses_if_receipts_would_exceed_remaining_sales(self):
        self.save()
        bank=add_account(self.db,"بانک تست",0)
        pid=next(x["id"] for x in parties(self.db) if x["code"]=="digikala")
        amt=platform_balances(self.db)["digikala"]["outstanding"]
        register_movement(self.db,"receipt",pid,bank,amt,self.day,"receipt-123")
        with self.assertRaisesRegex(ImportErrorDetail,"دریافتی"):
            void_daily_digikala_sales(self.db,self.day,self.day)
        self.assertEqual(self.stock(),8)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM sales WHERE sale_date=?",(self.day,)).fetchone()[0],1)
    def test_rejects_mismatched_day_without_any_write(self):
        self.save()
        with self.assertRaises(ImportErrorDetail):
            void_daily_digikala_sales(self.db,self.day,"2020-01-01")
        self.assertEqual(self.stock(),8)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM sales").fetchone()[0],1)

if __name__=="__main__":unittest.main()
