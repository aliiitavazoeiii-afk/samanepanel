import unittest
from daily_sales_service.mehr_document_positions_v1 import summarize_mehr_documents

class MehrDocumentPositionTests(unittest.TestCase):
    def test_separate_invoice_surplus_does_not_invent_net_credit(self):
        items=[
          {"kind":"invoice","id":1,"label":"واش‌ماش","date":"2026-09-06","gross":76000000,"credit":58000000,"paid":18000000},
          {"kind":"invoice","id":2,"label":"مدرنا","date":"2026-09-06","gross":113500000,"credit":77750000,"paid":0},
          {"kind":"invoice","id":3,"label":"بوستان چرم","date":"2026-09-06","gross":41000000,"credit":50000000,"paid":0},
          {"kind":"invoice","id":4,"label":"اکتیو کلینیر","date":"2026-10-07","gross":202500000,"credit":262500000,"paid":0},
          {"kind":"invoice","id":5,"label":"سجاد","date":"2026-11-22","gross":583000000,"credit":587000000,"paid":0},
          {"kind":"invoice","id":6,"label":"چرم شیک","date":"2026-11-10","gross":45000000,"credit":0,"paid":0},
          {"kind":"purchase","id":1,"label":"خرید","date":"2026-11-06","gross":41496000,"credit":0,"paid":0},
        ]
        p=summarize_mehr_documents(items,{"net":-49246000})
        self.assertEqual(p["invoice_excess"],73000000)
        self.assertEqual(p["invoice_due"],80750000)
        self.assertEqual(p["purchases_due"],41496000)
        self.assertEqual(p["documents_net"],-49246000)
        self.assertEqual(p["unallocated_difference"],0)
        self.assertEqual(p["net_claim"],0)
        self.assertEqual(p["net_payable"],49246000)

    def test_receivable_positive_does_not_change_ledger_net(self):
        rows=[{"kind":"invoice","id":2,"label":"فاکتور","date":"2026-10-01","gross":400,"credit":650,"paid":0}]
        result=summarize_mehr_documents(rows,{"net":250})
        self.assertEqual(result["invoice_excess"],250)
        self.assertEqual(result["net_claim"],250)
        self.assertEqual(result["net_payable"],0)
        self.assertEqual(result["unallocated_difference"],0)

    def test_nonallocated_adjustment_is_visible_not_silently_distributed(self):
        rows=[{"kind":"invoice","id":2,"label":"فاکتور","date":"2026-10-01","gross":100,"credit":120,"paid":0}]
        result=summarize_mehr_documents(rows,{"net":10})
        self.assertEqual(result["invoice_excess"],20)
        self.assertEqual(result["net_claim"],10)
        self.assertEqual(result["unallocated_difference"],-10)

if __name__=="__main__":
    unittest.main()
