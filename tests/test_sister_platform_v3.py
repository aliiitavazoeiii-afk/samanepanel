"""Tests for effective-dated costs, separate platform listings and atomic stock sale."""
import unittest
import tempfile
from pathlib import Path
from datetime import date,timedelta

from daily_sales_service.engine import init_db,ImportErrorDetail
from daily_sales_service.master_v2_logic import add_model,batch_adjust,sku_rows
from daily_sales_service.effective_costs import (
    schedule_cost,dated_cost,capital_snapshot,today
)
from daily_sales_service.platform_catalog import (
    create_listing,list_listings,book_sale,sale_summary
)
from daily_sales_service.master_v2_logic import set_channel_prices,channel_price_for

class PlatformV3Test(unittest.TestCase):
 def setUp(self):
    tmp=tempfile.TemporaryDirectory()
    self.addCleanup(tmp.cleanup)
    self.conn=init_db(Path(tmp.name)/"test.sqlite3")
    self.addCleanup(self.conn.close)
    add_model(self.conn,"شورت زنانه دارما","Darma G","","مشکی","M")
    self.sku=sku_rows(self.conn,"شورت زنانه دارما")[0]

 def seed(self,qty=20):
    mid=self.sku["id"]
    batch_adjust(self.conn,self.sku["category"],mid,self.sku["size"],"home",{mid:qty},"شمارش دوره‌ای")

 def test_future_cost_rule_changes_capital_only_on_effective_day(self):
    self.seed(15)
    start=today()
    future=(date.fromisoformat(start)+timedelta(days=1)).isoformat()
    schedule_cost(self.conn,"شورت زنانه دارما","","*",70000,start)
    schedule_cost(self.conn,"شورت زنانه دارما","","*",90000,future)
    self.assertEqual(dated_cost(self.conn,self.sku,start),70000)
    self.assertEqual(dated_cost(self.conn,self.sku,future),90000)
    self.assertEqual(capital_snapshot(self.conn,start)["total_value"],1050000)
    self.assertEqual(capital_snapshot(self.conn,future)["total_value"],1350000)
    self.assertEqual(capital_snapshot(self.conn,start)["units"],15)
    with self.assertRaises(ImportErrorDetail):
        schedule_cost(self.conn,"شورت زنانه دارما","","*",1,
           (date.fromisoformat(start)-timedelta(days=1)).isoformat())

 def test_bodyguard_and_mold_separate_effective_dates(self):
    add_model(self.conn,"بادیگارد","بادیگارد پایه","اسلیپ","مشکی","XL")
    add_model(self.conn,"بادیگارد","بادیگارد پایه","پادار","مشکی","XL")
    add_model(self.conn,"قالب","قالب کفش","","طبیعی","کوچک، متوسط، بزرگ")
    start=today()
    for subtype,cost in (("اسلیپ",40000),("پادار",60000)):
        schedule_cost(self.conn,"بادیگارد",subtype,"*",cost,start)
    for size,cost in (("کوچک",100000),("متوسط",130000),("بزرگ",160000)):
        schedule_cost(self.conn,"قالب","",size,cost,start)
    self.assertEqual({r["subtype"]:dated_cost(self.conn,r) for r in sku_rows(self.conn,"بادیگارد")},{"اسلیپ":40000,"پادار":60000})
    self.assertEqual({r["size"]:dated_cost(self.conn,r) for r in sku_rows(self.conn,"قالب")},{"کوچک":100000,"متوسط":130000,"بزرگ":160000})

 def test_platform_listing_three_pack_uses_master_sku_and_site_price(self):
    self.seed()
    set_channel_prices(self.conn,"site","شورت زنانه دارما","","M",100000)
    pid=create_listing(self.conn,"site",self.sku["id"],"پک سه‌عددی",3)
    row=list_listings(self.conn,"site")[0]
    self.assertEqual(row["master_id"],self.sku["id"])
    self.assertEqual(row["unit_price"]*row["pack_qty"],300000)
    sale=book_sale(self.conn,"site",pid,2,"home",today(),"site-123")
    self.assertEqual(sale["units"],6)
    self.assertEqual(sale["gross"],600000)
    self.assertEqual(self.conn.execute("SELECT seller_stock FROM master_products WHERE id=?",(self.sku["id"],)).fetchone()[0],14)
    self.assertEqual(sale_summary(self.conn)["site"]["units"],6)
    with self.assertRaises(ImportErrorDetail):
        book_sale(self.conn,"site",pid,2,"home",today(),"site-123")
    self.assertEqual(self.conn.execute("SELECT seller_stock FROM master_products WHERE id=?",(self.sku["id"],)).fetchone()[0],14)

 def test_two_platforms_share_one_stock_and_invalid_sale_does_not_deduct(self):
    self.seed(5)
    set_channel_prices(self.conn,"site","شورت زنانه دارما","","M",50000)
    set_channel_prices(self.conn,"basalam","شورت زنانه دارما","","M",60000)
    site=create_listing(self.conn,"site",self.sku["id"],"پک دو",2)
    salam=create_listing(self.conn,"basalam",self.sku["id"],"تکی",1)
    book_sale(self.conn,"site",site,2,"home",today(),"s-22")
    with self.assertRaises(ImportErrorDetail):
        book_sale(self.conn,"basalam",salam,2,"home",today(),"b-10")
    self.assertEqual(self.conn.execute("SELECT seller_stock FROM master_products WHERE id=?",(self.sku["id"],)).fetchone()[0],1)
    book_sale(self.conn,"basalam",salam,1,"home",today(),"b-10")
    self.assertEqual(self.conn.execute("SELECT seller_stock FROM master_products WHERE id=?",(self.sku["id"],)).fetchone()[0],0)

 def test_mold_platform_rejects_wrong_category_and_unpriced_sale(self):
    with self.assertRaises(ImportErrorDetail):
        create_listing(self.conn,"mold",self.sku["id"],"قالب",1)
    self.seed(1)
    lid=create_listing(self.conn,"basalam",self.sku["id"],"تکی",1)
    with self.assertRaises(ImportErrorDetail):
        book_sale(self.conn,"basalam",lid,1,"home",today(),"order-z")
    self.assertEqual(self.conn.execute("SELECT seller_stock FROM master_products WHERE id=?",(self.sku["id"],)).fetchone()[0],1)

 def test_ui_paths_and_calculation(self):
    from daily_sales_service.master_v2_api import router
    from daily_sales_service.platform_api import channel_page,platforms
    from daily_sales_service.capital_api import capital_report,capital_data
    from daily_sales_service.platform_api import router as platform_router
    from daily_sales_service.capital_api import router as capital_router
    paths={r.path for rr in (router,platform_router,capital_router)
           for r in rr.routes if hasattr(r,"path")}
    for suffix in ("/platforms","/platforms/{channel}","/platforms/{channel}/add",
                   "/platforms/{channel}/sales","/platforms/{channel}/sales/add",
                   "/capital-report","/api/sister-capital.json"):
        self.assertIn("/daily-sales"+suffix,paths)
    home=platforms(conn=self.conn).body.decode()
    for name in ("دیجی‌کالا","باسلام","سایت","قالب‌ها"):self.assertIn(name,home)
    detail=channel_page("basalam",category=self.sku["category"],conn=self.conn).body.decode()
    self.assertIn("تعریف محصول",detail)
    self.assertIn("جستجو",detail)
    self.assertIn("فهرست محصولات ثبت‌شده",detail)
    self.assertIn("مشکی",detail)
    self.assertIn("M",detail)
    self.assertIn("گزارش جامع سرمایه",capital_report(conn=self.conn).body.decode())

if __name__=="__main__":unittest.main()
