"""Integration regression for dated DigiKala prices, bulk archive and capital."""
import tempfile
import unittest
from datetime import date,timedelta
from pathlib import Path

from daily_sales_service.app import app
from daily_sales_service.engine import init_db,ImportErrorDetail
from daily_sales_service.dk_dated_prices import effective_price,save_dated_prices
from daily_sales_service.master_engine import _daily_digikala_price
from daily_sales_service.dk_catalog_preferences import bulk_archive,set_archived
from daily_sales_service.dk_pricing_ui import digikala_pricing,records,family
from daily_sales_service.master_v2_logic import add_model,batch_adjust,sku_rows
from daily_sales_service.effective_costs import today,schedule_cost
from daily_sales_service.capital_components import components,save_component
from daily_sales_service.capital_api import financial_capital,capital_report

class DatedPriceBulkCapitalTest(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.db=init_db(Path(tmp.name)/"sister.sqlite3")
        self.addCleanup(self.db.close)
        self.first=int(self.db.execute("SELECT variant_id FROM products WHERE active=1 ORDER BY variant_id LIMIT 1").fetchone()[0])
        self.second=int(self.db.execute("SELECT variant_id FROM products WHERE active=1 AND variant_id<>? ORDER BY variant_id LIMIT 1",(self.first,)).fetchone()[0])

    def variant(self,vid):
        return dict(self.db.execute("SELECT * FROM products WHERE variant_id=?",(vid,)).fetchone())

    def test_dated_price_is_exact_pack_and_uses_sale_day_not_upload_day(self):
        today_key=today()
        later=(date.fromisoformat(today_key)+timedelta(days=2)).isoformat()
        before=_daily_digikala_price(self.db,self.variant(self.first),None,today_key)
        save_dated_prices(self.db,{self.first:510000},today_key)
        save_dated_prices(self.db,{self.first:560000},later)
        self.assertEqual(effective_price(self.db,self.first,today_key),(510000,today_key))
        self.assertEqual(effective_price(self.db,self.first,later),(560000,later))
        self.assertEqual(_daily_digikala_price(self.db,self.variant(self.first),None,today_key)[0],510000)
        self.assertEqual(_daily_digikala_price(self.db,self.variant(self.first),None,later)[0],560000)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM dk_dated_sale_prices").fetchone()[0],2)
        with self.assertRaises(ImportErrorDetail):
            save_dated_prices(self.db,{self.first:500000},
                              (date.fromisoformat(today_key)-timedelta(days=1)).isoformat())

    def test_pricing_page_categories_and_bodyguard_subtype_selection(self):
        self.assertIn("/daily-sales/pricing/digikala",app.openapi()["paths"])
        self.assertIn("post",app.openapi()["paths"]["/daily-sales/pricing/digikala/save"])
        page=digikala_pricing(conn=self.db).body.decode("utf-8")
        self.assertIn("شورت زنانه دارما",page)
        self.assertIn("شورت زنانه دیا",page)
        self.assertIn("شورت مردانه بادیگارد",page)
        page=digikala_pricing(category="بادیگارد",conn=self.db).body.decode("utf-8")
        self.assertIn("اسلیپ",page)
        self.assertIn("پادار",page)
        details=digikala_pricing(category="بادیگارد",subtype="اسلیپ",conn=self.db).body.decode("utf-8")
        self.assertIn("قیمت‌گذاری دیجی‌کالا",details)
        self.assertIn("شروع اجرای قیمت جدید",details)

    def test_atomic_bulk_archive_preserves_538_source_rows_and_old_sales(self):
        count=self.db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        self.db.execute("""INSERT INTO sales(sale_date,source,variant_id,qty,price_toman,
               commission_toman,processing_toman,vat_toman,fee_toman,cost_toman)
               VALUES('2026-11-14','seller',?,1,400000,10000,2000,1000,13000,100000)""",
               (self.first,))
        with self.assertRaises(ImportErrorDetail):
            bulk_archive(self.db,[self.first,999999999])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM dk_catalog_preferences WHERE archived=1").fetchone()[0],0)
        self.assertEqual(bulk_archive(self.db,[self.first,self.second]),2)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM products").fetchone()[0],count)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM sales").fetchone()[0],1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM dk_catalog_preferences WHERE archived=1").fetchone()[0],2)
        visible={r["variant_id"] for r in records(self.db)}
        self.assertNotIn(self.first,visible)
        self.assertNotIn(self.second,visible)
        with self.assertRaises(ImportErrorDetail):bulk_archive(self.db,[self.first])
        set_archived(self.db,self.first,False)
        self.assertIn(self.first,{r["variant_id"] for r in records(self.db)})

    def test_real_stock_and_manual_assets_are_distinct_not_double_counted(self):
        add_model(self.db,"شورت زنانه دیا","مدل تست","","مشکی","M")
        mid=int(sku_rows(self.db,"شورت زنانه دیا")[0]["id"])
        batch_adjust(self.db,"شورت زنانه دیا",mid,"M","home",{mid:10},"موجودی افتتاحیه")
        schedule_cost(self.db,"شورت زنانه دیا","","*",50000,today())
        initial=financial_capital(self.db)
        self.assertEqual(initial["total_value"],500000)
        self.assertEqual(initial["total_capital"],500000)
        save_component(self.db,"raw_materials",100000)
        save_component(self.db,"equipment",200000)
        save_component(self.db,"other_liabilities",30000)
        value=financial_capital(self.db)
        self.assertEqual(value["total_capital"],770000)
        self.assertEqual(value["raw_materials"],100000)
        self.assertEqual(value["equipment"],200000)
        self.assertEqual(value["liabilities"],30000)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM sister_capital_component_audit").fetchone()[0],3)
        html=capital_report(conn=self.db).body.decode("utf-8")
        self.assertIn("770,000",html)
        self.assertIn("کالای آماده",html)
        self.assertIn("طلب پلتفرم‌های فروش",html)
        self.assertIn("مواد اولیه",html)
        self.assertNotIn("موجودی به تفکیک کالا",html)
        self.assertNotIn("تکوین",html)

    def test_unknown_cost_marks_capital_incomplete_not_zero(self):
        add_model(self.db,"شورت زنانه دارما","محصول بی‌هزینه","","کرم","M")
        sku=sku_rows(self.db,"شورت زنانه دارما")[0]
        batch_adjust(self.db,"شورت زنانه دارما",sku["id"],"M","home",
                     {sku["id"]:4},"موجودی افتتاحیه")
        value=financial_capital(self.db)
        self.assertIsNone(value["total_capital"])
        self.assertEqual(value["unknown_units"],4)
        self.assertEqual(value["known_components_total"],0)
        html=capital_report(conn=self.db).body.decode("utf-8")
        self.assertIn("جمع اقلام ارزش‌گذاری‌شده (ناقص)",html)
        self.assertIn("4",html)
        self.assertIn("تکمیل بهای تمام‌شده",html)

if __name__=="__main__":
    unittest.main()
