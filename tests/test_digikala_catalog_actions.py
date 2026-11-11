"""DigiKala catalog CRUD-in-view: history-safe, reversible, per-code tests."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from daily_sales_service.engine import init_db, report, ImportErrorDetail
from daily_sales_service.dk_catalog_preferences import (
    update_display, set_archived, is_archived, catalog_redirect,
)
from daily_sales_service.digikala_manual_pack import CATALOG_HIDDEN_VARIANT_IDS, manual_link
from daily_sales_service.digikala_auto_link import scan
from daily_sales_service.app import app  # Ensure active router finishes loading before legacy module.
from daily_sales_service.master_api import catalog
from daily_sales_service.master_v2_api import router

class CatalogActionsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        with patch.dict(os.environ, {"SALES_START_EMPTY_STOCK": "1"}):
            self.conn = init_db(str(Path(temp.name)/"sales.sqlite3"))
        self.addCleanup(self.conn.close)
        self.vid=int(next(r[0] for r in self.conn.execute(
            "SELECT variant_id FROM products ORDER BY variant_id")
            if int(r[0]) not in CATALOG_HIDDEN_VARIANT_IDS))
        self.orig=dict(self.conn.execute(
            "SELECT * FROM products WHERE variant_id=?", (self.vid,)).fetchone())

    def test_page_has_each_row_edit_and_remove_and_removed_tab(self):
        html=catalog(q=str(self.vid),status="all",conn=self.conn).body.decode()
        self.assertIn("/daily-sales/catalog/edit",html)
        self.assertIn("/daily-sales/catalog/archive",html)
        self.assertIn("حذف‌شده‌ها",html)
        self.assertIn(f'name="variant_id" value="{self.vid}"',html)

    def test_edit_changes_only_display_metadata_not_original_product_or_sales(self):
        update_display(self.conn,self.vid,"عنوان اصلاحی دیا",125000)
        assert self.orig==dict(self.conn.execute(
            "SELECT * FROM products WHERE variant_id=?", (self.vid,)).fetchone())
        html=catalog(q=str(self.vid),conn=self.conn).body.decode()
        self.assertIn("عنوان اصلاحی دیا",html)
        self.assertIn("125,000",html)
        self.assertIn("حذف",html)
        pref=self.conn.execute("SELECT * FROM dk_catalog_preferences WHERE variant_id=?", (self.vid,)).fetchone()
        self.assertEqual(125000,pref["display_price_toman"])

    def test_remove_frees_active_list_retains_sale_and_restores(self):
        self.conn.execute("""INSERT INTO sales(
            sale_date,source,variant_id,qty,price_toman,commission_toman,
            processing_toman,vat_toman,fee_toman,cost_toman)
            VALUES('2026-11-05','digikala',?,1,200000,5000,2000,700,7700,80000)""",
            (self.vid,))
        original_report=report(self.conn)["gross"]
        original_inventory=self.conn.execute(
            "SELECT SUM(seller_stock),SUM(khorshid_stock) FROM master_products").fetchone()
        set_archived(self.conn,self.vid,True)
        self.assertTrue(is_archived(self.conn,self.vid))
        self.assertNotIn(f'name="variant_id" value="{self.vid}"',
                         catalog(q=str(self.vid),status="all",conn=self.conn).body.decode())
        self.assertIn(f'name="variant_id" value="{self.vid}"',
                      catalog(q=str(self.vid),status="removed",conn=self.conn).body.decode())
        self.assertEqual(original_report,report(self.conn)["gross"])
        self.assertEqual(1,self.conn.execute(
            "SELECT COUNT(*) FROM sales WHERE variant_id=?", (self.vid,)).fetchone()[0])
        self.assertEqual(tuple(original_inventory),tuple(self.conn.execute(
            "SELECT SUM(seller_stock),SUM(khorshid_stock) FROM master_products").fetchone()))
        self.assertEqual(self.orig,dict(self.conn.execute(
            "SELECT * FROM products WHERE variant_id=?", (self.vid,)).fetchone()))
        self.assertIn("بازیابی محصول",catalog(q=str(self.vid),status="removed",conn=self.conn).body.decode())
        set_archived(self.conn,self.vid,False)
        self.assertFalse(is_archived(self.conn,self.vid))
        self.assertIn(f'name="variant_id" value="{self.vid}"',
                      catalog(q=str(self.vid),status="all",conn=self.conn).body.decode())

    def test_removed_variant_will_not_be_auto_relinked_or_manually_linked(self):
        set_archived(self.conn,self.vid,True)
        plan=scan(self.conn)
        item=next(x for x in plan["items"] if x["variant_id"]==self.vid)
        self.assertEqual("removed",item["status"])
        with self.assertRaisesRegex(ImportErrorDetail,"بازیابی"):
            manual_link(self.conn,self.vid,[1])

    def test_invalid_edits_and_missing_code_protected(self):
        for value in ("", "x"*221):
            with self.assertRaises(ImportErrorDetail):
                update_display(self.conn,self.vid,value,"")
        with self.assertRaises(ImportErrorDetail):
            update_display(self.conn,self.vid,"okay","0")
        with self.assertRaises(ImportErrorDetail):
            set_archived(self.conn,-999,True)
        self.assertFalse(self.conn.execute(
            "SELECT 1 FROM dk_catalog_preferences WHERE variant_id=?", (self.vid,)).fetchone())

    def test_routes_and_safe_return_url(self):
        paths={x.path for x in router.routes if hasattr(x,'path')}
        for path in ("/daily-sales/catalog/edit","/daily-sales/catalog/archive","/daily-sales/catalog/restore"):
            self.assertIn(path,paths)
        link=catalog_redirect("unmapped","&external=https://fake.invalid",200000)
        self.assertTrue(link.startswith("/daily-sales/catalog?"))
        self.assertNotIn("https://",link)
        self.assertIn("page_no=10000",link)


if __name__=="__main__":
    unittest.main()
