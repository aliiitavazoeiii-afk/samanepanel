"""A read-only preview and reversible audit for historical DigiKala prices."""
import importlib.util
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from daily_sales_service.engine import init_db, fee_unit, settings_for
from daily_sales_service.sister_finance_logic import ensure_finance_schema

SCRIPT = Path(__file__).resolve().parents[1] / "deploy/darma-fresh/reprice_digikala_from_15_aban.py"
spec = importlib.util.spec_from_file_location("dk_historical_reprice", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class HistoricalRepriceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "sales.sqlite3"
        self.conn = init_db(self.path)
        self.addCleanup(self.conn.close)
        ensure_finance_schema(self.conn)
        p = self.conn.execute("SELECT variant_id,category FROM products WHERE active=1 LIMIT 1").fetchone()
        self.vid = int(p["variant_id"])
        self.category = p["category"]
        self.conn.execute("UPDATE products SET sale_price_toman=150000 WHERE variant_id=?", (self.vid,))
        old = fee_unit(100000,self.category,settings_for(self.conn))
        self.old = old
        for day,qty in (("2026-11-05",1),("2026-11-07",2)):
            self.conn.execute("""INSERT INTO sales(sale_date,source,variant_id,qty,price_toman,
              commission_toman,processing_toman,vat_toman,fee_toman,cost_toman)
              VALUES(?,?,?,?,?,?,?,?,?,?)""",
              (day,"seller",self.vid,qty,100000,old["commission"],old["processing"],
               old["vat"],old["fee"],45000))

    def test_preflight_read_only_and_correct_scope(self):
        plan = module.read_plan(self.conn,"2026-11-20")
        self.assertEqual(len(plan["updates"]),1)
        self.assertEqual(plan["updates"][0]["sale_date"],"2026-11-07")
        self.assertEqual(plan["updates"][0]["qty"],2)
        self.assertEqual(plan["updates"][0]["new_price"],150000)
        self.assertEqual(plan["fallback"],[])
        self.assertEqual(plan["missing"],[])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM master_stock_events").fetchone()[0],0)
        self.assertEqual(self.conn.execute("SELECT price_toman FROM sales WHERE sale_date='2026-11-07'").fetchone()[0],100000)

    def test_apply_preserves_stock_quantity_cost_and_earlier_sales(self):
        plan = module.read_plan(self.conn,"2026-11-20")
        stock_events_before = self.conn.execute("SELECT COUNT(*) FROM master_stock_events").fetchone()[0]
        with patch.object(module,"backup_database",return_value="verified-test-backup"):
            module.apply(self.conn,plan["digest"],"2026-11-20","/data/test-backup.sqlite3")
        old = self.conn.execute("SELECT * FROM sales WHERE sale_date='2026-11-05'").fetchone()
        new = self.conn.execute("SELECT * FROM sales WHERE sale_date='2026-11-07'").fetchone()
        self.assertEqual(old["price_toman"],100000)
        self.assertEqual(new["price_toman"],150000)
        self.assertEqual(new["cost_toman"],45000)
        self.assertEqual(new["qty"],2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM master_stock_events").fetchone()[0],stock_events_before)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM dk_sales_repricing_audit").fetchone()[0],1)
        self.assertEqual(self.conn.execute("SELECT price_toman FROM dk_dated_sale_prices WHERE variant_id=? AND effective_date=?",(self.vid,module.START)).fetchone()[0],150000)
        again=module.read_plan(self.conn,"2026-11-20")
        self.assertFalse(again["updates"])

    def test_rejects_stale_preview_without_changes(self):
        plan = module.read_plan(self.conn,"2026-11-20")
        self.conn.execute("UPDATE sales SET qty=3 WHERE sale_date='2026-11-07'")
        with self.assertRaisesRegex(RuntimeError,"پیش‌نمایش"):
            module.apply(self.conn,plan["digest"],"2026-11-20","/data/test-backup.sqlite3")
        self.assertEqual(self.conn.execute("SELECT price_toman FROM sales WHERE sale_date='2026-11-07'").fetchone()[0],100000)

    def test_rejects_fallback_catalog_price(self):
        self.conn.execute("UPDATE products SET sale_price_toman=NULL WHERE variant_id=?",(self.vid,))
        plan = module.read_plan(self.conn,"2026-11-20")
        self.assertFalse(plan["updates"])
        self.assertTrue(plan["fallback"])
        with self.assertRaisesRegex(RuntimeError,"پیش‌فرض"):
            module.apply(self.conn,plan["digest"],"2026-11-20","/data/test-backup.sqlite3")


if __name__=="__main__":
    unittest.main()
