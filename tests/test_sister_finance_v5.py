"""Sister finance: Basalam 15%, platform claims, bank flows and profit safety."""
import tempfile
import unittest
from pathlib import Path

from daily_sales_service.engine import init_db,ImportErrorDetail
from daily_sales_service.master_v2_logic import add_model,batch_adjust,sku_rows,set_channel_prices
from daily_sales_service.platform_packs_v4 import available_models,define_bundle,list_bundle_variants,save_variant_prices,book_bundle_sale
from daily_sales_service.platform_catalog import create_listing,book_sale
from daily_sales_service.effective_costs import schedule_cost,today
from daily_sales_service.sister_finance_logic import (
    ensure_finance_schema, commission_for,sale_lines,sales_report,platform_balances,
    add_account,add_party,register_movement,cancel_movement,accounts,parties,movements,overview
)

class SisterFinanceTest(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.conn=init_db(Path(self.folder.name)/"finance.sqlite3")
        self.addCleanup(self.conn.close)
        add_model(self.conn,"شورت زنانه دارما","مدل ساده","","مشکی،سفید","M،L")
        self.sku=sku_rows(self.conn,"شورت زنانه دارما")[0]
        self.color_skus={(s["size"],s["color"]):s for s in sku_rows(self.conn,"شورت زنانه دارما")}
        for s in sku_rows(self.conn,"شورت زنانه دارما"):
            batch_adjust(self.conn,s["category"],s["id"],s["size"],"home",
                         {s["id"]:40},"شمارش افتتاحیه")
        schedule_cost(self.conn,"شورت زنانه دارما","","*",80000,today())

    def sale(self,channel="basalam",price=500000,qty=1,colors=("مشکی",),size="M"):
        key=available_models(self.conn,"شورت زنانه دارما")[0]["key"]
        define_bundle(self.conn,channel,"شورت زنانه دارما",key,len(colors),list(colors),[size],"پک تست")
        variant=list_bundle_variants(self.conn,channel)[-1]["variant_id"]
        save_variant_prices(self.conn,channel,{variant:price})
        return book_bundle_sale(self.conn,channel,variant,qty,"home",today(),f"{channel}-{price}-{qty}")

    def test_basalam_is_exact_15_percent_of_gross_and_appears_as_debt(self):
        self.assertEqual(commission_for("basalam",500000),75000)
        sale=self.sale()
        self.assertEqual(sale["gross"],500000)
        self.assertEqual(sale["fees"],75000)
        self.assertEqual(sale["receivable"],425000)
        self.assertEqual(sale["cogs"],80000)
        self.assertEqual(sale["profit"],345000)
        self.assertEqual(self.conn.execute("SELECT commission_toman FROM platform_bundle_sales").fetchone()[0],75000)
        claim=platform_balances(self.conn)["basalam"]
        self.assertEqual(claim["outstanding"],425000)
        stats=sales_report(self.conn,"basalam")
        self.assertEqual((stats["gross"],stats["fees"],stats["cogs_known"],stats["net"],stats["profit"]),
                         (500000,75000,80000,425000,345000))
        self.assertEqual(sales_report(self.conn)["net"],425000)

    def test_actual_discounted_order_price_controls_commission_not_catalog_price(self):
        self.sale(price=500000)
        vid=list_bundle_variants(self.conn,"basalam")[0]["variant_id"]
        out=book_bundle_sale(self.conn,"basalam",vid,1,"home",today(),"discount-2",actual_price="400000")
        self.assertEqual((out["gross"],out["fees"],out["receivable"],out["profit"]),
                         (400000,60000,340000,260000))
        self.assertEqual(platform_balances(self.conn)["basalam"]["outstanding"],765000)
        self.assertEqual(sales_report(self.conn,"basalam")["fees"],135000)
        self.assertEqual(self.conn.execute("SELECT price_per_pack FROM platform_bundle_sales ORDER BY id DESC LIMIT 1").fetchone()[0],400000)

    def test_multicolor_sale_uses_total_pack_price_not_per_piece_fee(self):
        sale=self.sale(qty=2,price=530000,colors=("مشکی","سفید","مشکی"))
        self.assertEqual((sale["gross"],sale["fees"],sale["receivable"]), (1060000,159000,901000))
        self.assertEqual(sale["cogs"],480000)
        self.assertEqual(sale["profit"],421000)
        self.assertEqual(sales_report(self.conn,"basalam")["units"],6)

    def test_receipt_reduces_receivable_and_increases_bank_without_revenue(self):
        self.sale()
        bank=add_account(self.conn,"ملت","1000000")
        basalam=next(x for x in parties(self.conn) if x["code"]=="basalam")
        before=sales_report(self.conn)
        movement=register_movement(self.conn,"receipt",basalam["id"],bank,200000,today(),"receipt-xyz","واریز باسلام")
        self.assertEqual(platform_balances(self.conn)["basalam"]["outstanding"],225000)
        self.assertEqual(accounts(self.conn)[0]["balance"],1200000)
        self.assertEqual(sales_report(self.conn)["gross"],before["gross"])
        self.assertEqual(sales_report(self.conn)["profit"],before["profit"])
        with self.assertRaises(ImportErrorDetail):
            register_movement(self.conn,"receipt",basalam["id"],bank,200000,today(),"receipt-xyz","تکراری")
        self.assertEqual(len(movements(self.conn,"receipt")),1)
        cancel_movement(self.conn,movement)
        self.assertEqual(platform_balances(self.conn)["basalam"]["outstanding"],425000)
        self.assertEqual(accounts(self.conn)[0]["balance"],1000000)
        self.assertIsNotNone(movements(self.conn)[0]["cancelled_at"])
        with self.assertRaises(ImportErrorDetail):cancel_movement(self.conn,movement)

    def test_payment_is_from_selected_bank_to_custom_party_and_not_sale_fee(self):
        self.sale()
        bank=add_account(self.conn,"ملت",1000000)
        new=add_account(self.conn,"تجارت",200000)
        supplier=add_party(self.conn,"تأمین کننده جدید")
        movement=register_movement(self.conn,"payment",supplier,new,130000,today(),"pay-10")
        self.assertEqual([(x["title"],x["balance"]) for x in accounts(self.conn)],[("ملت",1000000),("تجارت",70000)])
        self.assertEqual(platform_balances(self.conn)["basalam"]["outstanding"],425000)
        self.assertEqual(sales_report(self.conn,"basalam")["profit"],345000)
        self.assertEqual(movements(self.conn,"payment")[0]["party_title"],"تأمین کننده جدید")
        cancel_movement(self.conn,movement)
        self.assertEqual(accounts(self.conn)[1]["balance"],200000)

    def test_site_and_mold_known_zero_fee_without_any_digikala_fee(self):
        self.sale("site",price=300000)
        self.assertEqual(sales_report(self.conn,"site")["fees"],0)
        self.assertEqual(platform_balances(self.conn)["site"]["outstanding"],300000)
        self.assertEqual(sales_report(self.conn,"site")["profit"],220000)
        self.assertEqual(sales_report(self.conn)["fees"],0)

    def test_unpriced_cost_makes_profit_unknown_not_zero(self):
        self.conn.execute("DELETE FROM master_cost_history")
        sale=self.sale()
        self.assertIsNone(sale["cogs"])
        self.assertIsNone(sale["profit"])
        self.assertEqual(sales_report(self.conn,"basalam")["unknown_cost_lines"],1)
        self.assertIsNone(sales_report(self.conn,"basalam")["profit"])
        self.assertEqual(platform_balances(self.conn)["basalam"]["outstanding"],425000)

    def test_legacy_v3_basalam_fee_is_computed_and_preserved(self):
        set_channel_prices(self.conn,"basalam","شورت زنانه دارما","","M",500000)
        sku=self.color_skus[("M","مشکی")]
        listing=create_listing(self.conn,"basalam",sku["id"],"قدیمی",1)
        sold=book_sale(self.conn,"basalam",listing,1,"home",today(),"legacy-1")
        self.assertEqual(sold["fees"],75000)
        self.assertEqual(sales_report(self.conn,"basalam")["net"],425000)
        self.conn.execute("UPDATE platform_sales SET commission_toman=NULL WHERE id=?",(sold["sale_id"],))
        self.assertEqual(sales_report(self.conn,"basalam")["fees"],75000)
        self.assertEqual(platform_balances(self.conn)["basalam"]["outstanding"],425000)

    def test_digikala_sales_fee_snapshot_counted_as_receivable(self):
        variant=self.conn.execute("SELECT variant_id FROM products LIMIT 1").fetchone()[0]
        self.conn.execute("""INSERT INTO sales(sale_date,source,variant_id,qty,price_toman,
            commission_toman,processing_toman,vat_toman,fee_toman,cost_toman)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (today(),"seller",variant,2,250000,30000,10000,3000,43000,80000))
        stats=sales_report(self.conn,"digikala")
        self.assertEqual((stats["gross"],stats["fees"],stats["net"],stats["cogs_known"],stats["profit"]),
                         (500000,86000,414000,160000,254000))
        bank=add_account(self.conn,"بانک",0)
        party=next(x for x in parties(self.conn) if x["code"]=="digikala")
        register_movement(self.conn,"receipt",party["id"],bank,100000,today(),"dig-1")
        self.assertEqual(platform_balances(self.conn)["digikala"]["outstanding"],314000)
        self.assertEqual(stats["gross"],sales_report(self.conn,"digikala")["gross"])

    def test_input_safety_and_idempotent_schema(self):
        ensure_finance_schema(self.conn)
        ensure_finance_schema(self.conn)
        self.assertEqual(len(parties(self.conn)),5)
        bank=add_account(self.conn,"صندوق",0)
        with self.assertRaises(ImportErrorDetail):add_account(self.conn,"صندوق",0)
        with self.assertRaises(ImportErrorDetail):add_party(self.conn,"باسلام")
        with self.assertRaises(ImportErrorDetail):
            register_movement(self.conn,"receipt",999999,bank,100,today())
        with self.assertRaises(ImportErrorDetail):
            register_movement(self.conn,"receipt",1,bank,0,today())
        self.assertEqual(len(movements(self.conn)),0)

    def test_real_http_sale_creates_basalam_claim_and_receipt_settles_it(self):
        import os
        from unittest.mock import patch
        from httpx import BasicAuth
        from fastapi.testclient import TestClient
        import daily_sales_service.app as app_mod
        db=str(Path(self.folder.name)/"finance.sqlite3")
        with patch.dict(os.environ,{"SALES_ADMIN_PASSWORD":"t"*32,"SALES_ADMIN_USER":"bridge"}), patch.object(app_mod,"DB",db):
            with TestClient(app_mod.app) as client:
                auth=BasicAuth("bridge","t"*32)
                for path in ("/daily-sales/finance","/daily-sales/finance/accounts",
                             "/daily-sales/finance/movements?section=receipt",
                             "/daily-sales/finance/movements?section=payment",
                             "/daily-sales/finance/sales"):
                    response=client.get(path,auth=auth)
                    self.assertEqual(response.status_code,200,(path,response.text[:160]))
                model=available_models(self.conn,"شورت زنانه دارما")[0]["key"]
                created=client.post("/daily-sales/platforms/basalam/add",auth=auth,
                    data={"model_key":model,"category":"شورت زنانه دارما","pack_qty":"1",
                          "color_1":"مشکی","size":"M","title":"آزمایش مالی باسلام"},
                    follow_redirects=False)
                self.assertEqual(created.status_code,303,created.text[:200])
                variant=list_bundle_variants(self.conn,"basalam")[0]["variant_id"]
                saved=client.post("/daily-sales/pricing/sales/variants/save",auth=auth,
                    data={"channel":"basalam",f"price_{variant}":"500000"},follow_redirects=False)
                self.assertEqual(saved.status_code,303,saved.text[:160])
                sold=client.post("/daily-sales/platforms/basalam/sales/add",auth=auth,
                    data={"variant_id":str(variant),"packs":"1","warehouse":"home",
                          "sale_date":today(),"order_ref":"HTTP-BAS-1"},follow_redirects=False)
                self.assertEqual(sold.status_code,303,sold.text[:160])
                day=client.get("/daily-sales/platforms/basalam/sales",auth=auth)
                self.assertIn("75,000",day.text)
                self.assertIn("345,000",day.text)
                before=client.get("/daily-sales/api/sister-finance.json",auth=auth).json()
                self.assertEqual(before["platforms"]["basalam"]["outstanding"],425000)
                bank=client.post("/daily-sales/finance/accounts/add",auth=auth,
                    data={"title":"ملت تست","opening":"100000"},follow_redirects=False)
                self.assertEqual(bank.status_code,303)
                bank_id=accounts(self.conn)[0]["id"]
                basalam=next(p for p in parties(self.conn) if p["code"]=="basalam")
                received=client.post("/daily-sales/finance/movements/add",auth=auth,
                    data={"kind":"receipt","party_id":str(basalam["id"]),
                          "account_id":str(bank_id),"amount":"200000",
                          "movement_date":today(),"reference":"HTTP-REC-1"},follow_redirects=False)
                self.assertEqual(received.status_code,303,received.text[:200])
                after=client.get("/daily-sales/api/sister-finance.json",auth=auth).json()
                self.assertEqual(after["platforms"]["basalam"]["outstanding"],225000)
                self.assertEqual(after["accounts"][0]["balance"],300000)
                self.assertEqual(after["sales"]["profit"],345000)
                self.assertEqual(after["sales"]["gross"],500000)
                movement=movements(self.conn)[0]["id"]
                cancelled=client.post("/daily-sales/finance/movements/cancel",auth=auth,
                    data={"movement_id":str(movement),"return_kind":"receipt"},
                    follow_redirects=False)
                self.assertEqual(cancelled.status_code,303)
                self.assertEqual(client.get("/daily-sales/api/sister-finance.json",
                    auth=auth).json()["platforms"]["basalam"]["outstanding"],425000)

    def test_finance_routes_and_html_show_derived_claims(self):
        from daily_sales_service.sister_finance_api import (
            router,finance_home,finance_accounts,finance_movements,all_sales
        )
        routes={r.path for r in router.routes if hasattr(r,"path")}
        for tail in ("/finance","/finance/accounts","/finance/movements",
                     "/finance/accounts/add","/finance/parties/add",
                     "/finance/movements/add","/finance/movements/cancel",
                     "/finance/sales","/api/sister-finance.json"):
            self.assertIn("/daily-sales"+tail,routes)
        self.sale()
        self.assertIn("باسلام",finance_accounts(conn=self.conn).body.decode())
        self.assertIn("425,000",finance_accounts(conn=self.conn).body.decode())
        self.assertIn("دیجی‌کالا",finance_movements(conn=self.conn).body.decode())
        self.assertIn("75,000",all_sales(channel="basalam",conn=self.conn).body.decode())
        self.assertIn("مالی و حسابداری",finance_home(conn=self.conn).body.decode())

if __name__=="__main__":unittest.main()
