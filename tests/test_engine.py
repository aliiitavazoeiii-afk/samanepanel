import io, tempfile, unittest, zipfile
from decimal import Decimal
from pathlib import Path
from daily_sales_service.engine import init_db, fee_unit, settings_for, create_preview,commit_preview,report,ImportErrorDetail


def make_xlsx(rows):
 import xml.etree.ElementTree as ET
 ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
 root=ET.Element('worksheet',xmlns=ns);data=ET.SubElement(root,'sheetData')
 for i,row in enumerate(rows,1):
  r=ET.SubElement(data,'row',r=str(i))
  for j,value in enumerate(row):
   col='';k=j+1
   while k: k,remainder=divmod(k-1,26);col=chr(65+remainder)+col
   cell=ET.SubElement(r,'c',r=f'{col}{i}',t='inlineStr')
   inline=ET.SubElement(cell,'is');ET.SubElement(inline,'t').text=str(value)
 workbook=f'<workbook xmlns="{ns}"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/></sheets></workbook>'
 b=io.BytesIO()
 with zipfile.ZipFile(b,'w') as z:
  z.writestr('xl/workbook.xml',workbook)
  z.writestr('xl/worksheets/sheet1.xml',ET.tostring(root,encoding='utf-8'))
 return b.getvalue()

class DailySalesTest(unittest.TestCase):
 def setUp(self):
  self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
  self.conn=init_db(Path(self.folder.name)/'test.sqlite3')
  self.addCleanup(self.conn.close)
  self.products=self.conn.execute('SELECT * FROM products').fetchall()
  self.assertEqual(len(self.products),538)
  self.assertEqual(len({r['variant_id'] for r in self.products}),538)
 def test_catalog_numbers(self):
  x=self.conn.execute('SELECT category, COUNT(*) c FROM products GROUP BY category').fetchall()
  self.assertEqual(sum(r['c'] for r in x),538)
  self.assertEqual(self.conn.execute('SELECT SUM(seller_stock) FROM products').fetchone()[0],9928)
  self.assertEqual(self.conn.execute('SELECT SUM(digikala_stock) FROM products').fetchone()[0],85)
 def test_fee_commissions_floor_and_vat(self):
  s=settings_for(self.conn)
  f=fee_unit(500000,'شورت مردانه',s)
  self.assertEqual(f['commission'],121500) # 24.3%
  self.assertEqual(f['processing'],36000) # 7% < floor
  self.assertEqual(f['vat'],13050 + 900) # 10%*(121500+18000) = 13950
  self.assertEqual(f['fee'],171450)
  shoe=fee_unit(2000000,'مراقبت کفش و لوازم جانبی',s)
  self.assertEqual(shoe['commission'],450000)
  self.assertEqual(shoe['processing'],140000)
  self.assertEqual(shoe['vat'],52000)
  women=fee_unit(500000,'شورت زنانه',s)
  self.assertEqual(women['commission'],120000)
 def test_import_preview_commit_idempotence_and_replace(self):
  item=next(x for x in self.products if x['seller_stock']>=3 and x['active'])
  variant=item['variant_id'];start=item['seller_stock'];self.conn.execute('UPDATE products SET cost_toman=100000 WHERE variant_id=?',(variant,))
  mk=lambda qty: [('order.xlsx',make_xlsx([['کد تنوع','تعداد ارسالی','وضعیت','قیمت فروش (تومان)'],[variant,qty,'دریافت',500000]]))]
  day='2026-10-28'
  first=create_preview(self.conn,day,'seller',mk(2))
  self.assertEqual(first['rows'][0]['qty'],2)
  self.assertEqual(self.conn.execute('SELECT seller_stock FROM products WHERE variant_id=?',(variant,)).fetchone()[0],start)
  commit_preview(self.conn,first['token'])
  self.assertEqual(self.conn.execute('SELECT seller_stock FROM products WHERE variant_id=?',(variant,)).fetchone()[0],start-2)
  again=create_preview(self.conn,day,'seller',mk(2));commit_preview(self.conn,again['token'])
  self.assertEqual(self.conn.execute('SELECT seller_stock FROM products WHERE variant_id=?',(variant,)).fetchone()[0],start-2)
  revised=create_preview(self.conn,day,'seller',mk(1));commit_preview(self.conn,revised['token'])
  self.assertEqual(self.conn.execute('SELECT seller_stock FROM products WHERE variant_id=?',(variant,)).fetchone()[0],start-1)
  result=report(self.conn)
  self.assertEqual(result['units'],1);self.assertIsNotNone(result['profit'])
  self.assertEqual(result['gross'],500000)
  self.assertEqual(result['profit'],500000-result['fee']-100000)
  self.assertEqual(self.conn.execute('SELECT SUM(delta) FROM stock_events WHERE variant_id=?',(variant,)).fetchone()[0],-1)
 def test_missing_cost_is_unknown_not_zero(self):
  x=next(x for x in self.products if x['seller_stock']>=1 and x['active'])
  file=make_xlsx([['کد تنوع','تعداد ارسالی'],[x['variant_id'],1]])
  p=create_preview(self.conn,'2026-10-28','seller',[('report.xlsx',file)]);commit_preview(self.conn,p['token'])
  r=report(self.conn)
  self.assertIsNone(r['profit']);self.assertEqual(r['unknown_cost_lines'],1)
 def test_stock_insufficiency_fail_closed(self):
  item=next(x for x in self.products if x['seller_stock']==0 and x['active'])
  file=make_xlsx([['کد تنوع','تعداد ارسالی'],[item['variant_id'],1]])
  p=create_preview(self.conn,'2026-10-27','seller',[('report.xlsx',file)])
  self.assertTrue(p['errors']);self.assertNotIn('token',p)
 def test_unknown_variant_fails_closed(self):
  file=make_xlsx([['کد تنوع','تعداد ارسالی'],[999999999999,1]])
  p=create_preview(self.conn,'2026-10-27','seller',[('report.xlsx',file)])
  self.assertTrue(p['errors'])

if __name__=='__main__':unittest.main()
