"""Regression: the owner's ordinary seven-column DigiKala daily XLSX has NO price column.

The registered per-variant/catalog prices must be used for a whole listing/pack.
Every preview is read-only; confirmation posts exact physical stock and frozen fees.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_engine import make_xlsx
from daily_sales_service.engine import init_db, create_preview, commit_preview, fee_unit, settings_for
from daily_sales_service.dk_catalog_preferences import update_display
from daily_sales_service.master_v2_logic import add_model, batch_adjust, sku_rows
from daily_sales_service.effective_costs import schedule_cost, today
from daily_sales_service.digikala_daily_ui import preview_page
from daily_sales_service.digikala_manual_pack import listing_scope, sku_options, manual_link
from daily_sales_service.digikala_auto_link import parts_for

HEADER=["کد تنوع","کد فروشنده","عنوان","تعداد پیشنهادی",
        "تعداد ارسالی","تعداد مغایرت","وضعیت"]

class StandardDigiKalaDailyImport(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        ctx=patch.dict(os.environ,{"SALES_MASTER_STRICT":"1","SALES_START_EMPTY_STOCK":"1"})
        ctx.start()
        self.addCleanup(ctx.stop)
        self.conn=init_db(Path(temp.name)/"test.sqlite3")
        self.addCleanup(self.conn.close)
        self.vid=67312039
        original=self.conn.execute("SELECT * FROM products WHERE variant_id=?",(self.vid,)).fetchone()
        self.assertIsNotNone(original,"The catalog seed must contain this public DigiKala variant")
        add_model(self.conn,"شورت زنانه دیا","DIA test unit","","مشکی","L")
        sku=sku_rows(self.conn,"شورت زنانه دیا")[0]
        self.master_id=int(sku["id"])
        batch_adjust(self.conn,"شورت زنانه دیا",self.master_id,"L","home",
                     {self.master_id:12},"test initial stock")
        schedule_cost(self.conn,"شورت زنانه دیا","","*",50000,today())
        # Exact two-component physical pack (the market variant has its own whole-pack price).
        self.conn.execute("UPDATE products SET master_id=?,sale_price_toman=0,"
                          "list_price_rial=4400000,promotion_price_rial=3700000 "
                          "WHERE variant_id=?",(self.master_id,self.vid))
        self.conn.execute("INSERT INTO dk_variant_parts(variant_id,position,master_id) VALUES(?,?,?)",
                          (self.vid,1,self.master_id))
        self.conn.execute("INSERT INTO dk_variant_parts(variant_id,position,master_id) VALUES(?,?,?)",
                          (self.vid,2,self.master_id))

    def report(self,qty=2):
        row=self.conn.execute("SELECT title FROM products WHERE variant_id=?",(self.vid,)).fetchone()
        sheet=[HEADER,[self.vid,"",row["title"],0,qty,0,"اماده ارسال/تحویل"]]
        return [("packageDeliveryReport.xlsx",make_xlsx(sheet))]

    def test_no_price_column_uses_saved_catalog_price_for_whole_pack(self):
        row=self.conn.execute("SELECT title FROM products WHERE variant_id=?",(self.vid,)).fetchone()
        update_display(self.conn,self.vid,row["title"],555000)
        before=self.conn.execute("SELECT seller_stock FROM master_products WHERE id=?",
                                 (self.master_id,)).fetchone()[0]
        preview=create_preview(self.conn,today(),"seller",self.report())
        self.assertFalse(preview["errors"],preview["errors"])
        self.assertEqual(preview["rows"][0]["price"],555000)
        self.assertEqual(preview["rows"][0]["price_source"],"قیمت ثبت‌شده در کاتالوگ دیجی‌کالا")
        self.assertEqual(preview["rows"][0]["cost"],100000)
        self.assertEqual(preview["fallback_prices"],1)
        self.assertEqual(preview["rows"][0]["fee"],
                         fee_unit(555000,"شورت زنانه",settings_for(self.conn))["fee"])
        self.assertEqual(self.conn.execute(
            "SELECT seller_stock FROM master_products WHERE id=?",(self.master_id,)
        ).fetchone()[0],before)
        html=preview_page(preview).body.decode("utf-8")
        self.assertIn("قیمت فروش",html)
        self.assertNotIn("<th>مبنای قیمت</th>",html)
        commit_preview(self.conn,preview["token"])
        self.assertEqual(self.conn.execute(
            "SELECT seller_stock FROM master_products WHERE id=?",(self.master_id,)
        ).fetchone()[0],before-4)
        saved=self.conn.execute("SELECT price_toman,qty,fee_toman,cost_toman FROM sales "
                                "WHERE variant_id=?",(self.vid,)).fetchone()
        self.assertEqual((saved["price_toman"],saved["qty"],saved["cost_toman"]),
                         (555000,2,100000))
        second=create_preview(self.conn,today(),"seller",self.report())
        self.assertFalse(second["errors"],second["errors"])
        commit_preview(self.conn,second["token"])
        self.assertEqual(self.conn.execute(
            "SELECT seller_stock FROM master_products WHERE id=?",(self.master_id,)
        ).fetchone()[0],before-4)

    def test_explicit_variant_price_precedes_imported_catalog_without_edit(self):
        self.conn.execute("UPDATE products SET sale_price_toman=520000 WHERE variant_id=?",
                          (self.vid,))
        p=create_preview(self.conn,today(),"seller",self.report(1))
        self.assertFalse(p["errors"],p["errors"])
        self.assertEqual(p["rows"][0]["price"],520000)
        self.assertEqual(p["rows"][0]["price_source"],"قیمت فروش اختصاصی کد تنوع")

    def test_imported_catalog_promotion_is_last_resort_not_master_unit_price(self):
        self.conn.execute("UPDATE master_products SET sale_price_toman=180000 WHERE id=?",
                          (self.master_id,))
        p=create_preview(self.conn,today(),"seller",self.report(1))
        self.assertFalse(p["errors"],p["errors"])
        self.assertEqual(p["rows"][0]["price"],370000)
        self.assertEqual(p["rows"][0]["price_source"],"قیمت تخفیفی فهرست دیجی‌کالا")

    def test_no_real_price_still_blocks_atomic_sale(self):
        self.conn.execute("UPDATE products SET list_price_rial=0,promotion_price_rial=0,"
                          "sale_price_toman=0 WHERE variant_id=?",(self.vid,))
        p=create_preview(self.conn,today(),"seller",self.report())
        self.assertTrue(p["errors"])
        self.assertIn("قیمت فروش معتبر",p["errors"][0])
        self.assertIsNone(self.conn.execute("SELECT 1 FROM sales WHERE variant_id=?",
                        (self.vid,)).fetchone())
        self.assertEqual(self.conn.execute("SELECT seller_stock FROM master_products "
                         "WHERE id=?",(self.master_id,)).fetchone()[0],12)

    def test_real_mold_two_pack_requires_explicit_sizes_not_guessed(self):
        mold=self.conn.execute("SELECT * FROM products WHERE variant_id=75666433").fetchone()
        self.assertIsNotNone(mold)
        scope=listing_scope(mold)
        self.assertEqual((scope["category"],scope["size"],scope["pack_qty"]),
                         ("قالب","*",2))
        add_model(self.conn,"قالب","قالب آزمایشی","","سفید","کوچک,متوسط")
        choices=sku_options(self.conn,scope)
        sizes={choice["size"] for choice in choices}
        self.assertTrue({"کوچک","متوسط"}.issubset(sizes))
        ids=[next(r["id"] for r in choices if r["size"]==size)
             for size in ("کوچک","متوسط")]
        stock_before=self.conn.execute(
            "SELECT SUM(seller_stock+khorshid_stock) FROM master_products").fetchone()[0]
        manual_link(self.conn,75666433,ids)
        self.assertEqual(sum(q for _,q in parts_for(self.conn,75666433)),2)
        self.assertEqual(self.conn.execute(
            "SELECT SUM(seller_stock+khorshid_stock) FROM master_products").fetchone()[0],
            stock_before)

if __name__=="__main__":
    unittest.main()
