"""Safe bankless platform receipts and business-by-product sale accounting."""
import tempfile
import unittest
from pathlib import Path

from daily_sales_service.engine import init_db,ImportErrorDetail
from daily_sales_service.effective_costs import today
from daily_sales_service.sister_finance_logic import (
    parties,accounts,platform_balances,sales_report,business_sales_report,overview
)
from daily_sales_service.sister_finance_bankless_v1 import (
    record_receipt,cancel_receipt,receipt_history,received_total,ensure_schema
)


class BanklessMarketplaceReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.conn=init_db(Path(self.temp.name)/"bankless.sqlite3")
        self.addCleanup(self.conn.close)
        self.variant=self.conn.execute("SELECT variant_id FROM products LIMIT 1").fetchone()[0]
        self.conn.execute("""INSERT INTO sales(sale_date,source,variant_id,qty,price_toman,
            commission_toman,processing_toman,vat_toman,fee_toman,cost_toman)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (today(),"seller",self.variant,2,250000,30000,10000,3000,43000,80000))
        self.party=next(p for p in parties(self.conn) if p["code"]=="digikala")

    def test_bankless_receipt_reduces_claim_without_affecting_sales_or_accounts(self):
        previous=sales_report(self.conn,"digikala")
        before=platform_balances(self.conn)["digikala"]
        self.assertEqual(before["outstanding"],414000)
        count=self.conn.execute("SELECT COUNT(*) FROM sister_finance_accounts").fetchone()[0]
        identifier=record_receipt(self.conn,self.party["id"],100000,today(),
                                  "idempotent-dk-1","bank-ref-1","واریزی دیجی‌کالا")
        after=platform_balances(self.conn)["digikala"]
        self.assertEqual(after["outstanding"],314000)
        self.assertEqual(after["received"],100000)
        self.assertEqual(overview(self.conn)["receipts"],100000)
        self.assertEqual(received_total(self.conn),100000)
        self.assertEqual(sales_report(self.conn,"digikala")["gross"],previous["gross"])
        self.assertEqual(sales_report(self.conn,"digikala")["profit"],previous["profit"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM sister_finance_accounts").fetchone()[0],count)
        self.assertEqual(accounts(self.conn),[])
        self.assertEqual(len(receipt_history(self.conn)),1)
        with self.assertRaises(ImportErrorDetail):
            record_receipt(self.conn,self.party["id"],100000,today(),
                           "idempotent-dk-1")
        with self.assertRaises(ImportErrorDetail):
            record_receipt(self.conn,self.party["id"],100000,today(),
                           "different-key","bank-ref-1")
        with self.assertRaises(ImportErrorDetail):
            record_receipt(self.conn,self.party["id"],400000,today(),
                           "too-large")
        self.assertEqual(platform_balances(self.conn)["digikala"]["outstanding"],314000)
        cancel_receipt(self.conn,identifier)
        self.assertEqual(platform_balances(self.conn)["digikala"]["outstanding"],414000)
        self.assertEqual(received_total(self.conn),0)
        with self.assertRaises(ImportErrorDetail):cancel_receipt(self.conn,identifier)

    def test_does_not_make_business_revenue_when_payment_arrives(self):
        before=business_sales_report(self.conn)
        record_receipt(self.conn,self.party["id"],50000,today(),"business-no-dup")
        self.assertEqual(before,business_sales_report(self.conn))

    def test_unlinked_variant_has_separate_unknown_business(self):
        by_business=business_sales_report(self.conn)
        self.assertEqual(len(by_business),1)
        self.assertEqual(by_business[0]["business"],"نامشخص / نیازمند اتصال")
        self.assertEqual(by_business[0]["gross"],500000)

    def test_schema_is_idempotent_and_only_platform_party_can_settle(self):
        ensure_schema(self.conn)
        ensure_schema(self.conn)
        other=self.conn.execute("""INSERT INTO sister_finance_parties
             (code,title,is_platform,created_at) VALUES('person-test','شخص تست',0,'now')""").lastrowid
        with self.assertRaises(ImportErrorDetail):
            record_receipt(self.conn,other,10000,today(),"not-platform")
        with self.assertRaises(ImportErrorDetail):
            record_receipt(self.conn,self.party["id"],0,today(),"zero")
        self.assertEqual(received_total(self.conn),0)

if __name__=="__main__":
    unittest.main()
