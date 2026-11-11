"""Strict regression tests for owner-supplied DIA site + Basalam recipes."""
import importlib.util
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from daily_sales_service.engine import init_db, ImportErrorDetail
from daily_sales_service.master_v2_logic import add_model

SCRIPT = Path(__file__).resolve().parents[1] / "deploy/darma-fresh/import_dia_channels_v1.py"
spec = importlib.util.spec_from_file_location("dia_channels_import", SCRIPT)
dia = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dia)


class DiaChannelsImport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / "sales.sqlite3")
        with patch.dict(os.environ, {"SALES_START_EMPTY_STOCK": "1"}):
            self.conn = init_db(self.db)
        self.addCleanup(self.conn.close)
        add_model(self.conn, dia.CATEGORY, dia.MODEL_TITLE, "",
                  "مشکی، سرمه ای، سفید، راه راه مشکی", "M,L,XL,XXL")

    def test_counts_atomic_import_prices_unset_no_inventory_mutation_and_repeat(self):
        # Protect existing costs, stock and historical sales.
        self.conn.execute(
            "UPDATE master_products SET seller_stock=17,khorshid_stock=8,cost_toman=65000 "
            "WHERE category=? AND color='مشکی'", (dia.CATEGORY,))
        before = [tuple(x) for x in self.conn.execute(
            "SELECT id,seller_stock,khorshid_stock,digikala_stock,cost_toman,sale_price_toman "
            "FROM master_products ORDER BY id")]
        plan = dia.preflight(self.conn)
        self.assertEqual(28, len(plan))
        self.assertEqual(80, sum(len(x["sizes"]) for x in plan))
        self.assertEqual(28, sum(x["state"] == "create" for x in plan))
        self.assertEqual((28, 80), dia.apply(self.conn, plan))
        self.assertEqual((0, 0), dia.apply(self.conn, dia.preflight(self.conn)))
        after = [tuple(x) for x in self.conn.execute(
            "SELECT id,seller_stock,khorshid_stock,digikala_stock,cost_toman,sale_price_toman "
            "FROM master_products ORDER BY id")]
        self.assertEqual(before, after)
        self.assertEqual(0, self.conn.execute(
            "SELECT COUNT(*) FROM platform_bundle_variants WHERE price_toman IS NOT NULL").fetchone()[0])
        for channel in dia.CHANNELS:
            self.assertEqual(14, self.conn.execute(
                "SELECT COUNT(*) FROM platform_bundle_models WHERE channel=?", (channel,)).fetchone()[0])
            self.assertEqual(40, self.conn.execute(
                "SELECT COUNT(*) FROM platform_bundle_variants v JOIN platform_bundle_models b "
                "ON b.id=v.bundle_id WHERE b.channel=?", (channel,)).fetchone()[0])
            for code in ("nvy", "nvy-nvy"):
                sizes = {r[0] for r in self.conn.execute(
                    "SELECT v.size FROM platform_bundle_variants v JOIN platform_bundle_models b "
                    "ON b.id=v.bundle_id WHERE b.title=? AND b.channel=?", ("DIA "+code,channel))}
                self.assertEqual({"M","L","XL","XXL"}, sizes)
            for code in ("24", "24-wh", "24-wh-blk", "24-blk"):
                sizes = {r[0] for r in self.conn.execute(
                    "SELECT v.size FROM platform_bundle_variants v JOIN platform_bundle_models b "
                    "ON b.id=v.bundle_id WHERE b.title=? AND b.channel=?", ("DIA "+code,channel))}
                self.assertEqual({"L","XL"}, sizes)
            actual = [r[0] for r in self.conn.execute(
                "SELECT m.color FROM platform_bundle_parts p "
                "JOIN master_products m ON m.id=p.master_id "
                "JOIN platform_bundle_variants v ON v.id=p.variant_id "
                "JOIN platform_bundle_models b ON b.id=v.bundle_id "
                "WHERE b.channel=? AND b.title='DIA blk-nvy 4adadi' AND v.size='L' "
                "ORDER BY p.position", (channel,))]
            self.assertEqual(["مشکی", "مشکی", "سرمه ای", "سرمه ای"], actual)

    def test_upgrade_existing_13_to_14_adds_only_striped_single(self):
        # Simulate a successful previous importer run with the original 13 DIA packs.
        original_recipes = dia.RECIPES
        old_recipes = tuple(item for item in original_recipes if item[0] != "24")
        with patch.object(dia, "RECIPES", old_recipes), patch.object(dia, "EXPECTED_PER_CHANNEL", 38):
            self.assertEqual((26, 76), dia.apply(self.conn, dia.preflight(self.conn)))
        old_rows = [tuple(r) for r in self.conn.execute(
            "SELECT id,bundle_id,size,price_toman FROM platform_bundle_variants ORDER BY id")]
        new_plan = dia.preflight(self.conn)
        self.assertEqual(26, sum(x["state"] == "already_present" for x in new_plan))
        self.assertEqual(2, sum(x["state"] == "create" for x in new_plan))
        self.assertEqual((2, 4), dia.apply(self.conn, new_plan))
        self.assertEqual(old_rows, [tuple(r) for r in self.conn.execute(
            "SELECT id,bundle_id,size,price_toman FROM platform_bundle_variants WHERE id<=? ORDER BY id",
            (old_rows[-1][0],))])
        for channel in dia.CHANNELS:
            rows = [tuple(r) for r in self.conn.execute(
                """SELECT v.size,m.color FROM platform_bundle_variants v
                JOIN platform_bundle_models b ON b.id=v.bundle_id
                JOIN platform_bundle_parts p ON p.variant_id=v.id
                JOIN master_products m ON m.id=p.master_id
                WHERE b.channel=? AND b.title='DIA 24' ORDER BY v.size,p.position""",
                (channel,))]
            self.assertEqual([("L","راه راه مشکی"),("XL","راه راه مشکی")], rows)

    def test_missing_physical_size_aborts_before_any_channel(self):
        self.conn.execute(
            "UPDATE master_products SET active=0 "
            "WHERE category=? AND color='راه راه مشکی' AND size='XL'", (dia.CATEGORY,))
        with self.assertRaises(ImportErrorDetail):
            dia.preflight(self.conn)
        self.assertEqual(0, self.conn.execute("SELECT COUNT(*) FROM platform_bundle_models").fetchone()[0])

    def test_mid_batch_sql_error_rolls_back_all(self):
        self.conn.execute(
            """CREATE TRIGGER dia_block BEFORE INSERT ON platform_bundle_models
               WHEN NEW.title='DIA wh-blk' BEGIN SELECT RAISE(ABORT,'test failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            dia.apply(self.conn, dia.preflight(self.conn))
        self.assertEqual(0, self.conn.execute("SELECT COUNT(*) FROM platform_bundle_models").fetchone()[0])
        self.assertEqual(0, self.conn.execute("SELECT COUNT(*) FROM platform_bundle_variants").fetchone()[0])

    def test_dryrun_readonly_connection(self):
        self.conn.close()
        reader = dia.connect(self.db, readonly=True)
        try:
            self.assertEqual(28, len(dia.preflight(reader)))
            self.assertEqual(0, reader.total_changes)
        finally:
            reader.close()


if __name__ == "__main__":
    unittest.main()
