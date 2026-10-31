"""Golden counts from body.xlsx and non-destructive import safety tests."""
import os
import tempfile
import unittest
from pathlib import Path
from daily_sales_service.engine import init_db
from daily_sales_service.catalog_import import entries, apply_catalog, EXPECTED

class BodyCatalogTest(unittest.TestCase):
 def setUp(self):
  self.folder=tempfile.TemporaryDirectory()
  self.addCleanup(self.folder.cleanup)
  self.db=Path(self.folder.name)/"test.sqlite3"
  self.conn=init_db(self.db)
  self.addCleanup(self.conn.close)

 def test_excel_model_counts_and_size_sets(self):
  items=entries()
  self.assertEqual(len(items),213)
  self.assertEqual(len({(r["category"],r["code"],r["color"],r["size"]) for r in items}),213)
  by_group={}
  for r in items:by_group.setdefault(r["group"],[]).append(r)
  self.assertEqual({k:len(v) for k,v in by_group.items()},EXPECTED)
  self.assertEqual({r["size"] for r in by_group["mens_slip"]},{"L","XL","2XL","3XL"})
  self.assertEqual({r["size"] for r in by_group["mens_padar"]},{"L","XL","2XL","3XL"})
  self.assertEqual({r["size"] for r in by_group["undershirt"]},{"M","L","XL"})
  self.assertEqual({r["size"] for r in by_group["women_dia"]},{"M","L","XL","XXL"})
  self.assertEqual({r["size"] for r in by_group["molds"]},{"کوچک","متوسط","بزرگ"})

 def test_import_dry_run_and_idempotent_with_unmodified_stock_price_cost(self):
  before=self.conn.execute("SELECT COUNT(*) FROM master_products").fetchone()[0]
  dry=apply_catalog(self.conn,dry_run=True)
  self.assertEqual(dry["new"],213)
  self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM master_products").fetchone()[0],before)
  first=apply_catalog(self.conn,dry_run=False)
  self.assertEqual(first["new"],213)
  self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM master_products").fetchone()[0],before+213)
  sample=self.conn.execute("SELECT id FROM master_products WHERE code='BG-SL-01' AND size='L'").fetchone()[0]
  self.conn.execute("UPDATE master_products SET seller_stock=17,digikala_stock=4,sale_price_toman=925000,cost_toman=55000 WHERE id=?",(sample,))
  second=apply_catalog(self.conn,dry_run=False)
  self.assertEqual(second["new"],0)
  self.assertEqual(second["already_present"],213)
  self.assertEqual(tuple(self.conn.execute("SELECT seller_stock,digikala_stock,sale_price_toman,cost_toman FROM master_products WHERE id=?",(sample,)).fetchone()),(17,4,925000,55000))

 def test_all_new_skus_have_zero_stock_and_no_invented_prices(self):
  apply_catalog(self.conn,dry_run=False)
  aggregates=self.conn.execute("SELECT COUNT(*),SUM(seller_stock),SUM(digikala_stock),SUM(sale_price_toman),COUNT(cost_toman) FROM master_products").fetchone()
  self.assertEqual(tuple(aggregates),(213,0,0,0,0))
  self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0],538)

if __name__=='__main__':unittest.main()
