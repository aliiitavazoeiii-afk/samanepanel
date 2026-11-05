"""Audit 538 genuine DigiKala titles and verify safety of physical SKU mappings."""
import tempfile
import unittest
from pathlib import Path

from daily_sales_service.engine import init_db,create_preview,commit_preview
from daily_sales_service.catalog_import import apply_catalog
from daily_sales_service.master_v2_logic import sku_rows,batch_adjust
from daily_sales_service.digikala_auto_link import apply_links,scan,parts_for,proposed_match
from daily_sales_service.effective_costs import today,schedule_cost
from test_engine import make_xlsx

class DigiKalaAutoLinkTest(unittest.TestCase):
 def setUp(self):
    folder=tempfile.TemporaryDirectory()
    self.addCleanup(folder.cleanup)
    self.conn=init_db(Path(folder.name)/"dk.sqlite3")
    self.addCleanup(self.conn.close)
    self.assertEqual(apply_catalog(self.conn,dry_run=False)["expected"],213)

 def test_all_538_are_scanned_and_known_undershirts_link(self):
    result=scan(self.conn)
    self.assertEqual(result["scanned"],538)
    self.assertEqual(sum(result["summary"].values()),538)
    undershirts=[dict(v) for v in self.conn.execute("SELECT * FROM products WHERE category='زیرپوش مردانه'")]
    self.assertEqual(len(undershirts),9)
    matched={x["variant_id"]:x for x in result["items"]}
    for variant in undershirts:
        self.assertEqual(matched[variant["variant_id"]]["status"],"matched",variant["title"])
        self.assertEqual(len(matched[variant["variant_id"]]["parts"]),1)
    self.assertGreater(result["summary"].get("matched",0),100)
    self.assertGreater(result["summary"].get("unknown",0)+result["summary"].get("ambiguous",0),0)
    print("DK_538_AUDIT_BASELINE",result["summary"])
    from collections import defaultdict,Counter
    all_variants={v["variant_id"]:dict(v) for v in self.conn.execute("SELECT * FROM products")}
    summaries=defaultdict(Counter)
    examples=defaultdict(list)
    for item in result["items"]:
        origin=all_variants[item["variant_id"]]
        summaries[origin["category"]][item["status"]]+=1
        key=item["reason"] if item["status"]!="matched" else "MATCHED"
        if len(examples[key])<3:
            examples[key].append(origin["title"][:120])
    print("DK_538_AUDIT_BY_GROUP",dict(summaries))
    for reason,rows in sorted(examples.items(),key=lambda x:-sum(
       1 for z in result["items"] if z["reason"]==x[0]))[:25]:
       count=sum(1 for z in result["items"] if z["reason"]==reason)
       print("DK_AUDIT_REASON",count,reason,rows)

 def test_single_numeric_size_is_not_guessed_and_unknown_colors_left_alone(self):
    samples=[dict(x) for x in self.conn.execute(
        "SELECT * FROM products WHERE title LIKE '%دارما%' AND title LIKE '%| 38 |%'")]
    self.assertTrue(samples)
    masters=[dict(x) for x in self.conn.execute("SELECT * FROM master_products")]
    for variant in samples:
        self.assertEqual(proposed_match(variant,masters)["status"],"unknown")
    mold=dict(self.conn.execute("SELECT * FROM products WHERE category='مراقبت کفش و لوازم جانبی' LIMIT 1").fetchone())
    self.assertEqual(proposed_match(mold,masters)["status"],"unknown")

 def test_dia_two_pack_color_slots_and_idempotent_apply(self):
    target=dict(self.conn.execute("""SELECT * FROM products
        WHERE title LIKE '%دیا%' AND title LIKE '%مجموعه 2 عددی%'
          AND title LIKE '%سرمه ای%' LIMIT 1""").fetchone())
    masters=[dict(x) for x in self.conn.execute("SELECT * FROM master_products")]
    p=proposed_match(target,masters)
    self.assertEqual(p["status"],"matched",p)
    self.assertEqual(len(p["parts"]),2)
    before=self.conn.execute("SELECT COUNT(*) FROM dk_variant_parts").fetchone()[0]
    preview=apply_links(self.conn,dry_run=True)
    self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM dk_variant_parts").fetchone()[0],before)
    first=apply_links(self.conn,dry_run=False)
    self.assertGreater(first["summary"].get("matched",0),100)
    actual=parts_for(self.conn,target["variant_id"])
    self.assertEqual(sum(n for _,n in actual),2)
    second=apply_links(self.conn,dry_run=False)
    self.assertEqual(second["summary"].get("matched",0),0)
    self.assertEqual(second["summary"].get("auto_connected",0),first["summary"]["matched"])
    self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM dk_variant_parts").fetchone()[0],
                     sum(len(x["parts"]) for x in first["items"] if x["status"]=="matched"))
    self.assertIsNone(self.conn.execute("SELECT cost_toman FROM sales LIMIT 1").fetchone())

 def test_real_digikala_two_pack_deducts_two_and_idempotent_import(self):
    apply_links(self.conn,dry_run=False)
    item=self.conn.execute("""SELECT p.variant_id,p.master_id FROM products p
      WHERE p.title LIKE '%دیا%' AND p.title LIKE '%مجموعه 2 عددی%'
       AND p.title LIKE '%سرمه ای%' AND p.master_id IS NOT NULL LIMIT 1""").fetchone()
    self.assertIsNotNone(item)
    mid=item["master_id"]
    sku=dict(self.conn.execute("SELECT * FROM master_products WHERE id=?",(mid,)).fetchone())
    batch_adjust(self.conn,sku["category"],mid,sku["size"],"home",{mid:9},"شمارش تست")
    schedule_cost(self.conn,sku["category"],"","*",50000,today())
    doc=lambda count:make_xlsx([["کد تنوع","تعداد ارسالی","قیمت فروش (تومان)"],
                                 [item["variant_id"],count,300000]])
    first=create_preview(self.conn,today(),"seller",[("orders.xlsx",doc(2))])
    self.assertFalse(first["errors"],first.get("errors"))
    self.assertEqual(first["rows"][0]["cost"],100000)
    self.assertEqual(first["stock_changes"][0]["delta"],-4)
    commit_preview(self.conn,first["token"])
    self.assertEqual(self.conn.execute("SELECT seller_stock FROM master_products WHERE id=?",(mid,)).fetchone()[0],5)
    repeated=create_preview(self.conn,today(),"seller",[("orders.xlsx",doc(2))])
    self.assertFalse(repeated["errors"])
    commit_preview(self.conn,repeated["token"])
    self.assertEqual(self.conn.execute("SELECT seller_stock FROM master_products WHERE id=?",(mid,)).fetchone()[0],5)

 def test_catalog_page_shows_matched_parts_and_unmapped_reasons(self):
    from daily_sales_service.app import app  # Load FastAPI router before importing legacy helper directly.
    from daily_sales_service.master_api import catalog
    before=catalog(conn=self.conn).body.decode()
    self.assertIn("همگام‌سازی هوشمند",before)
    apply_links(self.conn,dry_run=False)
    after=catalog(conn=self.conn).body.decode()
    self.assertIn("اتصال خودکار",after)
    self.assertIn("ترکیب اتصال به موجودی واقعی",after)
    self.assertIn("بدون اتصال",catalog(conn=self.conn,unmapped=1).body.decode())
    # Regression: the default page previously sorted every unlinked item
    # to the top, making 321 successfully mapped variants LOOK unmapped.
    table_start=after.index("فهرست کدهای دیجی‌کالا")
    self.assertIn("خودکار",after[table_start:])
    self.assertNotIn('<span style="color:#ffa460">بدون اتصال</span>',
                     after[table_start:].split("</table>",1)[0])
    connected=catalog(conn=self.conn,status="connected").body.decode()
    self.assertIn("فقط متصل",connected)
    self.assertIn("خودکار",connected[connected.index("فهرست کدهای دیجی‌کالا"):])
    unlinked=catalog(conn=self.conn,status="unmapped").body.decode()
    self.assertIn("فقط بدون اتصال",unlinked)
    self.assertIn('<span style="color:#ffa460">بدون اتصال</span>',unlinked)
    self.assertNotIn("خودکار</strong>",unlinked)
    # Existing bookmarked ?unmapped=1 filters still work.
    self.assertIn("فقط بدون اتصال",catalog(conn=self.conn,unmapped=1).body.decode())

 def test_specific_darma_range_and_boy_bodyguard_xxl_and_ambiguous_gray(self):
    masters=[dict(x) for x in self.conn.execute("SELECT * FROM master_products")]
    matched=lambda like:[dict(x) for x in self.conn.execute(
      "SELECT * FROM products WHERE title LIKE ? LIMIT 100",("%"+like+"%",))]
    darma=[x for x in matched("شورت زنانه دارما مدل 664")
           if "| 40-42 |" in x["title"] and "سرمه" in x["title"]]
    self.assertTrue(darma)
    self.assertEqual(proposed_match(darma[0],masters)["status"],"matched")
    body=[x for x in matched("شورت اسلیپ مردانه کد") if "| XXL |" in x["title"]
          and "مشکی" in x["title"]]
    self.assertTrue(body)
    res=proposed_match(body[0],masters)
    self.assertEqual(res["status"],"matched",res)
    self.assertEqual(res["size"],"2XL")
    gray=[x for x in matched("شورت پادار مردانه مدل") if "| طوسی |" in x["title"]]
    self.assertTrue(gray)
    self.assertNotEqual(proposed_match(gray[0],masters)["status"],"matched")

 def test_manual_links_and_sale_history_are_unchanged(self):
    first=self.conn.execute("SELECT variant_id FROM products ORDER BY variant_id LIMIT 1").fetchone()[0]
    sku=self.conn.execute("SELECT id FROM master_products LIMIT 1").fetchone()[0]
    self.conn.execute("UPDATE products SET master_id=? WHERE variant_id=?",(sku,first))
    plan=apply_links(self.conn,dry_run=False)
    self.assertEqual(self.conn.execute("SELECT master_id FROM products WHERE variant_id=?",(first,)).fetchone()[0],sku)
    self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM dk_variant_parts WHERE variant_id=?",(first,)).fetchone()[0],0)
    self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0],0)
    self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM master_stock_events").fetchone()[0],0)

if __name__=="__main__":unittest.main()
