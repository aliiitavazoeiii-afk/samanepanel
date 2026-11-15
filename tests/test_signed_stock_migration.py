"""Preserve a populated older sister SQLite while allowing verified sales deficits."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from daily_sales_service.engine import init_db,create_preview,commit_preview
from daily_sales_service.master_v2_logic import add_model,sku_rows
from daily_sales_service.signed_stock_migration import ensure_signed_master_stock
from test_engine import make_xlsx


class SignedStockMigrationTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path=Path(folder.name)/"legacy.sqlite3"
        old=sqlite3.connect(self.path,isolation_level=None)
        old.executescript("""
          PRAGMA foreign_keys=ON;
          CREATE TABLE master_products (
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             category TEXT NOT NULL,code TEXT NOT NULL,title TEXT NOT NULL,
             size TEXT NOT NULL DEFAULT '-',color TEXT NOT NULL DEFAULT '-',
             sale_price_toman INTEGER NOT NULL DEFAULT 0 CHECK(sale_price_toman>=0),
             cost_toman INTEGER CHECK(cost_toman>=0),
             seller_stock INTEGER NOT NULL DEFAULT 0 CHECK(seller_stock>=0),
             digikala_stock INTEGER NOT NULL DEFAULT 0 CHECK(digikala_stock>=0),
             active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,
             updated_at TEXT NOT NULL,subtype TEXT NOT NULL DEFAULT '',
             khorshid_stock INTEGER NOT NULL DEFAULT 0 CHECK(khorshid_stock>=0),
             UNIQUE(category,code,size,color)
          );
          CREATE INDEX idx_master_category ON master_products(category);
          CREATE TABLE master_stock_events (
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             occurred_at TEXT NOT NULL,
             master_id INTEGER NOT NULL REFERENCES master_products(id),
             source TEXT NOT NULL,delta INTEGER NOT NULL,
             balance_after INTEGER NOT NULL,reference TEXT NOT NULL
          );
          CREATE TABLE existing_foreign_child (
             ref INTEGER PRIMARY KEY,
             master_id INTEGER NOT NULL REFERENCES master_products(id)
          );
        """)
        old.execute("""INSERT INTO master_products(id,category,code,title,size,color,
              sale_price_toman,cost_toman,seller_stock,digikala_stock,khorshid_stock,
              active,created_at,updated_at,subtype)
              VALUES (42,'بادیگارد','BG-SL-02','شورت تست','2XL','سبز',0,55000,
                      0,3,2,1,'old','old','اسلیپ')""")
        old.execute("""INSERT INTO master_stock_events(occurred_at,master_id,source,
                  delta,balance_after,reference) VALUES ('old',42,'home',0,0,'old-event')""")
        old.execute("INSERT INTO existing_foreign_child(ref,master_id) VALUES (5,42)")
        old.execute("UPDATE sqlite_sequence SET seq=100 WHERE name='master_products'")
        old.close()

    def test_legacy_rebuild_is_atomic_preserves_related_data_and_auto_increment(self):
        db=init_db(self.path)
        self.addCleanup(db.close)
        self.assertFalse(ensure_signed_master_stock(db))  # exactly once
        db.execute("""UPDATE master_products SET seller_stock=-3,khorshid_stock=-1,
                   digikala_stock=-4 WHERE id=42""")
        master=db.execute("SELECT * FROM master_products WHERE id=42").fetchone()
        self.assertEqual((master["seller_stock"],master["khorshid_stock"],
                          master["digikala_stock"]),(-3,-1,-4))
        self.assertEqual(master["subtype"],"اسلیپ")
        self.assertEqual(master["cost_toman"],55000)
        self.assertEqual(db.execute("SELECT master_id FROM existing_foreign_child WHERE ref=5").fetchone()[0],42)
        self.assertEqual(db.execute("SELECT master_id FROM master_stock_events WHERE reference='old-event'").fetchone()[0],42)
        self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(),[])
        self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()[0],1)
        self.assertTrue(db.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_master_category'").fetchone())
        self.assertGreater(db.execute("""INSERT INTO master_products(category,code,title,size,color,
                       sale_price_toman,created_at,updated_at)
                       VALUES('قالب','NEW-M','test','کوچک','سفید',0,'new','new')
                       RETURNING id""").fetchone()[0],100)
        db.close()
        reopened=init_db(self.path)
        self.assertEqual(reopened.execute("SELECT seller_stock FROM master_products WHERE id=42").fetchone()[0],-3)
        reopened.close()

    def test_sale_at_zero_goes_negative_and_reupload_is_idempotent(self):
        db=init_db(self.path)
        self.addCleanup(db.close)
        code=db.execute("SELECT variant_id FROM products WHERE active=1 LIMIT 1").fetchone()[0]
        db.execute("UPDATE products SET master_id=?,sale_price_toman=400000 WHERE variant_id=?",(42,code))
        doc=[("today.xlsx",make_xlsx([["کد تنوع","تعداد ارسالی"],[code,3]]))]
        for _ in range(2):
            p=create_preview(db,"2026-11-15","seller",doc)
            self.assertFalse(p["errors"],p["errors"])
            self.assertEqual(p["stock_changes"][0]["stock_after"],-3)
            commit_preview(db,p["token"])
            self.assertEqual(db.execute("SELECT seller_stock FROM master_products WHERE id=42").fetchone()[0],-3)
        self.assertEqual(db.execute("SELECT qty FROM sales WHERE variant_id=?",(code,)).fetchone()[0],3)
        self.assertEqual(db.execute("SELECT COUNT(*) FROM master_stock_events WHERE reference LIKE 'digikala:%'").fetchone()[0],1)


if __name__=="__main__":
    unittest.main()
