"""Regression checks for sister SKU master and aggregated DigiKala stock."""
import os
import tempfile
import unittest
from pathlib import Path

from test_engine import make_xlsx
from daily_sales_service.engine import init_db,create_preview,commit_preview,report,ImportErrorDetail
from daily_sales_service.master_engine import add_master,adjust_master_stock,map_variant,CATEGORIES

class UnifiedStockTest(unittest.TestCase):
 def setUp(self):
  self.before=os.environ.get('SALES_MASTER_STRICT')
  os.environ['SALES_MASTER_STRICT']='1'
  self.addCleanup(self.restore)
  self.tmp=tempfile.TemporaryDirectory()
  self.addCleanup(self.tmp.cleanup)
  self.conn=init_db(Path(self.tmp.name)/'sales.sqlite3')
  self.addCleanup(self.conn.close)
  self.a,self.b=[x['variant_id'] for x in self.conn.execute('SELECT variant_id FROM products WHERE active=1 LIMIT 2')]

 def restore(self):
  if self.before is None:os.environ.pop('SALES_MASTER_STRICT',None)
  else:os.environ['SALES_MASTER_STRICT']=self.before

 def sample(self,rows):
  return [('delivered.xlsx',make_xlsx([['کد تنوع','تعداد ارسالی','وضعیت','قیمت فروش (تومان)']]+
      [[vid,qty,'دریافت',500000] for vid,qty in rows]))]

 def test_master_categories_and_stock_audit(self):
  self.assertEqual(len(CATEGORIES),5)
  self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM master_products').fetchone()[0],0)
  mid=add_master(self.conn,'زیرپوش دارما','U-001','زیرپوش',size='L',color='مشکی',sale_price=500000,cost=100000)
  adjust_master_stock(self.conn,mid,'seller',6,'شمارش اولیه انبار')
  row=self.conn.execute('SELECT seller_stock, digikala_stock FROM master_products WHERE id=?',(mid,)).fetchone()
  self.assertEqual((row[0],row[1]),(6,0))
  audit=self.conn.execute('SELECT delta,balance_after FROM master_stock_events WHERE master_id=?',(mid,)).fetchone()
  self.assertEqual((audit['delta'],audit['balance_after']),(6,6))
  with self.assertRaises(ImportErrorDetail):
   add_master(self.conn,'زیرپوش دارما','U-001','تکراری',size='L',color='مشکی')

 def test_two_variants_same_real_stock_replace_and_no_double_deduct(self):
  mid=add_master(self.conn,'زیرپوش دارما','V-01','زیرپوش',size='L',color='مشکی',sale_price=500000,cost=100000)
  adjust_master_stock(self.conn,mid,'seller',6,'شمارش اولیه')
  map_variant(self.conn,self.a,mid,500000);map_variant(self.conn,self.b,mid,500000)
  day='2026-10-31'
  def stock():return self.conn.execute('SELECT seller_stock FROM master_products WHERE id=?',(mid,)).fetchone()[0]
  a=create_preview(self.conn,day,'seller',self.sample([(self.a,2),(self.b,3)]))
  self.assertFalse(a['errors'],a['errors'])
  self.assertEqual(stock(),6)
  commit_preview(self.conn,a['token'])
  self.assertEqual(stock(),1)
  b=create_preview(self.conn,day,'seller',self.sample([(self.a,2),(self.b,3)]))
  commit_preview(self.conn,b['token'])
  self.assertEqual(stock(),1)
  c=create_preview(self.conn,day,'seller',self.sample([(self.a,1),(self.b,1)]))
  commit_preview(self.conn,c['token'])
  self.assertEqual(stock(),4)
  self.assertEqual(report(self.conn)['units'],2)
  self.assertEqual(self.conn.execute('SELECT SUM(delta) FROM master_stock_events WHERE reference LIKE "digikala:%"').fetchone()[0],-2)
  audit=self.conn.execute('SELECT balance_after FROM master_stock_events WHERE reference LIKE "digikala:%" ORDER BY id DESC LIMIT 1').fetchone()
  self.assertEqual(audit['balance_after'],4)
  with self.assertRaises(ImportErrorDetail):
   newmid=add_master(self.conn,'قالب','SH-1','قالب',color='سفید')
   map_variant(self.conn,self.a,newmid,100000)

 def test_fails_if_variant_not_mapped(self):
  x=create_preview(self.conn,'2026-10-31','seller',self.sample([(self.a,1)]))
  self.assertTrue(x['errors'])
  self.assertIn('متصل نیست',x['errors'][0] if x['errors'] else '')

 def test_insufficient_stock_aggregates_multiple_variants(self):
  mid=add_master(self.conn,'قالب','S-21','قالب',size='42',color='مشکی',sale_price=500000)
  adjust_master_stock(self.conn,mid,'seller',3,'شمارش اولیه')
  map_variant(self.conn,self.a,mid,500000);map_variant(self.conn,self.b,mid,500000)
  x=create_preview(self.conn,'2026-10-31','seller',self.sample([(self.a,2),(self.b,2)]))
  self.assertTrue(x['errors'])
  self.assertIn('موجودی ناکافی',x['errors'][0])
  self.assertEqual(self.conn.execute('SELECT seller_stock FROM master_products WHERE id=?',(mid,)).fetchone()[0],3)

if __name__=='__main__': unittest.main()
