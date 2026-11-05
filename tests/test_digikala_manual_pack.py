"""Actual DigiKala pack form: color slots, catalog hiding, and stock-safe linking."""
import tempfile
import unittest
from pathlib import Path

from daily_sales_service.engine import init_db,ImportErrorDetail
from daily_sales_service.catalog_import import apply_catalog
from daily_sales_service.digikala_manual_pack import (
    CATALOG_HIDDEN_VARIANT_IDS,listing_scope,sku_options,manual_link
)
from daily_sales_service.digikala_auto_link import parts_for,apply_links

class ManualPackTest(unittest.TestCase):
 def setUp(self):
    temp=tempfile.TemporaryDirectory()
    self.addCleanup(temp.cleanup)
    self.conn=init_db(Path(temp.name)/"test.sqlite3")
    self.addCleanup(self.conn.close)
    apply_catalog(self.conn,dry_run=False)

 def variant(self,id):
    row=self.conn.execute("SELECT * FROM products WHERE variant_id=?",(id,)).fetchone()
    self.assertIsNotNone(row)
    return row

 def test_hidden_sixteen_records_only_from_catalog_view(self):
    self.assertEqual(len(CATALOG_HIDDEN_VARIANT_IDS),16)
    self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0],538)
    from daily_sales_service.app import app
    from daily_sales_service.master_api import catalog
    page=catalog(conn=self.conn).body.decode()
    self.assertIn("همه · 522",page)
    for code in (50613316,50613319,50614490,50588316,74677012,74677021):
        self.assertNotIn(str(code),page)
        searched=catalog(conn=self.conn,q=str(code)).body.decode()
        self.assertIn("0 ردیف",searched)
        self.assertNotIn(f'href="/daily-sales/catalog?q={code}"',searched)
        self.assertIsNotNone(self.variant(code))
    self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0],538)

 def test_real_dia_four_pack_has_four_slots_for_reversed_range(self):
    row=self.variant(68434424)
    scope=listing_scope(row)
    self.assertEqual(scope["category"],"شورت زنانه دیا")
    self.assertEqual(scope["size"],"M")
    self.assertEqual(scope["pack_qty"],4)
    self.assertEqual(listing_scope(self.variant(68434490))["size"],"L")
    choices=sku_options(self.conn,scope)
    colors={m["color"] for m in choices}
    self.assertTrue({"مشکی","سرمه ای","سفید"}.issubset(colors),colors)
    from daily_sales_service.digikala_manual_ui import build_manual_form
    form=build_manual_form(self.conn,row)
    self.assertEqual(form.count('name="part_id"'),4)
    self.assertIn("عدد 4",form)
    self.assertIn("سرمه ای",form)
    self.assertIn('method="post"',form)

 def test_four_color_slots_link_to_four_stock_components_with_duplicates(self):
    row=self.variant(68434424)
    choice={m["color"]:m["id"] for m in sku_options(self.conn,listing_scope(row))}
    slots=[choice["مشکی"],choice["سرمه ای"],choice["مشکی"],choice["سفید"]]
    before_stock=self.conn.execute(
        "SELECT SUM(seller_stock+khorshid_stock) FROM master_products").fetchone()[0]
    before_price=row["sale_price_toman"]
    result=manual_link(self.conn,68434424,[str(i) for i in slots])
    self.assertEqual(result["pack_qty"],4)
    self.assertEqual(self.conn.execute("SELECT master_id FROM products WHERE variant_id=68434424").fetchone()[0],slots[0])
    positions=[r["master_id"] for r in self.conn.execute(
        "SELECT master_id FROM dk_variant_parts WHERE variant_id=68434424 ORDER BY position")]
    self.assertEqual(positions,slots)
    self.assertEqual(dict(parts_for(self.conn,68434424)),{
        choice["مشکی"]:2,choice["سرمه ای"]:1,choice["سفید"]:1})
    self.assertEqual(self.conn.execute("SELECT sale_price_toman FROM products WHERE variant_id=68434424").fetchone()[0],before_price)
    self.assertEqual(self.conn.execute("SELECT SUM(seller_stock+khorshid_stock) FROM master_products").fetchone()[0],before_stock)
    self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM master_stock_events").fetchone()[0],0)
    self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0],0)
    with self.assertRaises(ImportErrorDetail):
        manual_link(self.conn,68434424,slots)
    with self.assertRaises(ImportErrorDetail):
        manual_link(self.conn,68434490,slots[:2])
    self.assertIsNone(self.variant(68434490)["master_id"])

 def test_wrong_group_or_size_and_hidden_code_rejected(self):
    scope=listing_scope(self.variant(68434424))
    options=sku_options(self.conn,scope)
    valid=options[0]["id"]
    male=self.conn.execute("SELECT id FROM master_products WHERE category='بادیگارد' LIMIT 1").fetchone()[0]
    for bad in ([valid,male,valid,valid],[valid]*3):
        with self.assertRaises(ImportErrorDetail):
            manual_link(self.conn,68434424,bad)
    with self.assertRaises(ImportErrorDetail):
        manual_link(self.conn,50613316,[valid])
    self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM dk_variant_parts").fetchone()[0],0)
    self.assertIsNone(self.variant(68434424)["master_id"])

 def test_male_pack_can_select_real_defined_subtype_for_each_color(self):
    male=self.conn.execute("""SELECT * FROM products
        WHERE title LIKE '%شورت مردانه 671 مجموعه 2 عددی%'
        AND title LIKE '%| 3XL |%' LIMIT 1""").fetchone()
    self.assertIsNotNone(male)
    scope=listing_scope(male)
    self.assertEqual(scope["category"],"بادیگارد")
    self.assertEqual(scope["size"],"3XL")
    self.assertEqual(scope["pack_qty"],2)
    candidates=sku_options(self.conn,scope)
    self.assertTrue(any(m["subtype"]=="اسلیپ" for m in candidates))
    self.assertTrue(any(m["subtype"]=="پادار" for m in candidates))
    chosen=[next(m["id"] for m in candidates if m["subtype"]==typ)
            for typ in ("اسلیپ","پادار")]
    manual_link(self.conn,male["variant_id"],chosen)
    self.assertEqual(sum(n for _,n in parts_for(self.conn,male["variant_id"])),2)

 def test_unavailable_womens_3xl_and_invalid_single_size_have_no_form(self):
    from daily_sales_service.digikala_manual_ui import build_manual_form
    scope=listing_scope(self.variant(67254547))
    self.assertEqual(scope["size"],"3XL")
    self.assertEqual(sku_options(self.conn,scope),[])
    self.assertNotIn('name="part_id"',build_manual_form(self.conn,self.variant(67254547)))
    numeric=self.variant(50613316)
    self.assertIn("error",listing_scope(numeric))

 def test_repeat_auto_link_keeps_manual_provenance(self):
    manual=68434424
    scope=listing_scope(self.variant(manual))
    choice={m["color"]:m["id"] for m in sku_options(self.conn,scope)}
    manual_link(self.conn,manual,[choice["مشکی"]]*4)
    apply_links(self.conn,dry_run=False)
    reason=self.conn.execute("SELECT status FROM dk_auto_match_audit WHERE variant_id=?",(manual,)).fetchone()[0]
    self.assertEqual(reason,"manual_connected")
    self.assertEqual(len(list(self.conn.execute(
        "SELECT master_id FROM dk_variant_parts WHERE variant_id=?",(manual,)))),4)

if __name__=="__main__":unittest.main()
