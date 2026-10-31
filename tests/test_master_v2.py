"""Regression tests: definition-only, split cost/selling-price and Darma-like warehouses."""
import os
import tempfile
import unittest
from pathlib import Path

from test_engine import make_xlsx
from daily_sales_service.engine import init_db, create_preview, commit_preview
from daily_sales_service.master_engine import map_variant, ImportErrorDetail
from daily_sales_service.master_v2_logic import (
    add_model, batch_adjust, batch_transfer, cost_for, channel_price_for,
    list_models, sku_rows, set_cost_rule, set_channel_prices,
)

class MasterV2Test(unittest.TestCase):
 def setUp(self):
  previous=os.getenv("SALES_MASTER_STRICT")
  os.environ["SALES_MASTER_STRICT"]="1"
  self.addCleanup(lambda: os.environ.pop("SALES_MASTER_STRICT",None) if previous is None else os.environ.__setitem__("SALES_MASTER_STRICT",previous))
  directory=tempfile.TemporaryDirectory()
  self.addCleanup(directory.cleanup)
  self.conn=init_db(Path(directory.name)/"db.sqlite3")
  self.addCleanup(self.conn.close)

 def make(self,category="شورت زنانه دیا",title="مدل A",subtype="",colors="مشکی، سفید",sizes="M، L"):
  count=add_model(self.conn,category,title,subtype,colors,sizes)
  return count

 def test_verified_catalog_filters_show_all_colors_and_correct_bodyguard_types(self):
  from daily_sales_service.catalog_import import apply_catalog
  from daily_sales_service.master_v2_api import stock, master, operations
  from daily_sales_service.master_v2_logic import list_models
  data=apply_catalog(self.conn,dry_run=False)
  self.assertEqual(data["expected"],213)
  self.assertEqual(data["new"],213)
  self.assertEqual(len(list_models(self.conn,"بادیگارد","اسلیپ")),18)
  self.assertEqual(len(list_models(self.conn,"بادیگارد","پادار")),22)
  board=stock(category="بادیگارد",subtype="اسلیپ",conn=self.conn).body.decode("utf-8")
  self.assertIn("موجودی کل",board)
  self.assertIn("موجودی خانه",board)
  self.assertIn("موجودی انبار خورشید",board)
  self.assertIn("قرمز اسلیپ",board)
  self.assertIn("طوسی ملانژ",board)
  self.assertGreaterEqual(board.count('class="m2-table"'),3)
  form=operations(category="بادیگارد",subtype="اسلیپ",size="L",conn=self.conn).body.decode("utf-8")
  self.assertEqual(form.count('name="target_'),18)
  definitions=master(category="بادیگارد",subtype="اسلیپ",conn=self.conn).body.decode("utf-8")
  self.assertIn("18 رنگ",definitions)
  self.assertIn("شورت مردانه اسلیپ",definitions)
  self.assertNotIn("قیمت فروش (تومان)",definitions)

 def test_clean_ui_and_all_new_routes(self):
  from daily_sales_service.app import app
  from daily_sales_service.master_v2_api import router, master, stock, pricing, cost_prices, sales_prices
  paths={route.path for route in router.routes if hasattr(route,"path")}
  for suffix in ("/master","/master/add","/master/stock",
                 "/master/stock/operations","/pricing","/pricing/cost",
                 "/pricing/sales","/catalog"):
   self.assertIn("/daily-sales"+suffix,paths)
  response=master(category="بادیگارد",conn=self.conn)
  html=response.body.decode("utf-8")
  self.assertIn("تعریف محصولات",html)
  self.assertIn("اسلیپ",html)
  self.assertNotIn("کد کالا",html)
  self.assertNotIn("بهای تمام‌شده (تومان)",html)
  self.assertIn("</style>",html)
  self.make()
  stock_html=stock(category="شورت زنانه دیا",conn=self.conn).body.decode("utf-8")
  for label in ("موجودی کل","موجودی خانه","موجودی انبار خورشید"):
   self.assertIn(label,stock_html)
  prices=pricing(conn=self.conn).body.decode("utf-8")
  self.assertIn("بهای تمام‌شده",prices)
  self.assertIn("قیمت فروش",prices)
  self.assertIn("اسلیپ",cost_prices(conn=self.conn).body.decode("utf-8"))
  self.assertIn("فروش باسلام",sales_prices(conn=self.conn).body.decode("utf-8"))

 def test_auto_hidden_code_idempotent_and_two_warehouses(self):
  self.assertEqual(self.make(),4)
  self.assertEqual(self.make(),0)
  self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM master_products").fetchone()[0],4)
  skus=sku_rows(self.conn,"شورت زنانه دیا")
  self.assertEqual({x["size"] for x in skus},{"M","L"})
  self.assertEqual({x["color"] for x in skus},{"مشکی","سفید"})
  self.assertTrue(all(x["code"].startswith("AUTO-") for x in skus))
  mid=skus[0]["id"]
  batch_adjust(self.conn,"شورت زنانه دیا",mid,skus[0]["size"],"home",{mid:"11"},"شمارش انبار")
  # Prevent transfer of more than physical source inventory.
  with self.assertRaises(ImportErrorDetail):
   batch_transfer(self.conn,"شورت زنانه دیا",mid,skus[0]["size"],"home",{mid:12},"انتقال شمارش")
  batch_transfer(self.conn,"شورت زنانه دیا",mid,skus[0]["size"],"home",{mid:5},"انتقال به خورشید")
  row=self.conn.execute("SELECT seller_stock,khorshid_stock,digikala_stock FROM master_products WHERE id=?",(mid,)).fetchone()
  self.assertEqual(tuple(row),(6,5,0))
  self.assertEqual(sum(x[0] for x in self.conn.execute("SELECT delta FROM master_stock_events WHERE master_id=?",(mid,))),11)
  self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM master_transfers WHERE master_id=?",(mid,)).fetchone()[0],1)

 def test_atomic_bulk_adjustment_failure_rolls_back(self):
  self.make()
  skus=sku_rows(self.conn,"شورت زنانه دیا")
  mids=[x["id"] for x in skus if x["size"]=="M"]
  model_id=mids[0]
  with self.assertRaises(ImportErrorDetail):
   batch_adjust(self.conn,"شورت زنانه دیا",model_id,"M","home",{mids[0]:5,mids[1]:"-3"},"شمارش موجودی")
  self.assertEqual(self.conn.execute("SELECT SUM(seller_stock) FROM master_products").fetchone()[0],0)

 def test_undo_latest_adjustment_and_transfer_revision(self):
  from daily_sales_service.master_v2_corrections import undo_adjustment, revise_transfer
  self.make()
  sku=sku_rows(self.conn,"شورت زنانه دیا")[0]
  mid=sku["id"];size=sku["size"]
  batch_adjust(self.conn,"شورت زنانه دیا",mid,size,"home",{mid:12},"شمارش اول")
  batch_adjust(self.conn,"شورت زنانه دیا",mid,size,"home",{mid:9},"اشتباه در شمارش")
  event=self.conn.execute("SELECT id FROM master_stock_events WHERE master_id=? ORDER BY id DESC LIMIT 1",(mid,)).fetchone()[0]
  undo_adjustment(self.conn,event)
  self.assertEqual(self.conn.execute("SELECT seller_stock FROM master_products WHERE id=?",(mid,)).fetchone()[0],12)
  with self.assertRaises(ImportErrorDetail):
   undo_adjustment(self.conn,event)
  batch_transfer(self.conn,"شورت زنانه دیا",mid,size,"home",{mid:4},"ارسال به خورشید")
  transfer_id=self.conn.execute("SELECT id FROM master_transfers WHERE master_id=?",(mid,)).fetchone()[0]
  revise_transfer(self.conn,transfer_id,2)
  actual=self.conn.execute("SELECT seller_stock,khorshid_stock FROM master_products WHERE id=?",(mid,)).fetchone()
  self.assertEqual(tuple(actual),(10,2))
  revise_transfer(self.conn,transfer_id,0)
  actual=self.conn.execute("SELECT seller_stock,khorshid_stock FROM master_products WHERE id=?",(mid,)).fetchone()
  self.assertEqual(tuple(actual),(12,0))
  batch_adjust(self.conn,"شورت زنانه دیا",mid,size,"home",{mid:11},"شمارش پس از انتقال")
  with self.assertRaises(ImportErrorDetail):
   revise_transfer(self.conn,transfer_id,3)

 def test_cost_rules_by_bodyguard_type_and_mold_size(self):
  add_model(self.conn,"بادیگارد","اسلیپ زنانه","اسلیپ","مشکی","M")
  add_model(self.conn,"بادیگارد","پادار زنانه","پادار","مشکی","M")
  set_cost_rule(self.conn,"بادیگارد","اسلیپ","*",100000)
  set_cost_rule(self.conn,"بادیگارد","پادار","*",120000)
  skus=sku_rows(self.conn,"بادیگارد")
  self.assertEqual({r["subtype"]:cost_for(self.conn,r) for r in skus},{"اسلیپ":100000,"پادار":120000})
  add_model(self.conn,"قالب","قالب طبی","","","کوچک، متوسط، بزرگ")
  for size,value in (("کوچک",50000),("متوسط",60000),("بزرگ",70000)):
   set_cost_rule(self.conn,"قالب","",size,value)
  self.assertEqual({r["size"]:cost_for(self.conn,r) for r in sku_rows(self.conn,"قالب")},
                   {"کوچک":50000,"متوسط":60000,"بزرگ":70000})

 def test_site_basalam_mold_prices_independent_of_digikala(self):
  self.make()
  set_channel_prices(self.conn,"site","شورت زنانه دیا","","M",330000)
  set_channel_prices(self.conn,"basalam","شورت زنانه دیا","","*",310000)
  skus=sku_rows(self.conn,"شورت زنانه دیا")
  for x in skus:
   self.assertEqual(channel_price_for(self.conn,x["id"],"basalam"),310000)
   self.assertEqual(channel_price_for(self.conn,x["id"],"site"),330000 if x["size"]=="M" else None)
  self.assertIsNone(self.conn.execute("SELECT sale_price_toman FROM products LIMIT 1").fetchone()[0])

 def test_digikala_sales_at_khorshid_and_reimport(self):
  add_model(self.conn,"زیرپوش دارما","مدل B","","مشکی","L")
  sku=sku_rows(self.conn,"زیرپوش دارما")[0]
  mid=sku["id"]
  set_cost_rule(self.conn,"زیرپوش دارما","","*",90000)
  batch_adjust(self.conn,"زیرپوش دارما",mid,"L","khorshid",{mid:7},"شمارش خورشید")
  variant_id=self.conn.execute("SELECT variant_id FROM products WHERE active=1 LIMIT 1").fetchone()[0]
  map_variant(self.conn,variant_id,mid,500000)
  def xlsx(qty):
   return [("order.xlsx",make_xlsx([["کد تنوع","تعداد ارسالی","وضعیت","قیمت فروش (تومان)"],[variant_id,qty,"دریافت",500000]]))]
  day="2026-10-31"
  p=create_preview(self.conn,day,"khorshid",xlsx(2))
  self.assertFalse(p["errors"],p["errors"])
  self.assertEqual(p["rows"][0]["cost"],90000)
  commit_preview(self.conn,p["token"])
  self.assertEqual(self.conn.execute("SELECT khorshid_stock FROM master_products WHERE id=?",(mid,)).fetchone()[0],5)
  p=create_preview(self.conn,day,"khorshid",xlsx(2))
  commit_preview(self.conn,p["token"])
  self.assertEqual(self.conn.execute("SELECT khorshid_stock FROM master_products WHERE id=?",(mid,)).fetchone()[0],5)
  p=create_preview(self.conn,day,"khorshid",xlsx(3))
  commit_preview(self.conn,p["token"])
  self.assertEqual(self.conn.execute("SELECT khorshid_stock FROM master_products WHERE id=?",(mid,)).fetchone()[0],4)

if __name__=="__main__": unittest.main()
