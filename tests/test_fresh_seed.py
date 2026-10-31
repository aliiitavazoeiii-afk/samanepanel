import os
import tempfile
import unittest
from pathlib import Path
from daily_sales_service.engine import init_db

class SisterFreshSeedTest(unittest.TestCase):
    def test_catalog_without_historical_opening_stock(self):
        with tempfile.TemporaryDirectory() as directory:
            before = os.environ.get("SALES_START_EMPTY_STOCK")
            os.environ["SALES_START_EMPTY_STOCK"] = "1"
            try:
                conn = init_db(Path(directory) / "fresh.sqlite3")
                self.assertEqual(conn.execute("SELECT count(*) FROM products").fetchone()[0],538)
                self.assertEqual(tuple(conn.execute("SELECT sum(seller_stock),sum(digikala_stock) FROM products").fetchone()),(0,0))
                conn.close()
            finally:
                if before is None: os.environ.pop("SALES_START_EMPTY_STOCK",None)
                else: os.environ["SALES_START_EMPTY_STOCK"] = before
